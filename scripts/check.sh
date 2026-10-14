#!/usr/bin/env bash
# The shared gate. Git hooks, CI and agents all run this script; every tool
# comes from the locked dev dependency group, so a stale uv.lock fails here.
# Portable to bash 3.2, the macOS system shell.
set -euo pipefail
cd "$(dirname "$0")/.."

run() { uv run --locked "$@"; }
# files PATHSPEC... TOOL ARGS...: run a tool over the tracked files matching
# the pathspecs (docket/ is vendored and checked upstream).
files() {
  local specs=()
  while [ "$1" != "--" ]; do
    specs+=("$1")
    shift
  done
  shift
  git ls-files -z -- "${specs[@]}" ':!docket' | xargs -0 uv run --locked "$@"
}

# Python formatting, lint and types.
run ruff format --check .
run ruff check .
run mypy
run basedpyright

# Shell scripts, workflows and spelling.
files 'scripts/*.sh' -- shfmt --diff
files 'scripts/*.sh' -- shellcheck
run actionlint
run zizmor --offline .github/workflows
run typos

# Repository hygiene: whitespace errors, conflict markers, TOML and YAML
# syntax, and shebangs agreeing with the executable bit.
git diff --check "$(git hash-object -t tree /dev/null)" -- . ':!docket'
files . -- check-merge-conflict
files '*.toml' -- check-toml
files '*.yml' '*.yaml' -- check-yaml
files . -- check-executables-have-shebangs
files . -- check-shebang-scripts-are-executable

run python scripts/audit-secrets.py

# pytest exits nonzero when it collects no tests.
run pytest --cov

bash docket/scripts/check-queues.sh --strict
bash docket/scripts/check-links.sh
