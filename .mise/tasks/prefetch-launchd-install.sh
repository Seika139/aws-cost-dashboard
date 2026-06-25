#!/usr/bin/env bash
#MISE description="Register/update the macOS launchd prefetch job"
#MISE quiet=true

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/.mise/scripts/prefetch-launchd-common.sh"

LABEL="$PREFETCH_LAUNCHD_DEFAULT_LABEL"
HOUR=""
MINUTE=""
TIMES=()

usage() {
  cat <<'USAGE'
Register or update the macOS launchd prefetch job.

Usage:
  mise run prefetch-launchd-install -- [--time HH:MM ...] [--label LABEL]
  mise run prefetch-launchd-install -- [--hour H --minute M] [--label LABEL]

Default schedule:
  11:30 and 14:30 local time

The installed job runs:
  mise run prefetch-cost -- --preset dashboard-default

That preset uses Config tab default accounts and prefetches:
  - MONTHLY: last 24 months including the current month
  - DAILY: last 4 months including the current month
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  --time)
    TIMES+=("${2:?--time requires a value}")
    shift 2
    ;;
  --hour)
    HOUR="${2:?--hour requires a value}"
    shift 2
    ;;
  --minute)
    MINUTE="${2:?--minute requires a value}"
    shift 2
    ;;
  --label)
    LABEL="${2:?--label requires a value}"
    shift 2
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
  esac
done

normalize_time() {
  local raw="$1"
  if [[ ! "$raw" =~ ^([0-9]{1,2}):([0-9]{1,2})$ ]]; then
    echo "Time must be HH:MM: $raw" >&2
    exit 2
  fi

  local hour="${BASH_REMATCH[1]}"
  local minute="${BASH_REMATCH[2]}"
  if ((10#$hour < 0 || 10#$hour > 23)); then
    echo "Hour must be an integer from 0 to 23: $raw" >&2
    exit 2
  fi
  if ((10#$minute < 0 || 10#$minute > 59)); then
    echo "Minute must be an integer from 0 to 59: $raw" >&2
    exit 2
  fi

  printf "%02d:%02d" "$((10#$hour))" "$((10#$minute))"
}

if [[ -n "$HOUR" || -n "$MINUTE" ]]; then
  if [[ -z "$HOUR" || -z "$MINUTE" ]]; then
    echo "--hour and --minute must be provided together" >&2
    exit 2
  fi
  TIMES=("${HOUR}:${MINUTE}")
fi

if [[ "${#TIMES[@]}" -eq 0 ]]; then
  TIMES=("11:30" "14:30")
fi

NORMALIZED_TIMES=()
for time in "${TIMES[@]}"; do
  NORMALIZED_TIMES+=("$(normalize_time "$time")")
done

SCHEDULE_TEXT="${NORMALIZED_TIMES[0]}"
for ((i = 1; i < ${#NORMALIZED_TIMES[@]}; i++)); do
  SCHEDULE_TEXT+=", ${NORMALIZED_TIMES[$i]}"
done

CALENDAR_INTERVAL_XML="  <array>"
for time in "${NORMALIZED_TIMES[@]}"; do
  hour="${time%%:*}"
  minute="${time##*:}"
  CALENDAR_INTERVAL_XML+="
    <dict>
      <key>Hour</key>
      <integer>$((10#$hour))</integer>
      <key>Minute</key>
      <integer>$((10#$minute))</integer>
    </dict>"
done
CALENDAR_INTERVAL_XML+="
  </array>"

prefetch_launchd_require_launchctl

MISE_BIN="$(command -v mise || true)"
if [[ -z "$MISE_BIN" ]]; then
  echo "mise was not found in PATH. Install mise first." >&2
  exit 1
fi

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="$(prefetch_launchd_plist_path "$LABEL")"
LOG_DIR="$(prefetch_launchd_log_dir)"

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

cat >"$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT_DIR}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${MISE_BIN}</string>
    <string>run</string>
    <string>prefetch-cost</string>
    <string>--</string>
    <string>--preset</string>
    <string>dashboard-default</string>
  </array>
  <key>StartCalendarInterval</key>
${CALENDAR_INTERVAL_XML}
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/prefetch-launchd.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/prefetch-launchd.err</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH" >/dev/null

launchctl bootout "$(prefetch_launchd_domain)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "$(prefetch_launchd_domain)" "$PLIST_PATH"
launchctl enable "$(prefetch_launchd_target "$LABEL")" >/dev/null 2>&1 || true

echo "Installed launchd job: $LABEL"
echo "Schedule: daily at ${SCHEDULE_TEXT} local time"
prefetch_launchd_print_paths "$LABEL"
