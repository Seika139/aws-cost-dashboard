#!/usr/bin/env bash

#MISE description="format"
#MISE quiet=true

set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/common.sh"

print_blue "Format Markdown / TOML / JSON with dprint"$'\n'
dprint fmt

print_blue "Format Python files with ruff"$'\n'
uv run ruff format src/ tests/ .mise/
uv run ruff check --fix src/ tests/ .mise/

print_blue "Format shell scripts with shfmt"$'\n'
shfmt -w .mise/common.sh .mise/tasks/*.sh .mise/scripts/*.sh

print_blue "Format YAML files with yamllint"$'\n'
yamllint -f parsable . | while IFS= read -r line; do
  # yamllint の出力をパースして、ファイル名と行番号を抽出
  if [[ "$line" =~ ^([^:]+):([0-9]+):([0-9]+):\ (.*)$ ]]; then
    file="${BASH_REMATCH[1]}"
    line_num="${BASH_REMATCH[2]}"
    col_num="${BASH_REMATCH[3]}"
    message="${BASH_REMATCH[4]}"
    # sed を使って該当行を修正（ここでは単純に行末のスペースを削除する例）
    # `-i.bak` は BSD/GNU 双方で in-place 編集として動く portable 形式。
    # `-E` (ERE) で `\+` を `+` に統一し、BSD/GNU 間の正規表現方言差を回避。
    sed -i.bak -E "${line_num}s/[[:space:]]+$//" "$file" && rm -f "$file.bak"
    print_green "Fixed $file:${line_num}:${col_num}: $message"$'\n'
  fi
done
