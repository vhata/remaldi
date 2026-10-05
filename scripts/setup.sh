#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${REMALDI_PYTHON:-/Users/jonathan.hitchcock/.venv/3.12/bin/python}"
"$PYTHON" -m pip install -e '.[dev]'
"$PYTHON" -m pre_commit install --hook-type pre-commit --hook-type pre-push
