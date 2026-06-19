#!/usr/bin/env bash

set -euo pipefail

PREFETCH_LAUNCHD_ROOT_DIR="${PREFETCH_LAUNCHD_ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PREFETCH_LAUNCHD_DEFAULT_LABEL="${PREFETCH_LAUNCHD_DEFAULT_LABEL:-com.aws-cost-dashboard.prefetch}"

prefetch_launchd_domain() {
  printf 'gui/%s' "$(id -u)"
}

prefetch_launchd_target() {
  local label="$1"
  printf '%s/%s' "$(prefetch_launchd_domain)" "$label"
}

prefetch_launchd_plist_path() {
  local label="$1"
  printf '%s/Library/LaunchAgents/%s.plist' "$HOME" "$label"
}

prefetch_launchd_log_dir() {
  printf '%s/data/logs' "$PREFETCH_LAUNCHD_ROOT_DIR"
}

prefetch_launchd_stdout_log() {
  printf '%s/prefetch-launchd.log' "$(prefetch_launchd_log_dir)"
}

prefetch_launchd_stderr_log() {
  printf '%s/prefetch-launchd.err' "$(prefetch_launchd_log_dir)"
}

prefetch_launchd_require_launchctl() {
  if ! command -v launchctl >/dev/null 2>&1; then
    echo "launchctl が見つかりません。この task は macOS launchd 用です。" >&2
    exit 1
  fi
}

prefetch_launchd_is_registered() {
  local label="$1"
  launchctl print "$(prefetch_launchd_target "$label")" >/dev/null 2>&1
}

prefetch_launchd_prepare_logs() {
  mkdir -p "$(prefetch_launchd_log_dir)"
  touch "$(prefetch_launchd_stdout_log)" "$(prefetch_launchd_stderr_log)"
}

prefetch_launchd_print_paths() {
  local label="$1"
  printf 'plist : %s\n' "$(prefetch_launchd_plist_path "$label")"
  printf 'stdout: %s\n' "$(prefetch_launchd_stdout_log)"
  printf 'stderr: %s\n' "$(prefetch_launchd_stderr_log)"
}

prefetch_launchd_print_not_registered() {
  local label="$1"
  echo "launchd job は登録されていません: $label"
  echo "  install: mise run prefetch-launchd-install"
}
