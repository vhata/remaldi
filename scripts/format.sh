#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${REMALDI_PYTHON:-python3}"
"$PYTHON" -m ruff check --fix .
"$PYTHON" -m ruff format .
