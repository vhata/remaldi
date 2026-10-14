# Ordinary deferred work

Use [the TODO guide](docket/TODO_GUIDE.md) before selecting or moving an entry.
These are known follow-ups, not assignments. Check open PR claims and dependencies
before calling ready work available. Priorities were set in triage on 2026-10-11.

## Needs triage

### P1 High

- [ACCEPTANCE] `verify-live-workspace-switch` — **Validate visible switching and service reuse in a running Vivaldi browser.** Current success confirms dispatch.
  - Source: accepted plan and remaining live acceptance, 2026-10-02.
  - Starting point: workspace CLI and live scenario in docs/QUALITY.md.
  - Blocked by: an already-running debug-enabled Vivaldi, known workspace IDs,
    and explicit authorization for the selected visible change.
  - Acceptance: observe the selected workspace, confirm the same service PID on
    subsequent calls, and report version/capabilities and limits without private data.

- [ACCEPTANCE] `verify-live-browser-reconnect` — **Validate reconnection and fresh state after a browser restart.** Automated fake-target tests do not establish this.
  - Source: accepted plan and remaining live acceptance, 2026-10-02.
  - Starting point: browser monitor, cache generation, and docs/QUALITY.md scenario.
  - Related: `retain-debugging-across-launches`
  - Blocked by: a user-controlled restart of a debug-enabled browser and a safe
    window for observing it; the agent/service must not restart it automatically.
  - Acceptance: observe disconnect/reconnect, retain the service PID, and verify
    fresh state after the new browser target appears.

### P3 Low

- [BROWSER] `browser-ui-style-injection` — **Apply user styles to Vivaldi's own interface through the debugger.** Evaluating in the `window.html`
  target can add CSS to the browser UI without modifying application files.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Browser UI changes").
  - Starting point: target discovery in `browser.py`; the `window.html` target.
  - Dependencies: none.
  - Triage outcome: whether this is wanted (undecided as of 2026-10-11 triage);
    where styles are stored; how to reapply after UI reloads, reconnection and new
    windows; how to remove them; and how several windows map onto `window.html`
    targets (one window was observed).

### Unprioritized

- [BROWSER] `per-profile-ui-contexts` — **Report and control windows in every UI context, Private windows included.** Remaldi uses only the regular profile's `main.html`, so Private windows (and any other profile) are invisible to `state`, `workspace switch` and `command run`.
  - Source: `regular-profile-ui-target` fix, 2026-10-13.
  - Starting point: `_select_ui` in `browser.py`; the decision entry of
    2026-10-13 in docs/DECISIONS.md.
  - Open questions: whether Private windows should be controllable at all;
    whether `vivaldi.menubar.onActivated.dispatch` from one context reaches a
    window owned by another; how snapshots, event hooks and invalidation work
    with one connection per context; how several regular profiles are told
    apart.

- [CLIENT] `list-window-ids` — **Add a command that lists window IDs for `--window-id`.** `workspace switch` and `command run` both take `--window-id`, and the only way to find one is to filter `state` output with `jq` as the README shows.
  - Source: user request during the `regular-profile-ui-target` fix, 2026-10-13.
  - Starting point: `_select_window` in `adapter.py`; the `windows` field of
    the snapshot; `__main__.py`.
  - Shape to decide: a `remaldi window list` command (or similar) printing
    each window's `id`, `focused`, `state`, `type` and tab count, with no tab
    titles or URLs; whether it marks the window the focused-window default
    would select.
  - Related: `last-focused-window-default`

- [STATE] `last-focused-window-default` — **Default `workspace switch` and `command run` to the most recently focused Vivaldi window.** The default now needs exactly one window with `focused: true`, and Chrome sets that only while Vivaldi has OS focus, so running `remaldi` from a terminal in front of Vivaldi fails with `ambiguous_window` in what the user expects to be the most common case.
  - Source: user request, 2026-10-13, after the `regular-profile-ui-target` fix.
  - Starting point: `_select_window` in `adapter.py`; the
    `chrome.windows.onFocusChanged` hook in `EVENT_HOOKS` (`browser.py`);
    `chrome.windows.getLastFocused`.
  - Open questions: whether `getLastFocused` returns the last Vivaldi window
    while another app has focus, or whether the UI context must record focus
    changes itself (and what happens after a service or UI reload, before any
    focus change is seen); how minimized windows and windows closed since are
    handled; whether `state` should mark the window the default would pick.
  - Unverified: `focused` being false for every window while another app is
    frontmost is Chrome's documented behaviour, not observed in Vivaldi.
  - Related: `list-window-ids`

