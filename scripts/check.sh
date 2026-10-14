#!/usr/bin/env bash
# The shared gate. Git hooks, CI and agents all run this script; every tool
# comes from the locked dev dependency group, so a stale uv.lock fails here.
# Portable to bash 3.2, the macOS system shell.
set -euo pipefail
cd "$(dirname "$0")/.."

run() { uv run --locked "$@"; }
# tracked [--executable] PATHSPEC...: set "matched" to the tracked files that
# match, leaving out docket/, which is vendored and checked upstream. The
# filtering is done here because git 2.55 returns nothing for a glob combined
# with an exclude pathspec. An empty match is an error, since most tools would
# silently read standard input instead.
tracked() {
  local executable=0 line path
  if [ "$1" = "--executable" ]; then
    executable=1
    shift
  fi
  matched=()
  while IFS= read -r line; do
    path="${line#* }"
    case "$path" in docket/*) continue ;; esac
    if [ "$executable" -eq 1 ] && [ "${line%% *}" != 100755 ]; then
      continue
    fi
    matched+=("$path")
  done < <(git ls-files --format='%(objectmode) %(path)' -- "$@")
  if [ "${#matched[@]}" -eq 0 ]; then
    echo "check: no tracked files match $*" >&2
    return 1
  fi
}
# files PATHSPEC... -- TOOL ARGS...: run a tool over the tracked files.
files() {
  local specs=()
  while [ "$1" != "--" ]; do
    specs+=("$1")
    shift
  done
  shift
  tracked "${specs[@]}"
  run "$@" "${matched[@]}"
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
tracked .
git diff --check "$(git hash-object -t tree /dev/null)" -- "${matched[@]}"
files . -- check-merge-conflict
files '*.toml' -- check-toml
files '*.yml' '*.yaml' -- check-yaml
tracked --executable .
run check-executables-have-shebangs "${matched[@]}"
files . -- check-shebang-scripts-are-executable

run python scripts/audit-secrets.py

# pytest exits nonzero when it collects no tests.
run pytest --cov

bash docket/scripts/check-queues.sh --strict
bash docket/scripts/check-links.sh
