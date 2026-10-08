# Accepted scope

Remaldi is a generic local control client for an already-running Vivaldi browser.
The CLI and daemon are the same executable. Browser commands start the service on
first use; it stays running so subsequent clients reuse connections and state.
Friendly operations and raw DevTools requests are both required. Workspace
switching is the first friendly mutation, not the boundary of the product.

## Implemented foundation

| Capability | Evidence boundary |
| --- | --- |
| On-demand service, status, stop, private local socket | Automated lifecycle tests; status/stop do not start an absent service. |
| Persistent correlated DevTools connections, discovery, reconnection | Fake-WebSocket tests and read-only live connection/reuse checks on 2026-10-02. |
| Window/tab state, capability discovery, event invalidation, shared refreshes | Automated tests and read-only live state/event subscription checks on 2026-10-02. |
| Friendly workspace dispatch and raw/evaluate access | Automated dispatch tests; live raw request checked on 2026-10-02. Visible workspace switching remains unverified. A static reading on 2026-10-08 found the dispatched command is positional, not ID-based; see `fix-workspace-switch-by-id` in TODO. |
| Python quality gates, secret audit, package builds, MIT license | Executable gates; macOS/Linux CI passed at `83b49ee`. This is not browser acceptance. |

Vivaldi 8.2.4133.84 has no `vivaldi.workspaces` API, so the snapshot reports
`workspaces: null` with capability false. A read-only probe on 2026-10-08 found
the list in the `vivaldi.workspaces.list` preference and tab membership in tab
`vivExtData`; `implement-workspace-enumeration` in TODO adopts that source. Do not
describe an unsupported or unverified capability as delivered browser behavior.

## Remaining foundation acceptance

- [ ] Observe a switch to a known workspace in a live Vivaldi window and confirm
  repeated client calls reuse the service. See `verify-live-workspace-switch` in TODO.
- [ ] After a user-controlled debug-enabled browser restart, confirm reconnection,
  fresh state, and continued service reuse. See `verify-live-browser-reconnect`.

The delivery order is transport, discovery/state adapter, service/client,
automated checks, and live acceptance. Adding friendly commands is separate scoped
work: first specify the operation's target, semantics, capability support, and
observable acceptance. No new browser operation is selected by this setup.

## Boundaries

- The service never launches or restarts Vivaldi. A debugging endpoint is an
  external prerequisite; retaining the launch flag through updates is unresolved.
- Control is local to the current user on macOS/Linux. Network control, automatic
  browser relaunch, and Chrome support are outside the accepted implementation.
- Browser-specific UI APIs may vary by version. Report unsupported capabilities
  and uncertain outcomes explicitly; never blindly repeat a mutation.
- Tab stacking was an example during design, not a selected feature requirement.
