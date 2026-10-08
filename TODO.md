# Ordinary deferred work

Use [the TODO guide](docs/TODO_GUIDE.md) before selecting or moving an entry.
These are known follow-ups, not assignments. Check open PR claims and dependencies
before calling ready work available. Priorities below are intentionally unassigned.

## Needs triage

### Unprioritized

- [BROWSER] `retain-debugging-across-launches` — **Determine supported ways to keep debugging enabled through ordinary launches and updates.** Wrapper launches do
  not establish a flag for every future launch; keep the no-browser-launch contract.
  - Source: browser restart discussion, 2026-10-02; SPEC boundaries.
  - Starting point: Vivaldi launch configuration and supported restart behavior.
  - Triage outcome: evidence-backed feasible options or documented limitation;
    do not attribute an observed restart to an unverified external cause.

- [ACCEPTANCE] `verify-live-workspace-switch` — **Validate visible switching and service reuse in a running Vivaldi browser.** Current success confirms dispatch.
  - Source: accepted plan and remaining live acceptance, 2026-10-02.
  - Starting point: workspace CLI and live scenario in docs/QUALITY.md.
  - Depends on: `fix-workspace-switch-by-id`
  - Blocked by: an already-running debug-enabled Vivaldi, known workspace IDs,
    and explicit authorization for the selected visible change.
  - Acceptance: observe the selected workspace, confirm the same service PID on
    subsequent calls, and report version/capabilities and limits without private data.

- [ACCEPTANCE] `verify-live-browser-reconnect` — **Validate reconnection and fresh state after a browser restart.** Automated fake-target tests do not establish this.
  - Source: accepted plan and remaining live acceptance, 2026-10-02.
  - Starting point: browser monitor, cache generation, and docs/QUALITY.md scenario.
  - Blocked by: a user-controlled restart of a debug-enabled browser and a safe
    window for observing it; the agent/service must not restart it automatically.
  - Acceptance: observe disconnect/reconnect, retain the service PID, and verify
    fresh state after the new browser target appears.

- [SERVICE] `event-watch-stream` — **Stream browser events to clients as they happen.** Remaldi only uses
  events to invalidate snapshots. A `watch` command could emit tab, window,
  workspace, preference, keyboard-shortcut and gesture events for scripts to react to.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Events").
  - Starting point: `EVENT_HOOKS` and `__remaldiChanged` in `browser.py`; protocol version 1 in `protocol.py`.
  - Dependencies: none.
  - Triage outcome: decide whether a long-lived streaming response fits protocol
    version 1 or needs a new version; which event sources are worth exposing;
    and back-pressure, filtering and privacy (events carry URLs and titles).

- [BROWSER] `browser-ui-style-injection` — **Apply user styles to Vivaldi's own interface through the debugger.** Evaluating in the `window.html`
  target can add CSS to the browser UI without modifying application files.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Browser UI changes").
  - Starting point: target discovery in `browser.py`; the `window.html` target.
  - Dependencies: none.
  - Triage outcome: whether this is wanted; where styles are stored; how to
    reapply after UI reloads, reconnection and new windows; how to remove them;
    and how several windows map onto `window.html` targets (one window was observed).

- [SERVICE] `guard-hazardous-raw-calls` — **Decide whether raw access should refuse browser lifecycle and secret-reading APIs.** `raw` and `evaluate`
  can call `vivaldi.runtimePrivate.restart`, plaintext password APIs and profile
  resets. Restarting would break the never-restart contract.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("What not to wrap").
  - Starting point: the `raw` operation in `service.py`; README's raw access section.
  - Dependencies: none.
  - Triage outcome: guard, warn or document only. A guard over evaluated JavaScript
    cannot be complete, and the debugging port is reachable without Remaldi, so
    any guard only prevents accidents.

## Needs proof of concept

### Unprioritized

