#!/usr/bin/env bash
# Report known vulnerabilities in every locked dependency, dev group included.
# Needs network access to the advisory database, so it runs on the daily main
# validation rather than in scripts/check.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT
uv export --locked --all-groups --no-emit-project --format requirements.txt \
  --quiet --output-file "$requirements"
uv run --locked pip-audit --disable-pip --strict --progress-spinner off \
  --requirement "$requirements"