- [ACCEPTANCE] `verify-live-command-dispatch` — **Validate a named command dispatch in a running Vivaldi browser.** `command run` success confirms dispatch only, and its tests read the evaluated JavaScript as text without running it.
  - Source: `dispatch-named-commands` PR, 2026-10-13; the live toggle in
    that entry's acceptance was reported as a limitation.
  - Starting point: `command run` in README; `RUN_COMMAND` in `adapter.py`;
    the live scenario in docs/QUALITY.md.
  - Blocked by: an already-running debug-enabled Vivaldi and explicit
    authorization for the selected visible change.
  - Acceptance: dispatch `COMMAND_MAIN_TOGGLE_TAB_BAR` twice, observe the tab bar
    hide and return, and report version, capabilities and limits without
    private data.

- [TOOLING] `automated-dependency-updates` — **Open update PRs for `uv.lock` and the SHA-pinned workflow actions automatically.** Every pin is now exact, so nothing moves without someone running `uv lock --upgrade` and editing workflow SHAs by hand.
  - Source: `uv-tooling` PR, 2026-10-13.
  - Starting point: Dependabot's `uv` and `github-actions` ecosystems, or Renovate.
  - Triage outcome: bot PR bodies carry no `## Why` or `Type:` line, so
    `docket/scripts/check-pr-markers.sh` would fail them in `Checks`; decide
    whether bot PRs are exempted in the workflow, rewritten before merge, or
    the tool is left out.

- [TOOLING] `pyright-strict-application` — **Run basedpyright in strict mode over `remaldi/`.** Standard mode misses values of unknown type flowing out of decoded JSON.
  - Source: `uv-tooling` PR, 2026-10-13; strict mode reported 49 errors in
    `remaldi/` and `scripts/` at the time, nearly all `dict[Unknown, Unknown]`
    from `json.loads` and `.get`.
  - Starting point: a JSON value type at the DevTools and socket boundaries in
    `transport.py`, `service.py` and `client.py`; `[tool.basedpyright]` in
    `pyproject.toml`.

## Needs proof of concept

### P2 Normal

- [BROWSER] `retain-debugging-across-launches` — **Determine supported ways to keep debugging enabled through ordinary launches and updates.** Wrapper launches do
  not establish a flag for every future launch; keep the no-browser-launch contract.
  - Source: browser restart discussion, 2026-10-02; SPEC boundaries.
  - Starting point: Vivaldi launch configuration and supported restart behavior.
  - Experiment: survey supported launch configuration on macOS and Linux (desktop
    entries, app bundles, command-line files, policies) and whether each survives
    an update and a browser-initiated restart.
  - Acceptance: evidence-backed feasible options or documented limitation;
    do not attribute an observed restart to an unverified external cause.

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

### P3 Low

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

- [SERVICE] `event-watch-stream` — **Stream browser events to clients as they happen.** Remaldi only uses
  events to invalidate snapshots. A `watch` command could emit tab, window,
  workspace, preference, keyboard-shortcut and gesture events for scripts to react to.
  - Source: Vivaldi control-surface audit, 2026-10-08, Vivaldi 8.2.4133.84;
    [docs/VIVALDI_CONTROL_SURFACE.md](docs/VIVALDI_CONTROL_SURFACE.md) ("Events").
  - Starting point: `EVENT_HOOKS` and `__remaldiChanged` in `browser.py`; protocol version 1 in `protocol.py`.
  - Dependencies: none.
  - Experiment: establish whether this could ever be useful before designing it.
    Read-only, observe which candidate sources actually fire and what they carry
    (shapes and rates only, no URLs or titles recorded), and name at least one
    concrete script that needs a stream rather than polling `state`.
  - Acceptance: a recommendation to drop the entry, or a Ready entry that settles
    whether a long-lived streaming response fits protocol version 1 or needs a new
    version, which sources are exposed, and back-pressure, filtering and privacy
    (events carry URLs and titles).

## Ready for separate work
