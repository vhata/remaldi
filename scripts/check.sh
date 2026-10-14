#!/usr/bin/env bash
# The shared gate. Git hooks, CI and agents all run this script; every tool
# comes from the locked dev dependency group, so a stale uv.lock fails here.
# Portable to bash 3.2, the macOS system shell.
set -euo pipefail
cd "$(dirname "$0")/.."

run() { uv run --locked "$@"; }
# files PATHSPEC... -- TOOL ARGS...: run a tool over the tracked files matching
# the pathspecs (docket/ is vendored and checked upstream). An empty match is
# an error, since most tools would silently read standard input instead.
files() {
  local specs=() matched=() path
  while [ "$1" != "--" ]; do
    specs+=("$1")
    shift
  done
  shift
  while IFS= read -r -d '' path; do
    matched+=("$path")
  done < <(git ls-files -z -- "${specs[@]}" ':!docket')
  if [ "${#matched[@]}" -eq 0 ]; then
    echo "check: no tracked files match ${specs[*]}" >&2
    return 1
  fi
  run "$@" "${matched[@]}"
}
# executables TOOL ARGS...: run a tool over tracked files with mode 100755.
executables() {
  local matched=() path
  while IFS= read -r path; do
    matched+=("$path")
  done < <(git ls-files --format='%(objectmode) %(path)' -- . ':!docket' | sed -n 's/^100755 //p')
  if [ "${#matched[@]}" -eq 0 ]; then
    echo "check: no tracked executables" >&2
    return 1
  fi
  run "$@" "${matched[@]}"
}

# Python formatting, lint and types.
echo "DEBUG ls-files count: $(git ls-files | wc -l)"
git ls-files -- scripts | head -5
echo "DEBUG glob:"
git ls-files -- 'scripts/*.sh' | head -3
echo "DEBUG excl:"
git ls-files -- 'scripts/*.sh' ':!docket' | head -3
echo "DEBUG env:"
env | grep -i -E '^GIT_|LITERAL|ICASE' || true
git config --list --show-origin | grep -v -i -E 'token|extraheader|url' | head -20
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
executables check-executables-have-shebangs
files . -- check-shebang-scripts-are-executable

run python scripts/audit-secrets.py

# pytest exits nonzero when it collects no tests.
run pytest --cov

bash docket/scripts/check-queues.sh --strict
bash docket/scripts/check-links.sh
