#!/usr/bin/env bash
# Apply the automatic fixes that scripts/check.sh would otherwise report.
set -euo pipefail
cd "$(dirname "$0")/.."

shell_scripts=()
while IFS= read -r -d '' path; do
  shell_scripts+=("$path")
done < <(git ls-files -z -- 'scripts/*.sh')

uv run --locked ruff check --fix .
uv run --locked ruff format .
uv run --locked shfmt --write "${shell_scripts[@]}"
