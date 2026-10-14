#!/usr/bin/env bash
# Apply the automatic fixes that scripts/check.sh would otherwise report.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run --locked ruff check --fix .
uv run --locked ruff format .
git ls-files -z -- 'scripts/*.sh' | xargs -0 uv run --locked shfmt --write