- [STATE] `tab-stack-operations` — **Stack, unstack and tile explicit tabs.** The stack and tile commands act on
  the active or selected tabs. Scripts need to group tabs by ID.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Private APIs").
  - Starting point: `vivaldi.tabsPrivate.update`/`unstack`/`setGroupProperties`,
    tab `vivExtData`, and the `COMMAND_TAB_STACK_*` registry entries in `bundle.js`.
  - Dependencies: none.
  - Experiment: from bundle call sites, establish how stacks and tiles are encoded in
    `vivExtData` and which calls create, rename, dissolve and tile them for given
    tab IDs. Then confirm with one authorized, reversible live change on disposable tabs.
  - Acceptance: a documented call contract for each operation, with argument shapes,
    observed results and failure behaviour, ready for a Ready implementation entry.

- [STATE] `move-tabs-between-workspaces` — **Move given tabs into a given workspace by ID.** `WORKSPACE_MOVE_TABS_TO_N` is positional and acts
  on the selected tabs.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Workspace switching").
  - Starting point: the `WORKSPACE_MOVE_TABS_TO_` registry entries and their store
    actions in `bundle.js`; `vivaldi.tabsPrivate.update`.
  - Dependencies: none.
  - Experiment: find the store call the move command uses and whether writing
    `vivExtData.workspaceId` alone updates the UI. Confirm with one authorized
    live move of a disposable tab.
  - Acceptance: a documented contract (tab IDs, workspace ID, window effects,
    failure behaviour) ready for a Ready implementation entry.

- [STATE] `saved-session-operations` — **List, save and open named sessions.** Sessions are a natural snapshot and restore
  unit for workspaces of tabs.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Local actions that take a parameter", "Private APIs").
  - Starting point: `vivaldi.sessionsPrivate.getAll`/`add`/`open`;
    `JS_LOCAL_OPEN_SESSION` in `bundle.js`.
  - Dependencies: none.
  - Experiment: establish the read-only `getAll` result shape (counts and field
    names only) and the `add`/`open` arguments from bundle call sites. Confirm
    saving with one authorized live save that the user then deletes.
  - Acceptance: a documented contract for list, save and open, including whether
    open replaces or adds windows.

- [CLIENT] `capture-tab-or-ui` — **Save a screenshot of a tab or of the browser UI to a file.** Captures help with visual verification,
  including the live acceptance checks.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("DevTools protocol on web tabs", "Private APIs").
  - Starting point: `Page.captureScreenshot` on page targets; `vivaldi.thumbnails.captureTab`/`captureUI`.
  - Dependencies: none.
  - Experiment: compare the two sources for background tabs, hidden workspaces and
    the UI itself, and their output sizes against the 8 MiB response limit.
  - Acceptance: a chosen source, an output contract (client-side file path, format,
    size limits) and a privacy note. Captures are private and never committed.

## Ready for separate work

### Unprioritized

- [STATE] `implement-workspace-enumeration` — **Report workspaces from Vivaldi's workspace preference.** Vivaldi 8.2 has
  no `vivaldi.workspaces` API, so snapshots always report workspaces unsupported.
  - Source: `discover-workspace-enumeration` read-only live probe, 2026-10-08,
    Vivaldi 8.2.4133.84.
  - Starting point: `SNAPSHOT` in `adapter.py` and `EVENT_HOOKS` in `browser.py`.
  - Dependencies: none.
  - Contract: `vivaldi.prefs.get('vivaldi.workspaces.list', callback)` yields
    `{value, defaultValue, store}`. `value` lists `{id, name, icon, emoji?}` with
    unique nonnegative safe-integer IDs in the decimal form `switch_workspace`
    accepts; switching to them is unverified. An unknown path sets
    `chrome.runtime.lastError` rather than throwing.
  - Output: `workspaces` becomes a list of `{id, name, emoji}` (`emoji` null when
    absent; `icon` is inline SVG and is omitted) and the capability is true. Each
    tab gains `workspace_id`, the numeric `workspaceId` from its `vivExtData` JSON,
    or null. Tabs in no workspace and web-panel tabs (`panelId`) both have null.
    A missing `prefs.get`, `lastError`, or malformed value keeps `workspaces: null`
    with capability false instead of failing the snapshot.
  - Events: replace the absent `vivaldi.workspaces` hooks in `EVENT_HOOKS` with
    `vivaldi.prefs.onChanged`, limited to this path once its argument shape is
    checked, and `vivaldi.tabsPrivate.onExtDataChanged`. Neither was observed
    firing; keep the TTL fallback.
  - Acceptance: tests cover the supported shape, tab membership, malformed values,
    `lastError`, and fallback; a read-only live check reports the capability and
    IDs without committing names. A window's active workspace is out of scope.

