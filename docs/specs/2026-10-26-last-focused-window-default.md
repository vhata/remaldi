# Last-focused window default: proof of concept and implementation contract

## Recommendation

Use `chrome.windows.getLastFocused` in the selected regular Vivaldi UI
context to supply the default window for `workspace switch`, `command run`
and `window list`. An additional focus-history tracker is unnecessary for
the observed behavior. Keep explicit window IDs authoritative and retain
the existing dispatch-time existence and minimized-window checks.

This is an implementation recommendation, not a production behavior
change. The implementation remains a separate TODO and PR.

## Problem and current source

At source revision `11b8348bc1a595650a251806d8d71b7d65b163fb`,
[`_default_window`](../../remaldi/adapter.py) requires exactly one window
whose `focused` field is true. `_select_window` and `list_windows` share
that rule. With no qualifying window, commands without an explicit ID fail
with `ambiguous_window` and listing reports no default.

Both mutation paths select from a cached snapshot, then recheck the chosen
window through `chrome.windows.get` in the dispatch evaluation. They reject
missing or minimized windows before dispatch. The mutation lock and
no-replay contract remain essential.

[`EVENT_HOOKS`](../../remaldi/browser.py) already invalidates state on window
creation, removal and focus changes. Connection generation, UI-target
changes and the five-second TTL also refresh state. No agent-maintained
focus history is currently recorded. These selection and hook paths were
unchanged at integration base
`a0557424d456fc1f300f4f042d3f774c7477ebc2`.

## Observed evidence

The user explicitly authorized the listed read-only probes against an
already-running debug-enabled Vivaldi, then individually confirmed each
manual checkpoint. All focus, window creation, minimization, restoration
and closure actions were performed by the user. The probe never launched,
restarted, reloaded or changed browser state, installed listeners, or
started a Remaldi daemon.

Environment: macOS, Vivaldi reported as `Chrome/8.2.4133.94`, DevTools
protocol 1.3. Samples ran on 2026-10-27 UTC, still 2026-10-26 locally.
Exactly one regular UI context passed classification. Each checkpoint had
two samples one second apart, after a 15-second setup delay. Each sample
used fresh short-lived CDP connections without adding event hooks.

[Sanitized per-sample evidence](../evidence/2026-10-26-last-focused-window-default.json)
retains aliases, API outcomes, window status, version and timestamps only.
Raw window/target IDs, debugger addresses, titles, tab URLs, workspace
names, profile contents and raw errors were never retained. Foreground
application identity is user attestation; the probe did not inspect OS
foreground state.

| Checkpoint | UTC samples | Window state while terminal frontmost | Both getLastFocused filters |
| --- | --- | --- | --- |
| Baseline | 06:32:09 / 06:32:10 | W1 maximized, focused false | W1 |
| Focus original A, then terminal | 06:33:44 / 06:33:45 | W1 maximized, focused false | W1 |
| Create/focus disposable B, then terminal | 06:35:43 / 06:35:44 | W1 and W2 maximized, both focused false | W2 |
| Focus original A again, then terminal | 06:37:32 / 06:37:33 | W1 and W2 maximized, both focused false | W1 |
| Manually minimize both windows | 06:54:01 / 06:54:02 | W1 and W2 minimized, both focused false | W2, minimized |
| Restore/focus/close disposable B | 06:58:33 / 06:58:34 | Only W1 remains, minimized, focused false | W1, minimized |

Every before/after window list matched within its sample. Every sampled
window had type normal; the UI target did not change. Default and
normal-only query filters agreed throughout.

The first post-close sample still looked up the previous selection W2:
W2 was absent from both lists and `get(W2)` returned `api_error`.
`getLastFocused` returned current W1. The second sample had already updated
the tracked previous selection to W1, whose lookup succeeded. The nearest
pre-close API observation was minimized W2; restoring/focusing W2
immediately before closing it was user-confirmed, not separately sampled.

These observations answer the proof-of-concept questions:

- The API returns a last-focused window while the terminal is frontmost,
  even when every current window reports focused false.
- It follows W1 to W2 to W1. The final transition is between two existing
  windows, so the result is not explained by window creation order alone.
- It can return a minimized window, including when all windows are
  minimized. Minimization must not imply an automatic restore or fallback.
- After the selected window closes, a new query returns a surviving
  window; lookup of the closed ID fails. A cached ID can still become stale
  between snapshot selection and dispatch, so keep the existence guard.
- The result was available on fresh connections with no focus observer
  installed by this probe. No new Remaldi observer needs to see a focus
  event before querying it. Actual service restart and UI reload were not
  exercised; this does not establish their end-to-end behavior.

## Probe method and reproduction

