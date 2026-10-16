# Decisions

## 2026-10-14: Type decoded JSON as JsonValue for basedpyright strict mode

basedpyright runs in strict mode over `remaldi/` through the `strict`
setting in `pyproject.toml`, so tests, scripts and `bin` keep standard mode
and one invocation covers both. It supersedes the 2026-10-13 choice below to
run standard mode everywhere. Strict mode's errors came from `isinstance`
checks on values typed `object` or `Any`, which narrow to
`dict[Unknown, Unknown]` and `list[Unknown]`. `remaldi/protocol.py` now
defines a recursive `JsonValue` alias for what `json.loads` returns. A
decoded value is annotated with it where it is first inspected (socket
requests in `service.py`, the `/json/list` document, evaluation results,
tabs' extension data and `raw --params`), so the existing `isinstance`
checks narrow to `dict[str, JsonValue]` and `list[JsonValue]`, and the code
reads the narrowed value rather than indexing the container a second time.

`JsonObject` keeps `dict[str, Any]` values. It types the objects Remaldi
builds and passes between its own layers (operation parameters, snapshots,
results), and `JsonValue` values there would need a check on every read,
in the tests as well. The cost is that strict mode reports unknown types,
not `Any`, so a value read from a `JsonObject` is still unchecked by either
type checker. `transport.py` and `client.py` keep their `Any`-typed
messages: typing them as `JsonValue` would mean choosing a behaviour for
frames that are not objects, which DevTools and the service never send, and
that is a behaviour change rather than a typing one. The `/json/list`
entries are cast to `JsonObject` without a per-entry check, because
`refresh` already reports a malformed entry as an unavailable endpoint.

## 2026-10-14: List windows through a service operation

`window list` is a `window.list` operation in the service registry rather
than a projection the CLI makes of `state` output. The window the default
selection would use is decided in the adapter (`_default_window`, shared with
`_select_window`), and a client-side projection would have had to copy that
rule into the client, where it would drift when the rule changes (a default
to the last focused window has been proposed). As an operation, any socket
client gets the same answer, and the reply carries a few fields per window
instead of every tab's title and URL. The cost is one more protocol operation
to keep documented; it reads the same cached snapshot as `state`, so it adds
no browser work.

## 2026-10-13: Lock the toolchain with uv and widen the gates

uv replaces pip, setuptools and the hand-picked interpreter: `uv.lock` pins
every runtime and development dependency, `.python-version` pins 3.12, and
`uv_build` builds the package (`module-root = ""` keeps the flat layout). The
tools are a locked dependency group and every hook runs them with
`uv run --locked`, which removes the second set of pins the hook configuration
used to carry and makes a stale lockfile a gate failure. It supersedes the
2026-10-04 choice below to keep the existing tooling and the user's shared
virtualenv. The cost is that contributors need uv installed, and the Git hooks
start pre-commit from whichever checkout last ran `scripts/setup.sh`.

The gate grows with mature tools where the project had none: basedpyright
beside strict mypy, pytest with a coverage floor in place of the unittest
runner (the tests stay `unittest` classes), Ruff with every rule selected,
shellcheck and shfmt for the scripts, actionlint and zizmor for the workflows,
typos, and pip-audit on the daily validation. Ruff's ignore list records why
each excluded rule does not fit; new rules arrive only with a deliberate Ruff
upgrade, since the version is pinned. Running two type checkers costs a second
pass, but they catch different mistakes and basedpyright matches what most
editors report. basedpyright runs in standard mode because strict mode reports
every decoded JSON value as partly unknown; ty (behind `uv check`) is left out
while it is pre-1.0, and `uv audit` while it is experimental. Vulnerability
auditing needs the network and its result changes without a commit, so it
runs daily rather than in the shared gate.

## 2026-10-13: Use the regular profile's UI target and leave out Private windows

A Private window adds an incognito `main.html` target whose `chrome.windows`
sees only incognito windows. Remaldi used to connect to whichever `main.html`
came first in `/json/list`, so with a Private window open it could list and
dispatch to the Private window alone. When there is more than one `main.html`,
the service now evaluates `chrome.extension.inIncognitoContext` in each on a
short-lived connection, with no event hooks, and connects to the first that
returns `false`. Results are cached per target ID and WebSocket URL. A failed
or non-boolean probe is retried after 30 seconds rather than on every refresh,
because probes run under the browser lock and a hung target would otherwise
stall requests each second; while the selected target is still listed and
regular, it is kept without probing the others. Switching to a different UI
target invalidates cached state and replaces any hookless connection to it
(left by `raw --target`) with one that installs the event hooks. A single
`main.html` is used without probing, as before.

Private windows are therefore invisible to `state`, `workspace switch` and
`command run`. Covering them would mean a connection per context, merged state
and dispatch routed to the owning context; on 2026-10-14 the user decided
Remaldi does not need to control Private windows, so that work is not queued.
With several regular profiles the first non-incognito target still wins, which
is no worse than before.

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
