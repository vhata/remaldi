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

## Needs proof of concept

### Unprioritized

No entries.

## Ready for separate work

### Unprioritized

- [STATE] `implement-workspace-enumeration` — **Report workspaces from Vivaldi's workspace preference.** Vivaldi 8.2 has
  no `vivaldi.workspaces` API, so snapshots always report workspaces unsupported.
  - Source: `discover-workspace-enumeration` read-only live probe, 2026-10-08,
    Vivaldi 8.2.4133.84.
  - Starting point: `SNAPSHOT` in `adapter.py` and `EVENT_HOOKS` in `browser.py`.
  - Contract: `vivaldi.prefs.get('vivaldi.workspaces.list', callback)` yields
    `{value, defaultValue, store}`. `value` lists `{id, name, icon, emoji?}` with
    unique nonnegative safe-integer IDs in the decimal form `switch_workspace`
    accepts; switching to them is unverified. `icon` is inline SVG; omit it. A tab's membership is the numeric
    `workspaceId` in its `vivExtData` JSON; tabs without one are in no workspace.
    A missing `prefs.get` or malformed value is unsupported. `vivaldi.prefs.onChanged`
    and `vivaldi.tabsPrivate.onExtDataChanged` exist but were not observed firing;
    keep the TTL fallback.
  - Acceptance: tests cover the supported shape, malformed values, and fallback;
    a read-only live check reports the workspace capability and IDs without
    committing names. A window's active workspace is out of scope until verified.
