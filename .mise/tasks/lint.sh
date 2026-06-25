#!/usr/bin/env bash

#MISE description="lint"
#MISE quiet=true

set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/common.sh"

print_blue "Linting Markdown files"$'\n'
rumdl check .

print_blue "Lint Python files with ruff"$'\n'
uv run ruff check src/ tests/ .mise/

print_blue "Lint shell scripts with shfmt & shellcheck"$'\n'
shfmt -d .mise/common.sh .mise/tasks/*.sh .mise/scripts/*.sh
shellcheck_files=()
while IFS= read -r -d '' file; do
  shellcheck_files+=("$file")
done < <(find . -type f \( -name "*.sh" -o -name "*.bash" \) -not -path "./.venv/*" -not -path "./node_modules/*" -not -path "./.git/*" -not -path "./raw/*" -not -path "./tmp/*" -not -path "./.serena/*" -print0)
if [ "${shellcheck_files[0]+_}" ]; then
  shellcheck -x -P SCRIPTDIR "${shellcheck_files[@]}"
else
  print_red "No shell scripts found; skipping shellcheck."$'\n'
fi

print_blue "Lint toml with taplo"$'\n'
taplo fmt --check --diff

print_blue "Lint YAML files with yamllint"$'\n'
yamllint .
