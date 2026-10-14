#!/usr/bin/env bash
# Create the project environment from uv.lock and install the Git hooks.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --locked
uv run --locked pre-commit install --hook-type pre-commit --hook-type pre-push