Follow [the authorization and privacy rules](../QUALITY.md#live-browser-acceptance)
before rerunning. Read loopback `/json/version` and `/json/list` only into
memory. Match the built-in Vivaldi extension's `main.html` URL exactly,
then evaluate `chrome.extension.inIncognitoContext` in each candidate on a
direct short-lived `CDPConnection`. Require exactly one false result;
ambiguous, missing or unclassified contexts stop the experiment. Do not
print/save the discovery documents or incognito window state.

Use the transport directly rather than `Browser` or the Remaldi CLI:
connecting the selected target through `Browser` installs bindings and
hooks. Send only `Runtime.evaluate` with `awaitPromise: true` and
`returnByValue: true`, then close the connection. Never call
`Runtime.enable`, `Runtime.addBinding`, a listener API or a mutation.

The exact window expression below was evaluated after replacing both
`__PREVIOUS__` tokens with the preceding sample's successful last-focused
numeric ID, or `null` initially. That value lived only in process memory.
`populate:false` omits tab data; projection happens inside the UI before
the result crosses CDP. Callback errors become generic statuses, without
copying `lastError.message`.

```javascript
(async () => {
 const project = w => w && ({id:w.id, focused:w.focused, state:w.state, type:w.type});
 const call = (method, args, many=false) => new Promise(resolve => {
   try {
     if (typeof chrome.windows[method] !== 'function') {
       resolve({status:'unsupported'}); return;
     }
     chrome.windows[method](...args, value => {
       if (chrome.runtime.lastError) { resolve({status:'api_error'}); return; }
       resolve({status:'ok', value:many ? value.map(project) : project(value)});
     });
   } catch { resolve({status:'exception'}); }
 });
 const before = await call('getAll', [{populate:false}], true);
 const last = await call('getLastFocused', [{populate:false}]);
 const normal = await call('getLastFocused', [{populate:false,windowTypes:['normal']}]);
 const previous = __PREVIOUS__ === null ? {status:'not_requested'}
   : await call('get', [__PREVIOUS__, {populate:false}]);
 const after = await call('getAll', [{populate:false}], true);
 return {before,last,normal,previous,after};
})()
```

Before retaining results, map safe integer IDs to stable W1/W2 aliases in
memory. Output only the projected fields with allowlisted statuses,
state/type values, sanitized version/protocol strings and timestamps.
Suppress transport errors and exception details. Stop on any uncertain
browser/UI identity and start a new evidence session rather than carrying
aliases across it. Stable surrounding lists detect some races but do not
make the asynchronous calls atomic. The temporary Python 3.12 helper's
reviewed SHA-256 was
`5fe4d37a7b3d42a83194d457c76b4d60d46f379f71037b7572a794a6d1ec4d90`.

## Separate implementation contract

1. Extend `SNAPSHOT` to query `getLastFocused` in its existing regular UI
   context, using the same window-type policy as `getAll`. Normal-only
   filtering was a comparison probe, not a selected behavior change.
   A missing or failed API must not break explicit-ID operations.
2. Normalize `last_focused_window_id` and a
   `last_focused_window_status` enum: `ok`, `unavailable`, `error`,
   `invalid`. Preserve that provenance; collapsing all failures to null
   would make the fallback policy below impossible to implement.
3. Change the shared default rule to accept the normalized snapshot and
   select a successful candidate only when its ID is a nonnegative safe
   integer, not a boolean, and identifies exactly one current window.
   Missing, malformed, sentinel, duplicate or out-of-context successful
   results fail closed. Never choose the first enumerated window.
4. On `unavailable` or `error` only, preserve the existing uniquely focused
   window rule as a compatibility fallback. Invalid successful results
   must not trigger that fallback. With no valid default, `window list`
   reports null and implicit mutations retain `ambiguous_window`, with an
   updated explanation. Explicit IDs continue through existing checks.
5. Use the same helper for `default_window_id`, workspace switching and
   command dispatch. Report the API-selected minimized window as the
   default; retain `minimized_window` before dispatch. Do not restore,
   silently retarget or retry. Retain the final existence check so a
   window closed after snapshot acquisition rejects that request.
6. Retain mutation serialization, no replay, existing event invalidation,
   TTL refresh and generation handling. No new global history, listener
   set or hook-version change is needed. Selection remains snapshot-based:
   with TTL-only support, it may lag by five seconds. Do not promise an
   atomic focus-at-dispatch guarantee. Explicit `window list --refresh`
   obtains a fresh snapshot, subject to the existing refresh contract.
7. Update README, architecture semantics, error text and SPEC evidence
   boundaries in the implementation PR. Preserve the distinction between
   default selection, dispatch success and visibly verified effects.

Required regression coverage includes terminal foreground, W1/W2 focus
changes, a fresh adapter before observed events, explicit overrides,
minimized selection, closure before selection and between snapshot and
dispatch, API availability/error/status distinctions, invalid IDs and
membership, window-list/default parity, and no fallback or replay after
dispatch failure. Cover event, TTL and generation invalidation, including
invalidation during refresh. Execute the added callback/error JavaScript
with synthetic API fixtures where practical; text assertions alone do
not establish its runtime semantics. Run the shared repository gate and
obtain independent review before presenting production changes as ready.

## Limits and remaining acceptance

This establishes API selection on the observed macOS Vivaldi build. It
does not establish Linux behavior, other versions, popup/private/multiple
regular-profile semantics, event delivery, real service cache freshness,
UI reload, browser restart or any command's visible effect. Keep the
current regular-profile/type policy and fail closed on unsupported data.
There is no need to add custom focus history based on these results; if a
future build breaks the API, reassess rather than persisting stale IDs.

No live mutations or browser lifecycle operations are needed to implement
and test the proposed selection rule. Existing workspace/command/reconnect
acceptance TODOs remain separate and require their own authorization.