- [STATE] `fix-workspace-switch-by-id` — **Switch workspaces by internal ID through Vivaldi's local workspace action.** `switch_workspace`
  dispatches `COMMAND_WORKSPACE_SWITCH_<id>`, but those commands are positional
  (`_1` means no workspace, `_2` to `_10` the first nine). An internal ID matches no
  command, and a small number selects by position.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Workspace switching").
  - Starting point: `switch_workspace` in `adapter.py`; `tests/test_adapter.py`.
  - Dependencies: none. `dispatch-named-commands` also edits the adapter's
    dispatch and window selection; land one first and rebase the other.
  - Contract: dispatch `vivaldi.menubar.onActivated.dispatch(windowId,
    'JS_LOCAL_ACTIVATE_WORKSPACE', String(workspaceId))`, the path the native
    Window menu uses. Keep the decimal ID validation and window selection. In
    the same evaluated expression as the dispatch, first confirm that the ID is in
    `vivaldi.workspaces.list` (an unknown ID makes Vivaldi create a tab tagged with
    it) and that `chrome.windows.get(windowId)` is not minimized (minimized windows
    ignore dispatches). Fail with a structured error otherwise, without dispatching.
    A workspace already active in another window focuses that window instead of
    switching the requested one. Document this rather than treat it as an error.
  - Acceptance: tests assert the dispatched action and parameter, the unknown-ID
    and minimized-window rejections, and that rejection happens before dispatch.
    The README describes ID semantics, the focus-other-window case, and that
    success confirms dispatch only. Visible switching stays with
    `verify-live-workspace-switch`.

- [SERVICE] `dispatch-named-commands` — **Run Vivaldi commands and parameterised local actions by name.** Most keyboard-reachable actions
  (stack and tile tabs, toggle UI parts, mute, reader view, panels) need no new
  browser code, only a checked dispatch.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("How command dispatch works", "What can be driven", "What not to wrap").
  - Starting point: the service operation registry in `service.py`;
    `switch_workspace` in `adapter.py`; CLI parsing in `__main__.py`.
  - Dependencies: none. Coordinate with `fix-workspace-switch-by-id` on shared adapter code.
  - Contract: `command run NAME [--parameter TEXT] [--window-id ID]` and `command list`.
    The allowlist is a curated list committed in Remaldi, taken from the guide's
    `registered.txt` procedure plus the local-action table, and labelled with the
    Vivaldi version it came from. `vivaldi.actions` is not a source because it
    only holds bound commands and may contain user chain names. Chains are not
    allowed, because dispatching a chain's name runs steps the denylist cannot
    check. Always deny `COMMAND_EXIT`, `COMMAND_QUIT_MAC_MAYBE_WARN`,
    `COMMAND_CLOSE_WINDOW`, `COMMAND_MAIL_DELETE_PERMANENTLY`,
    `COMMAND_EXPORT_PASSWORDS`, `COMMAND_MANAGE_PEOPLE`,
    `JS_LOCAL_CLEAR_CLOSED_TABS` and `JS_LOCAL_CLEAR_CLOSED_WEBPANELS`.
    `--parameter` applies only to local actions. Window selection matches
    workspace switching. Check for a minimized window in the same expression as
    the dispatch. The result confirms dispatch only. Mutations serialize,
    invalidate state and are never replayed. `command list` returns names with an
    allowed flag and no bindings.
  - Acceptance: tests cover allowed, denied, unknown, chain and parameterised
    names, window selection, minimized rejection, no-replay and invalidation. The README
    documents the commands and their dispatch-only result. One authorized live
    toggle (for example `COMMAND_MAIN_TOGGLE_TAB_BAR` dispatched twice) is
    observed or reported as a limitation.
