<img src="assets/remaldi.svg" alt="Remaldi browser command logo" width="80" height="80">

# Remaldi

One local Vivaldi control client and background service. The first browser command
starts a detached service; later commands reuse its connections and cached state.
The service never launches or restarts Vivaldi. The original Bash proof of concept
is preserved in [reference/vivaldiws](reference/vivaldiws) for historical context;
it is not part of the supported client.

## Run

Requires Python 3.12 or newer on macOS or Linux. Install into a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
remaldi status
remaldi state
remaldi workspace switch WORKSPACE_ID
remaldi command list
remaldi command run COMMAND_MAIN_TOGGLE_TAB_BAR
remaldi raw Browser.getVersion
remaldi evaluate 'chrome.windows.getCurrent()' --await-promise --return-by-value
remaldi stop
```

`python -m remaldi` and the checkout launcher `./bin/remaldi` accept the same
commands when their interpreter has the dependencies installed. `serve` runs in the foreground
for debugging. `status` and `stop` never start a missing service. Output is JSON;
errors go to stderr and return a nonzero exit status.

`workspace switch` takes a Vivaldi internal workspace ID, a nonnegative decimal
number, not a list position. The IDs are the `id` fields of Vivaldi's
`vivaldi.workspaces.list` preference. `state` lists them with their names in
`workspaces`; this prints the IDs alone, without names, and also works when
`state` reports `workspaces: null` because some entries fail its checks (for
example duplicate IDs or a name that is not text):

```bash
remaldi evaluate "new Promise(r => vivaldi.prefs.get('vivaldi.workspaces.list', p => r(p.value.map(w => w.id))))" --await-promise --return-by-value
```

`--window-id` selects an explicit window; otherwise switching uses the uniquely
focused window. Window IDs are the `id` fields of the `windows` that `state`
returns:

```bash
remaldi state | jq '.windows[] | {id, focused, state}'
```

With a Private window open, Private windows are normally left out and cannot be
selected (see [State and extension points](#state-and-extension-points)).

In the same browser evaluation as the switch, Remaldi first checks that the ID is
in `vivaldi.workspaces.list` and that the window exists and is not minimized
(Vivaldi would create a tab tagged with an unknown ID, and a minimized window
ignores the action). Otherwise it fails with `unknown_workspace`,
`workspaces_unavailable`, `minimized_window` or `invalid_parameters` and dispatches
nothing. It then dispatches Vivaldi's `JS_LOCAL_ACTIVATE_WORKSPACE` action, as the
native Window menu does. If the workspace is already active in another window,
Vivaldi focuses that window instead of switching the selected one; Remaldi reports
this as a normal dispatch (read from Vivaldi 8.2's code, not observed live). A
successful result, `{"dispatched": true}`, means the action was dispatched, not
that a visible workspace change was verified.

`command run NAME` dispatches one of Vivaldi's own commands or local actions by
name, as a keyboard shortcut or the native menu would: for example
`COMMAND_TAB_STACK_CREATE`, `COMMAND_PAGE_TOGGLE_MUTE` or
`COMMAND_READERVIEW_TOGGLE`. Only names in Remaldi's committed list are
accepted. That list was taken from Vivaldi 8.2.4133.84's command registry and
local-action handler (`remaldi/commands.py`); other versions may differ.
`command list` prints it as `{"vivaldi_version", "commands"}`, each command
with its `name`, `kind` (`command` or `local_action`), the `parameter` a local
action expects and an `allowed` flag. It shows no key or gesture bindings
and needs no browser connection.

Some names are always refused with `command_denied`: `COMMAND_EXIT`,
`COMMAND_QUIT_MAC_MAYBE_WARN`, `COMMAND_CLOSE_WINDOW`,
`COMMAND_MAIL_DELETE_PERMANENTLY`, `COMMAND_EXPORT_PASSWORDS`,
`COMMAND_MANAGE_PEOPLE`, `COMMAND_NEW_GUEST_WINDOW` (it switches to a guest
session), `JS_LOCAL_CLEAR_CLOSED_TABS`, `JS_LOCAL_CLEAR_CLOSED_WEBPANELS`, and
`JS_LOCAL_ACTIVATE_WORKSPACE`, which
creates a tab for an unknown ID (use `workspace switch`). Any other name fails
with `unknown_command`. User-defined command chains are never dispatched,
because their steps could run any command, including the denied ones.

Local actions such as `JS_LOCAL_ACTIVATE_TAB`, `COMMAND_OPEN_LINK` and
`PERIODIC_RELOAD` need `--parameter TEXT`; IDs must be nonnegative decimal
numbers and the `PERIODIC_RELOAD` interval a positive one. Registry commands
take no parameter, and passing one fails with `invalid_parameters`. `--window-id` and the focused-window
default work as for `workspace switch`. In the same browser evaluation as the
dispatch, Remaldi refuses a name that a user-defined chain also uses
(`chain_not_allowed`, or `command_chains_unavailable` if the chain list
cannot be read) and a missing or minimized window (`invalid_parameters`,
`minimized_window`). A successful result, `{"dispatched": true}`, means only
that the dispatch was sent. Vivaldi reports nothing back, so a command that
does nothing in the current context still succeeds. No command has yet been
dispatched through Remaldi against a live browser.

Vivaldi must already be running with `--remote-debugging-port=9222`. On macOS,
launch it with `open -a Vivaldi --args --remote-debugging-port=9222` after quitting
any existing instance. Ordinary launches or updates may omit the flag; Remaldi
cannot fix this by reconnecting. The daemon remains alive while unavailable.

## State and extension points

`state` returns windows, their tabs, workspaces, and capabilities. A Private
window gets an incognito UI target of its own. When several UI targets exist,
Remaldi asks each whether it is incognito and uses the first that is not, so
`state` and dispatches cover the regular profile's windows and leave Private
windows out; if none is confirmed regular, status reports
`ui_target_unavailable`. A single UI target is used without asking. This check
has not yet been observed against a live Vivaldi (see the
[control-surface guide](docs/VIVALDI_CONTROL_SURFACE.md#step-1-find-the-debugger-targets)).

Workspaces are read from Vivaldi's `vivaldi.workspaces.list` preference and listed
as `{id, name, emoji}` (`emoji` is null when unset or empty). Each tab has a
`workspace_id` taken from its `vivExtData`, or null for tabs in no workspace,
web-panel tabs and unreadable tab data. When the preference is unavailable or has
an unexpected shape, the snapshot reports `workspaces: null` and a false
`workspaces` capability instead of failing. A read-only check against Vivaldi
8.2.4133.84 on 2026-10-12 confirmed the workspace listing and tab membership.

Snapshots expire after five seconds; `state --refresh` forces recollection. Tab
and window events, changes to the workspace preference, and tab data changes
invalidate snapshots where Vivaldi delivers them; the preference and tab data
events have not been observed firing, so the expiry still bounds staleness.
Reconnection also invalidates snapshots. Vivaldi UI APIs are internal and version
dependent; other evaluation failures are explicit errors.

`raw METHOD --params '{...}' --target TARGET_ID` sends any DevTools request to an
explicit discovered target. Without `--target`, it uses the Vivaldi UI target.
`evaluate` is a convenience wrapper for `Runtime.evaluate`; inspect its returned
`exceptionDetails` for JavaScript exceptions. Friendly operations live in the
service operation registry and Vivaldi adapter, independently of transport.
Raw operations invalidate cached state conservatively. Requests with an uncertain
outcome are never replayed, including toggles.

Remaldi passes every `raw` method and `evaluate` expression to the browser
unchecked. That includes the UI target's browser lifecycle APIs
(`vivaldi.runtimePrivate.exit` and `restart`, `chrome.runtime.restart`,
`vivaldi.autoUpdate.installUpdateAndRestart`), secret-reading APIs
(`vivaldi.savedpasswords.*`, `chrome.passwordsPrivate.requestPlaintextPassword`
and `exportPasswords`, `vivaldi.utilities.osDecrypt`) and profile-wide resets
and deletions (`vivaldi.prefs.resetAllToDefault`,
`vivaldi.runtimePrivate.deleteProfile`, `chrome.browsingData.*`); the
[control surface guide](docs/VIVALDI_CONTROL_SURFACE.md#what-not-to-wrap) lists
the rest. Calling a restart or exit API breaks the
[never-restart contract](SPEC.md#boundaries). There is no guard: a check over
evaluated JavaScript cannot be complete, and the debugging port is reachable
without Remaldi, so a guard would only prevent accidents while implying more
protection than it gives.

For Vivaldi commands, `command run` is the checked dispatch path.

## Service and socket protocol

The default runtime directory is `~/Library/Caches/remaldi`, owned by the current
user with mode 0700. The socket is `control.sock` with mode 0600. Startup uses a
short-lived startup lock and the daemon holds a separate lifetime lock. Stale
sockets are replaced only by a daemon that has acquired the lifetime lock.

`REMALDI_RUNTIME_DIR` overrides the runtime directory; use a short private path.
`REMALDI_ENDPOINT` overrides the loopback HTTP debugger URL (default
`http://127.0.0.1:9222`). Discovery and WebSockets bypass proxy settings. Browser
connections reconnect with capped backoff. Only local, current-user clients are
supported; this is not a network API.

