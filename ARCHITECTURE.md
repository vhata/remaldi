# Architecture contracts

## Boundaries

`remaldi.__main__` parses CLI commands; `client` sends versioned JSON requests and
starts a detached copy in `serve` mode when needed. `runtime` owns private paths
and locks. `service` validates and dispatches operations. `browser` discovers
targets and maintains connections. `transport` correlates CDP requests and routes
events. `adapter` owns Vivaldi-specific state and friendly command semantics.

The service operation registry is the extension point for friendly operations.
Raw requests go directly through the browser/transport layers and invalidate
state conservatively. Do not add browser semantics to socket or lifecycle code.
The archived `reference/vivaldiws` is historical context, not a runtime dependency.

## Interfaces and ownership

- Socket protocol version 1 uses newline-delimited JSON: requests contain
  `version`, `id`, `operation`, and object `params`; replies echo version/id and
  contain `ok` plus `result` or structured `error`. The user-facing examples and
  framing limits are in README; `protocol.py` is the executable constant source.
- Runtime directory and socket are private to the current user. The startup lock
  serializes first-use launches; the lifetime lock establishes ownership before
  stale socket replacement. `status`/`stop` never start a missing service.
- Browser discovery and WebSockets bypass inherited proxies. Default requests
  target the dynamically discovered Vivaldi UI; raw callers may select a target ID.
  Reconnection changes must not preserve obsolete targets or browser snapshots.
- Browser state is authoritative. Adapter snapshots are derived, expire after
  five seconds, and invalidate on supported events and connection changes.
  Overlapping refreshes share work. Unsupported events fall back to TTL refresh.
- Friendly mutations serialize in the adapter. Workspace switching accepts
  internal IDs and an explicit window or the uniquely focused window. Its result
  confirms dispatch, not a visually verified switch.

## Failure and acceptance invariants

Never launch/restart the browser or replay an operation after an uncertain
transmission. Requests match responses by ID even when events interleave. The
complete server operation deadline includes queueing; cancelled queued mutations
must not execute later. Preserve structured protocol, target, capability, browser
exception, and unknown-outcome errors.

Service readiness is distinct from browser connectivity. An unavailable endpoint
does not prove whether the browser is closed or merely missing debugging flags.
Status distinguishes endpoint rejection and missing UI targets; event subscription
failure is observable as TTL-only support.

Tests of a fake server prove transport/lifecycle invariants, not Vivaldi API
compatibility or visible behavior. Keep live checks separate and avoid committing
browser URLs, titles, profile captures, or credentials as evidence.

## Future changes

If Chrome or another browser is explicitly selected, define its capability and
target adapter contract first. Reuse the generic transport/lifecycle layers;
do not assume Vivaldi's privileged UI target exists elsewhere. This is a design
boundary, not authorization to implement a second adapter.
