# Quality checks and evidence

## What quality means here

- The service never launches or restarts Vivaldi and never replays a request
  whose outcome is uncertain, including toggles. A debugging endpoint is an
  external prerequisite, not something Remaldi can restore.
- Requests match responses by ID even when events interleave; the complete
  operation deadline includes queueing; cancelled queued mutations never execute
  later.
- Errors stay structured and distinct: protocol, target, capability, browser
  exception and unknown outcome. Unsupported capabilities and uncertain outcomes
  are reported, never guessed at.
- Service readiness is distinct from browser connectivity. An unavailable
  endpoint does not prove the browser is closed, and status separates endpoint
  rejection from a missing UI target.
- The runtime directory and socket are private to the current user, and evidence
  never contains tab titles, URLs, workspace names, profile captures or
  credentials.
- Deliberately manual: visible browser behaviour (a workspace actually switching,
  reconnection after a user-controlled restart) is checked only in the live
  scenarios below, with the user's authorisation.

The invariants behind these are stated in full in
[ARCHITECTURE.md](../ARCHITECTURE.md#failure-and-acceptance-invariants).

## Setup and entrypoints

[uv](https://docs.astral.sh/uv/) manages the environment. `.python-version`
pins Python 3.12 for development and CI; uv uses an installed 3.12 or downloads
one. `uv.lock` pins every dependency, and the tools all come from its `dev`
dependency group, so hooks, CI and local runs use the same versions.

```bash
bash scripts/setup.sh                # uv sync --locked, then install the Git hooks
scripts/format.sh                    # apply Ruff and shfmt fixes
scripts/check.sh                     # the shared gate
scripts/audit-dependencies.sh        # known vulnerabilities (needs network)
uv build                             # wheel and source distribution
uv run remaldi status                # run the client from the checkout
```

Run tools as `uv run --locked <tool>`; `--locked` fails when `uv.lock` no longer
matches `pyproject.toml` instead of silently re-resolving. Change dependencies
with `uv add`, `uv add --dev` or `uv lock --upgrade-package <name>` and commit the
lockfile with the change. Tool configuration lives in `pyproject.toml`, apart
from `typos.toml`, `.editorconfig` (which shfmt reads) and
`.pre-commit-config.yaml`.

`check.sh` runs, in order:

- Ruff formatting and lint. Lint selects every rule; the ignore list in
  `pyproject.toml` gives the reason for each exclusion.
- Strict mypy and basedpyright (standard mode) over `remaldi`, `tests` and
  `scripts`; basedpyright also reads `bin`.
- shfmt and shellcheck over `scripts/*.sh`, actionlint and zizmor (offline)
  over the workflows, and typos over the tree.
- Whitespace errors, conflict markers, TOML and YAML syntax, and shebangs that
  agree with the executable bit.
- The secret audit of publishable files and reachable Git history.
- pytest with branch coverage of `remaldi` and an 85% floor. pytest fails when
  it collects no tests, runs in strict mode, turns warnings into errors and
  times a test out after 60 seconds. The tests are `unittest` classes, which
  pytest runs unchanged.
- Strict queue validation and Markdown links (the vendored
  `docket/scripts/check-queues.sh --strict` and `docket/scripts/check-links.sh`).

`docket/` is vendored and `reference/` is historical, so neither is linted.

`scripts/setup.sh` installs pre-commit and pre-push hooks. Every hook runs its
tool through `uv run --locked`, so there are no hook pins to keep in step with
`pyproject.toml`. Commit hooks fix lint and formatting in changed Python and
shell files, strip trailing whitespace and add final newlines, check spelling,
syntax, large files and the lockfile, lint workflows when they change, audit
secrets, and validate queues and links. The push hook runs the complete gate.
Hooks are installed in the Git directory that every worktree shares and start
pre-commit from the checkout where `setup.sh` last ran, so run it from a
checkout that will outlive the worktrees, such as the main one. Hook checks
remain mandatory for pushes even when a scoped documentation change only needs
link and content review beforehand.

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

## CI and hosting

`Checks` runs the shared gate and package build on Linux and macOS for PRs and
pushes to main, then `bash docket/scripts/ci.sh`: queue validation, Markdown
links and, on pull requests, the PR body's markers against the base and head
queue snapshots (`PR`, `BASE`, `HEAD_BRANCH` and `GH_TOKEN` come from the event);
body edits also rerun CI. A `compat` job runs the tests alone on Python 3.13
and 3.14, because `requires-python` admits them; it is not a required check.
Workflows install a pinned uv with `astral-sh/setup-uv`, pin every action to a
commit SHA (zizmor enforces this) and check out without persisted credentials,
with complete Git history for the secret scan.
PR supersessions cancel previous runs; main pushes do not. Jobs time out after
15 minutes. `Main validation` runs daily, manually, and on PRs changing its
workflow, repeating checks/build, auditing the locked dependencies with
`scripts/audit-dependencies.sh` (pip-audit), and reporting review drift with
`bash docket/scripts/review-due.sh --paths "remaldi tests"`, with seven-day
package/report artifacts. It never operates a live browser.

On a red main run, revert with authorization or file a P1 TODO the same day
(P0 if releases are blocked), with run link and evidence. Keep it open until
main passes; a passing fix branch does not establish recovery. A missing scheduled
run is not a pass. GitHub schedules are best-effort and can become inactive.

The repository became public on 2026-10-07 and branch protection was applied the
same day: a pull request is required with zero approving reviews (independent
agent review is recorded in `## Review`); required checks `check (ubuntu-latest)`
and `check (macos-latest)`; branches need not be up to date with `main` before
merging; linear history required; conversation resolution not required; force
pushes and deletions on `main` allowed for the owner (agents never use them); not
enforced for administrators, which permits the direct-to-main exceptions in
[docket/CONTRACT.md](../docket/CONTRACT.md). Squash only, PR title and body as the squash message,
merged head branches deleted. Scheduled validation is not a required PR check.

After an authorized squash merge, run
`bash docket/scripts/cleanup-landed.sh` first in dry-run mode, inspect dirty or
ignored evidence, then `--apply` only for clean landed work. Preserve unmerged
commits and dirty trees; do not delete them without authorization. Rebase stacked
children onto main, retarget their PRs, rerun their checks/review as needed, and
inspect main's latest CI. A completed child can be ready for review but cannot
land until its parent lands and its checks pass on the current main base.

## Review inputs

What the vendored review guide ([docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md))
reads from this project.

- Focus areas: the list under [What quality means here](#what-quality-means-here),
  the invariants in [ARCHITECTURE.md](../ARCHITECTURE.md), and the evidence
  boundaries above: fake-server tests prove transport and lifecycle invariants,
  not Vivaldi compatibility or visible behaviour.
- Baseline commands beyond `bash scripts/check.sh`: `uv build`, followed
  by an inspection of the built artifact's metadata (license file and `remaldi`
  entry point present); `bash docket/scripts/review-due.sh --paths "remaldi tests"`
  for the drift figures.
- Drift checks for an incremental review: README commands, socket protocol and
  framing limits against `remaldi/__main__.py` and `remaldi/protocol.py`; SPEC's
  capability table and remaining acceptance against `TODO.md` and merged work;
  the area list in `AGENTS.md` against the package layout; this document against
  `.pre-commit-config.yaml`, `scripts/` and `.github/workflows/`;
  `bash ~/.claude/skills/docket/install.sh --check` for drift in `docket/` and
  the Docket section of `AGENTS.md`.

## PR evidence

Every PR lists the commands run and their results, a reproducible scenario for
behaviour changes, what was not run and why, and the independent review. See
[docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).