Clients may send multiple newline-delimited JSON requests over one socket:

```json
{"version":1,"id":"example","operation":"raw","params":{"method":"Browser.getVersion","params":{}}}
```

Responses contain the same `id`, `version: 1`, `ok`, and either `result` or an
`error` object with `code` and `message`. Operations are `status`, `stop`, `raw`,
`state`, `workspace.switch`, `command.list` and `command.run` (params `name`,
optional `parameter` and `window_id`). Request and response lines are limited to 8 MiB
plus 64 KiB of envelope allowance. Oversized results fail explicitly. Incompatible
protocol versions fail explicitly. Service status includes the PID, discovered
target IDs, browser state, and diagnostics. An unavailable endpoint does not prove
whether the browser is closed or running without debugging enabled. HTTP rejection
and a missing UI target are reported separately.

Logs are in `service.log` (1 MiB, two rotated copies); `startup.log` is replaced
on startup. Neither includes request expressions or browser state. Restart the
service with `stop` followed by a browser command after changing its configuration
or updating Remaldi. Client startup has an eight-second deadline; DevTools
requests have a five-second deadline. Each complete operation has a twelve-second
deadline (including queueing); optional event setup has a two-second budget.
Cancelled queued commands cannot dispatch later. A lost response reports `unknown_outcome`;
inspect browser state before deciding whether to issue another mutation.

