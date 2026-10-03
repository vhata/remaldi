# Quality checks and evidence

## Setup and entrypoints

Use Python 3.12 for development and CI. In the activated environment:

```bash
python -m pip install -e '.[dev]'
python -m pre_commit install --hook-type pre-commit --hook-type pre-push
scripts/format.sh
scripts/check.sh
python -m build
```

`format.sh` fixes Ruff lint and formatting. `check.sh` checks formatting, Ruff,
strict mypy for application modules, secrets in publishable files/reachable Git
history, and the unittest suite. Tests are linted/formatted but not strict-typed.
Standalone scripts use `python3` from the active environment; `REMALDI_PYTHON`
selects another interpreter. CI shares the gate on macOS/Linux and builds wheel
and source distributions with complete Git history available for the secret scan.

Git hooks create/reuse a managed Python 3.12 environment with required tools.
Python 3.12 must be installed, but commits/pushes do not require an activated
virtualenv. Initial runs download dependencies. Commit hooks lint/format changed
Python files and audit secrets; push hooks run the complete gate and ignore an
ambient `REMALDI_PYTHON` override. Keep hook dependency pins aligned with pyproject
dev dependencies when upgrading. Hook checks remain mandatory for pushes even
when a scoped documentation change only needs link/content review beforehand.

Use proportionate validation: documentation changes need link/content checks and
secret audit; code changes need relevant tests and mandatory gates. Investigate
failures before expanding scope. Independent review checks actual changes and
fixes; self-review or passing automation does not substitute for it.

## Evidence boundaries

The automated suite uses fake WebSockets and temporary local Unix sockets, never
launching Vivaldi. It covers response correlation/events, lifecycle ownership,
connection replacement, cache freshness, capability fallback, and mutation
deadline/no-replay behavior. Socket permission failures are environment limits,
not passing tests or automatically application defects.

Package builds establish artifact creation, not installation or browser behavior.
For packaging changes inspect the resulting artifact/metadata; a source assertion
does not prove the license or entrypoint was included. CI success does not establish
compatibility with a user's live Vivaldi version.

## Live browser acceptance

Run only a selected, authorized scenario against an already-running debug-enabled
browser. Record browser version, capabilities, command outcomes, and observed
behavior. Never launch/restart it automatically, expose tab titles/URLs/workspace
names in public evidence, or commit captured profile data.

- Read-only baseline: inspect status/state, issue a raw version request, repeat
  calls, and compare service PID. Event subscription status is not proof every
  possible browser event has been exercised.
- Workspace acceptance: obtain known workspace IDs and authorization for the
  visible change; dispatch a switch, directly observe the selected workspace,
  and compare the service PID on subsequent calls. Dispatch success alone fails
  this acceptance criterion. An inability to observe it remains a limitation.
- Reconnect acceptance: while the daemon remains alive, the user restarts Vivaldi
  with debugging enabled. Observe disconnect/reconnect, inspect fresh state and
  the new target, and confirm the service PID is unchanged. A fake-target test
  or an unavailable endpoint cannot substitute for this scenario.

Current unchecked scenarios live in SPEC/TODO. This guide defines how to validate
them; it does not assign or authorize those tasks.
