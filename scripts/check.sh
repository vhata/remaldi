#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${REMALDI_PYTHON:-python3}"
"$PYTHON" -m ruff format --check .
"$PYTHON" -m ruff check .
"$PYTHON" -m mypy
"$PYTHON" scripts/audit-secrets.py
"$PYTHON" -m unittest discover -s tests -v