## Development

See [quality checks](docs/QUALITY.md) for setup, managed Git hooks, executable
gates, and live acceptance boundaries. Start agent work with [AGENTS.md](AGENTS.md).

| Question | Authoritative record |
| --- | --- |
| What is promised or still unverified? | [SPEC.md](SPEC.md) |
| What contracts must changes preserve? | [ARCHITECTURE.md](ARCHITECTURE.md) |
| What can a debugger connection drive in Vivaldi, and how was that found? | [Vivaldi control surface](docs/VIVALDI_CONTROL_SURFACE.md) |
| What could be worked on next? | [TODO.md](TODO.md), with [selection rules](docket/TODO_GUIDE.md) |
| What is currently claimed? | Open GitHub PRs and their ownership/claim markers; check branches/worktrees too. |
| What has a codebase review found? | [Review history](review/README.md) and [promoted backlog](review/BACKLOG.md) |

## Contributor workflow

Start with [AGENTS.md](AGENTS.md) for ownership and process, then
[the quality guide](docs/QUALITY.md) for environment setup and checks.
Ordinary follow-ups are in [TODO.md](TODO.md); promoted codebase-review work is
in [review/BACKLOG.md](review/BACKLOG.md). Open PRs are shared active claims.

[![Main validation](https://github.com/vhata/remaldi/actions/workflows/main-validation.yml/badge.svg)](https://github.com/vhata/remaldi/actions/workflows/main-validation.yml)
