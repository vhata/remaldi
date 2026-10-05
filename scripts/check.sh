#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${REMALDI_PYTHON:-python3}"
"$PYTHON" -m ruff format --check .
"$PYTHON" -m ruff check .
"$PYTHON" -m mypy
"$PYTHON" scripts/audit-secrets.py
"$PYTHON" -c 'import unittest; suite = unittest.defaultTestLoader.discover("tests"); count = suite.countTestCases(); print(f"Collected {count} tests"); raise SystemExit(0 if count else "No tests collected")'
"$PYTHON" -m unittest discover -s tests -v
bash scripts/workflow/check-queues.sh --strict
bash scripts/workflow/check-links.sh
