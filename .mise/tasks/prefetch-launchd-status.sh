#!/usr/bin/env bash
#MISE description="Show the macOS launchd prefetch job status"
#MISE quiet=true

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT_DIR/.mise/scripts/prefetch-launchd-common.sh"

LABEL="$PREFETCH_LAUNCHD_DEFAULT_LABEL"
VERBOSE="false"

usage() {
  cat <<'USAGE'
Show the launchd prefetch job status.

Usage:
  mise run prefetch-launchd-status -- [--label LABEL] [-v|--verbose]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  --label)
    LABEL="${2:?--label requires a value}"
    shift 2
    ;;
  -v | --verbose)
    VERBOSE="true"
    shift
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

prefetch_launchd_require_launchctl

TARGET="$(prefetch_launchd_target "$LABEL")"
RAW="$(launchctl print "$TARGET" 2>/dev/null)" || {
  prefetch_launchd_print_not_registered "$LABEL"
  prefetch_launchd_print_paths "$LABEL"
  exit 1
}

field() {
  printf '%s\n' "$RAW" | awk -F'= ' -v key="$1" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      value = $2
      sub(/^[[:space:]]+/, "", value)
      print value
      exit
    }
  '
}

STATE="$(field state)"
PID="$(field pid)"
RUNS="$(field runs)"
LAST_EXIT="$(field 'last exit code')"

printf 'label     : %s\n' "$LABEL"
printf 'target    : %s\n' "$TARGET"
printf 'state     : %s\n' "${STATE:-unknown}"
printf 'pid       : %s\n' "${PID:-(none)}"
printf 'runs      : %s\n' "${RUNS:-0}"
printf 'last exit : %s\n' "${LAST_EXIT:-(none)}"
prefetch_launchd_print_paths "$LABEL"

if [[ "$VERBOSE" == "true" ]]; then
  echo ""
  printf '%s\n' "$RAW"
else
  echo ""
  echo "詳細を見る場合: mise run prefetch-launchd-status -- --verbose"
fi
