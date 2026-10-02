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
remaldi workspace switch 2
remaldi raw Browser.getVersion
remaldi evaluate 'chrome.windows.getCurrent()' --await-promise --return-by-value
remaldi stop
```

`python -m remaldi` and the checkout launcher `./bin/remaldi` accept the same
commands when their interpreter has the dependencies installed. `serve` runs in the foreground
for debugging. `status` and `stop` never start a missing service. Output is JSON;
errors go to stderr and return a nonzero exit status. Workspace numbers are Vivaldi
internal IDs, not list positions. `--window-id` selects an explicit window; otherwise
switching uses the uniquely focused window. A successful switch result means the
command was dispatched, not that the visible workspace change was verified.

Vivaldi must already be running with `--remote-debugging-port=9222`. On macOS,
launch it with `open -a Vivaldi --args --remote-debugging-port=9222` after quitting
any existing instance. Ordinary launches or updates may omit the flag; Remaldi
cannot fix this by reconnecting. The daemon remains alive while unavailable.

## State and extension points

`state` returns windows, their tabs, workspaces where supported, and capabilities.
Snapshots expire after five seconds; `state --refresh` forces recollection.
Supported tab, window, and workspace events invalidate snapshots. Reconnection
also invalidates them. Vivaldi UI APIs are internal and version dependent;
unsupported workspace listing is reported with `workspaces: null` and a false
capability. Other evaluation failures are explicit errors.

`raw METHOD --params '{...}' --target TARGET_ID` sends any DevTools request to an
explicit discovered target. Without `--target`, it uses the Vivaldi UI target.
`evaluate` is a convenience wrapper for `Runtime.evaluate`; inspect its returned
`exceptionDetails` for JavaScript exceptions. Friendly operations live in the
service operation registry and Vivaldi adapter, independently of transport.
Raw operations invalidate cached state conservatively. Requests with an uncertain
outcome are never replayed, including toggles.

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
`state`, and `workspace.switch`. Request and response lines are limited to 8 MiB
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

