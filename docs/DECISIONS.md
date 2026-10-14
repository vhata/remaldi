# Decisions

## 2026-10-13: Use the regular profile's UI target and leave out Private windows

A Private window adds an incognito `main.html` target whose `chrome.windows`
sees only incognito windows. Remaldi used to connect to whichever `main.html`
came first in `/json/list`, so with a Private window open it could list and
dispatch to the Private window alone. When there is more than one `main.html`,
the service now evaluates `chrome.extension.inIncognitoContext` in each on a
short-lived connection, with no event hooks, and connects to the first that
returns `false`. Results are cached per target ID and WebSocket URL; a failed
or non-boolean probe is not cached and is retried on the next refresh. A
single `main.html` is used without probing, as before.

Private windows are therefore invisible to `state`, `workspace switch` and
`command run`. Covering them means a connection per context, merged state and
dispatch routed to the owning context, which is recorded as
`per-profile-ui-contexts` in `TODO.md`. With several regular profiles the first
non-incognito target still wins, which is no worse than before.

## 2026-10-13: Curate the command allowlist from Vivaldi's bundle

`command run` dispatches only names in `remaldi/commands.py`: the command
registry read from the installed 8.2.4133.84 `bundle.js` with the
`registered.txt` procedure in the control-surface guide, plus the local actions
in its table. `vivaldi.actions` is not a source, because it lists only bound
commands and can name user chains. The list is a Python module, one registry
name per line, so it ships in the wheel without package-data configuration and
diffs directly against a regenerated `registered.txt`. The cost is a manual
refresh after each Vivaldi update; a name Vivaldi drops stays listed and
dispatches to nothing.

Two names are denied as well as the ones the queue entry listed.
`JS_LOCAL_ACTIVATE_WORKSPACE`, dispatched directly, creates a tab for an
unknown ID, and `workspace switch` already checks the ID first.
`COMMAND_NEW_GUEST_WINDOW` calls `vivaldi.runtimePrivate.switchToGuestSession`,
which the control-surface guide lists under browser lifecycle. Local actions
must have a parameter: without one Vivaldi's handler declines and the name
falls through to the registry and then to a chain lookup.

Vivaldi runs a registered command before it looks for a chain of the same
name, but an unregistered name or a declined local action reaches the chain
lookup. So the dispatch expression reads `vivaldi.chained_commands.command_list`
and refuses any name a chain uses, for every command rather than only the
cases that can fall through. If the chain list cannot be read, nothing is
dispatched.

## 2026-10-11: Vendor the workflow machinery under docket/

The generic workflow (contract, queue and review guides, validators) is vendored
under `docket/` by the docket skill's `install.sh` and is never edited here. It
replaces the scripts copied into `scripts/workflow/` and the guides rewritten
under `docs/`, which had drifted from the skill and received none of its fixes,
and supersedes the 2026-10-04 choice below to copy the shell tools into the
repository (its reason still holds: the installed copies run without a globally
installed skill).
`AGENTS.md` keeps only this project's settings in its marked Docket section, and
the review focus areas, baseline commands and drift checks live in
`docs/QUALITY.md`. One command installs or resyncs the whole directory and
`--check` reports drift, so a validator fix reaches this project without a hand
merge; the installed copies still run without a globally installed skill. The
cost is that a project-specific rule can no longer be written into a guide; it
goes in the Docket section or the quality doc, which the guides point to.

## 2026-10-04: Extend the existing setup PR

PR #1 already owns repository workflow setup. Continue `workflow-foundation`
in its isolated worktree rather than creating an overlapping claim. Preserve
its existing commit and deferred browser work. Main remains the user's landing
responsibility. The shell workflow tools are copied into the repository so
contributors need no globally installed skill.

## 2026-10-04: Keep existing quality tooling

Keep pre-commit, Ruff, strict mypy, unittest, and secret auditing. Add workflow
record checks to the same entrypoint and manager. Explicitly reject empty test
collection because unittest otherwise succeeds with zero tests. Python 3.12 is
the development/CI contract; local setup uses the user's installed environment,
while CI and hooks provision their own. No live browser scenario runs unattended.

## 2026-10-04: Ready means unblocked

The user chose repo-workflow's unblocked Ready policy over the earlier guide's
blocked-Ready convention. Move both live browser acceptance tasks to Needs triage
with explicit external blockers, preserving their slugs, sources, and acceptance
criteria. This exposes the actual availability boundary without assigning those
tasks or authorizing visible browser changes.
