# Ordinary deferred work

Use [the TODO guide](docs/TODO_GUIDE.md) before selecting or moving an entry.
These are known follow-ups, not assignments. Check open PR claims and dependencies
before calling ready work available. Priorities below are intentionally unassigned.

## Needs triage

### Unprioritized

- [BROWSER] `retain-debugging-across-launches` — **Determine supported ways to keep
  debugging enabled through ordinary launches and updates.** Wrapper launches do
  not establish a flag for every future launch; keep the no-browser-launch contract.
  - Source: browser restart discussion, 2026-10-02; SPEC boundaries.
  - Starting point: Vivaldi launch configuration and supported restart behavior.
  - Triage outcome: evidence-backed feasible options or documented limitation;
    do not attribute an observed restart to an unverified external cause.

## Needs proof of concept

### Unprioritized

- [STATE] `discover-workspace-enumeration` — **Identify a usable workspace listing
  API in the running Vivaldi UI.** The first live check found the current probe
  unsupported; do not promise listing from generic DevTools connectivity alone.
  - Source: read-only live acceptance, 2026-10-02; SPEC foundation evidence.
  - Starting point: `adapter.py` snapshot probe and capability fallback.
  - Experiment: read-only API discovery; record support/version without private
    names or browsing data. Produce an implementation-ready contract or limitation.

## Ready for separate work

### Unprioritized

- [ACCEPTANCE] `verify-live-workspace-switch` — **Validate visible switching and
  service reuse in a running Vivaldi browser.** Current success confirms dispatch.
  - Source: accepted plan and remaining live acceptance, 2026-10-02.
  - Starting point: workspace CLI and live scenario in docs/QUALITY.md.
  - Depends on: an already-running debug-enabled Vivaldi, known workspace IDs,
    and explicit authorization for the selected visible change.
  - Acceptance: observe the selected workspace, confirm the same service PID on
    subsequent calls, and report version/capabilities and limits without private data.

- [ACCEPTANCE] `verify-live-browser-reconnect` — **Validate reconnection and fresh
  state after a browser restart.** Automated fake-target tests do not establish this.
  - Source: accepted plan and remaining live acceptance, 2026-10-02.
  - Starting point: browser monitor, cache generation, and docs/QUALITY.md scenario.
  - Depends on: a user-controlled restart of a debug-enabled browser and a safe
    window for observing it; the agent/service must not restart it automatically.
  - Acceptance: observe disconnect/reconnect, retain the service PID, and verify
    fresh state after the new browser target appears.
