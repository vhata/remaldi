# Vivaldi control surface

This guide records what a DevTools connection to a running Vivaldi can drive and
how each part of that list was found. Every procedure below is a command or a
JavaScript expression you can run yourself. Re-run them after a Vivaldi update,
because private UI APIs and minified bundle code change between versions.

Observed on Vivaldi 8.2.4133.84 (Chromium 152, DevTools protocol 1.3) on macOS,
2026-10-08. Evidence labels used below:

- **Live**: a read-only expression evaluated in the running browser.
- **Static**: read from the installed Vivaldi application files without the browser.
- **Unverified**: inferred, not exercised. Treat it as a hypothesis.

Nothing in this guide dispatches a command, writes a preference, or changes the
browser. Keep it that way when re-running it. Mutation experiments belong to a
selected task with explicit authorization (see [QUALITY.md](QUALITY.md)).

## Ground rules for probing

- Vivaldi must already be running with `--remote-debugging-port=9222`. Never
  launch or restart it for a probe.
- Ask for names, counts, types and shapes, not values. Tab URLs and titles,
  workspace names, bookmarks, keybindings and mail are private profile data. Do
  not commit or publish them.
- Do not evaluate anything from the hazard list in
  [What not to wrap](#what-not-to-wrap). `typeof x.y` and `Object.keys(x)` are
  safe. Calling `x.y(...)` is only safe once you know what it does.

## Step 1: find the debugger targets

The debugging endpoint is plain HTTP on loopback. Bypass any proxy:

```bash
curl -s --noproxy '*' http://127.0.0.1:9222/json/version
curl -s --noproxy '*' http://127.0.0.1:9222/json/list | jq -r 'group_by(.type)[] | "\(.[0].type)\t\(length)"'
curl -s --noproxy '*' http://127.0.0.1:9222/json/list |
  jq -r '.[] | select(.url | startswith("chrome-extension://mpognobbkildjkofajifpdfhcoklimli/")) | "\(.type)\t\(.url)"'
```

The first command counts targets by type. The second lists only Vivaldi's own UI
targets. Printing every target's URL would show your open tabs.

`/json/version` reports the Vivaldi version as `Browser` (it says `Chrome/8.2...`).
`/json/list` has one entry per target: every web tab (`page`), iframes, workers,
and Vivaldi's own UI. The UI is a built-in extension with ID
`mpognobbkildjkofajifpdfhcoklimli`, and it exposes two `app` targets:

| Target URL suffix | What it is (Live) |
| --- | --- |
| `mpognobbkildjkofajifpdfhcoklimli/main.html` | A nearly empty document (8 elements) with the full `vivaldi.*` and `chrome.*` API set. Remaldi's default target. |
| `mpognobbkildjkofajifpdfhcoklimli/window.html` | The rendered browser UI: around a thousand elements (the count varies), a `#browser` root, and a numeric `window.vivaldiWindowId`. It has the same APIs. Target this to style or alter the UI. |

How several browser windows map onto `window.html` targets is Unverified. The
probe ran with one window open.

To get the WebSocket URL of the API target:

```bash
curl -s --noproxy '*' http://127.0.0.1:9222/json/list |
  jq -r '.[] | select(.url | contains("mpognobbkildjkofajifpdfhcoklimli/main.html")) | .webSocketDebuggerUrl'
```

## Step 2: send an expression to the UI target

Each probe is one DevTools `Runtime.evaluate` request over the target's
WebSocket:

```json
{"id": 1, "method": "Runtime.evaluate",
 "params": {"expression": "typeof vivaldi.menubar.onActivated.dispatch",
            "awaitPromise": true, "returnByValue": true}}
```

`returnByValue` returns plain JSON instead of an object handle. `awaitPromise`
waits when the expression returns a promise. A successful reply looks like
`{"id":1,"result":{"result":{"type":"string","value":"function"}}}`. A
JavaScript error comes back as `result.exceptionDetails` rather than an
HTTP or WebSocket error.

Any of these sends the request.

**With Remaldi itself.** Install it as described in the README, then:

```bash
remaldi evaluate 'Object.keys(vivaldi).length' --await-promise --return-by-value
```

This prints `{"result": {"type": "number", "value": 41, ...}}` and leaves the
Remaldi service running. Run `remaldi stop` afterwards.

**With curl, jq and websocat** (`brew install jq websocat`). Define this shell
function and pass it an expression:

```bash
vivaldi_eval() {
  local ws
  ws="$(curl -s --noproxy '*' http://127.0.0.1:9222/json/list |
    jq -r '.[] | select(.url | contains("mpognobbkildjkofajifpdfhcoklimli/main.html")) | .webSocketDebuggerUrl')"
  jq -cn --arg expr "$1" \
    '{id: 1, method: "Runtime.evaluate",
      params: {expression: $expr, awaitPromise: true, returnByValue: true}}' |
    websocat -n1 -B 67108864 "$ws" |
    jq 'if (.result.result | has("value")) then .result.result.value else .result end'
}

vivaldi_eval 'typeof vivaldi.menubar.onActivated.dispatch'   # "function"
vivaldi_eval 'nonexistent()'   # prints {"result": ..., "exceptionDetails": ...}
```

`-n1` sends one message and exits after one reply. `-B` raises websocat's buffer
for large results. To target `window.html`, change the `contains(...)` string.
Longer expressions can live in a file: `vivaldi_eval "$(cat probe.js)"`.

**With DevTools (Unverified).** Vivaldi's `vivaldi://inspect/#apps` page should
list the UI documents with an Inspect link that opens a console. Paste the
expressions there. This route was not exercised for this guide.

## Step 3: list the extension APIs (Live)

The UI target can call Vivaldi's private extension APIs on the global `vivaldi`
object, plus the standard `chrome` extension APIs. This expression lists every
namespace, separating functions from events. An event is an object with
`addListener`. It only reads property names:

```js
(() => {
  const describe = (root) => {
    const out = {};
    for (const ns of Object.keys(root || {}).sort()) {
      const o = root[ns]; if (!o || typeof o !== 'object') continue;
      const fns = [], evs = [];
      for (const k of Object.keys(o).sort()) {
        if (typeof o[k] === 'function') fns.push(k);
        else if (o[k] && typeof o[k].addListener === 'function') evs.push(k);
      }
      out[ns] = {fns, evs};
    }
    return out;
  };
  return {vivaldi: describe(typeof vivaldi === 'undefined' ? {} : vivaldi), chrome: describe(chrome)};
})()
```

On 8.2 it returned 41 `vivaldi.*` namespaces (420 functions, 154 events) and 37
`chrome.*` namespaces (332 functions, 100 events). The full lists are in
[Appendix A](#appendix-a-vivaldi-namespaces-in-the-ui-target) and
[Appendix B](#appendix-b-chrome-namespaces-in-the-ui-target). Note there is no
`vivaldi.workspaces` namespace in 8.2.

These APIs follow the Chrome extension convention: most take a trailing callback
and report failure through `chrome.runtime.lastError`. Wrap a read in a promise:

```js
new Promise(r => vivaldi.prefs.get('vivaldi.workspaces.enabled',
  v => r(chrome.runtime.lastError ? {error: chrome.runtime.lastError.message} : v)))
```

`vivaldi.prefs.get` passes `{value, defaultValue, store}` to its callback.

Function names do not document argument shapes. Before using a function, find
its call sites in the bundle (Step 5) or ask for its shape with `.length` and
`toString()`. Native bindings print `[native code]`, so call sites are the
better source.

## Step 4: list the DevTools protocol domains (Live)

The browser publishes its protocol schema:

```bash
curl -s --noproxy '*' http://127.0.0.1:9222/json/protocol |
  jq -r '.domains[] | .domain + (if .experimental then " (experimental)" else "" end)'
```

8.2 reports 58 domains, the standard Chromium set. Commands and events for each
are in the same JSON under `.domains[].commands` and `.domains[].events`. The
[Chrome DevTools Protocol reference](https://chromedevtools.github.io/devtools-protocol/)
documents them. Send these over a target's WebSocket the same way as
`Runtime.evaluate`, or use `remaldi raw METHOD --params '{...}' --target ID`.

## Step 5: read Vivaldi's installed UI code (Static)

The UI is a JavaScript bundle in the application package. On macOS:

```bash
VIVALDI_RES="/Applications/Vivaldi.app/Contents/Frameworks/Vivaldi Framework.framework/Versions/Current/Resources/vivaldi"
ls "$VIVALDI_RES"
```

On Linux packages it is typically `/opt/vivaldi/resources/vivaldi` (Unverified).
The files that matter:

| File | Contents |
| --- | --- |
| `bundle.js` | Minified UI code (about 6.7 MB): command registry, stores, API call sites. |
| `prefs_definitions.json` | Every Vivaldi preference with `type`, `default` and `description`. |
| `menus/mainmenu.json`, `menus/contextmenu.json` | Default menus. Each `"type":"command"` item names an `action`. |
| `window.html`, `main.html` | The two UI documents from Step 1. |

### Command names

```bash
grep -oE 'COMMAND_[A-Z0-9_]+' "$VIVALDI_RES/bundle.js" | LC_ALL=C sort -u > commands.txt
wc -l commands.txt     # 368 on 8.2
```

This is every string that looks like a command. It includes store action
types such as `COMMAND_INITIALIZE`, category suffixes, and UI prefixes such as
`COMMAND_WORKSPACE_SWITCH_` that the code tests with `startsWith`. Appendix C has
the grouped list.

The command registry is the set that dispatch can run. Each entry has the form
`{name:"COMMAND_...",action:...}`:

```bash
grep -oE '\{name:"COMMAND_[A-Z0-9_]+",action:' "$VIVALDI_RES/bundle.js" |
  sed -E 's/\{name:"(.*)",action:/\1/' | LC_ALL=C sort -u > registered.txt
wc -l registered.txt   # 339 on 8.2
LC_ALL=C comm -23 commands.txt registered.txt   # the 29 strings that are not registered commands
```

The `vivaldi.actions` preference stores shortcuts and gestures. Its defaults (a
generic, a Mac and a Linux set) list the commands that ship with a default
binding. This is a subset of the registry, not the full set of bindable commands:

```bash
jq -r '[.vivaldi.actions.default[0], .vivaldi.actions.default_mac[0], .vivaldi.actions.default_linux[0]]
       | map(keys) | add | unique | .[]' "$VIVALDI_RES/prefs_definitions.json" | LC_ALL=C sort > default-bound.txt
wc -l default-bound.txt   # 190 on 8.2
LC_ALL=C comm -23 default-bound.txt registered.txt   # 2 on 8.2: MAIL_COMPOSER_DOCK and _UNDOCK
```

Sort with `LC_ALL=C` everywhere, or `comm` compares the lists incorrectly. Many
useful commands have no default binding, for example `TAB_STACK_CREATE`,
`PIN_TAB`, `CLONE_TAB` and `SAVE_SESSION`.

Commands that appear in the default menus:

```bash
jq -r '.. | objects | select(.type == "command") | .action' "$VIVALDI_RES/menus/mainmenu.json" | sort -u
```

To see how one command is defined, search for its registry entry:

```bash
grep -oE '\{name:"COMMAND_TAB_STACK_CREATE",action:.{0,200}' "$VIVALDI_RES/bundle.js"
```

### Preferences

```bash
jq -r '.vivaldi | paths(objects and has("type")) as $p
       | "vivaldi.\($p | join("."))\t\(getpath($p).type)\t\(getpath($p).description // "")"' \
  "$VIVALDI_RES/prefs_definitions.json"
```

This prints all 622 `vivaldi.*` preference paths with their type and
description. The file also defines 65 `chromium` and 21 `chromium_local`
entries. These map Chromium constants such as `kNetworkPredictionOptions` to
Chromium pref paths through a `path` field. Appendix D has counts per group.

To learn the shape of a live value without reading its contents, return keys and
counts only. This one reports how many commands have bindings in the profile and
which fields they use:

```js
new Promise(r => vivaldi.prefs.get('vivaldi.actions', p => r({
  sections: p.value.length,
  commands: Object.keys(p.value[0]).length,
  fields: [...new Set(Object.values(p.value[0]).flatMap(Object.keys))]
})))
```

## How command dispatch works

Remaldi switches workspaces by calling
`vivaldi.menubar.onActivated.dispatch(windowId, commandName, parameter)` in
`main.html`, the method inherited from the original
[Bash script](../reference/vivaldiws). `dispatch` fires the event's listeners
locally, as if the native macOS menu bar had been used. To find the listeners:

```bash
grep -oE '.{60}menubar\.onActivated\.addListener.{40}' "$VIVALDI_RES/bundle.js"
grep -oE '_onMacMenuAction=\(e,t,n\)=>\{[^}]*\}' "$VIVALDI_RES/bundle.js" | sort -u
```

On 8.2 there are four registrations. Two belong to Settings views. They match
the same window ID, run only while active, and only accept actions that
`isActionAcceptedForSettings` allows. The other two register the same
browser-window handler (minified names vary by version):

```js
_onMacMenuAction=(e,t,n)=>{e!==this.context.vivaldiWindowId||ie.ZP.isMinimized(e)
  ||Te.Z.executeLocalAction(e,t,n)||K.Z.executeActions("menu",this.context,t)}
```

The second registration is in a component that renders a read-only address bar,
probably for popup-style windows (Unverified). Every handler checks the window
ID, so a dispatch to a normal window should run once. With Settings open in that
window, a settings-accepted action might run twice (Unverified).

So, for `dispatch(windowId, name, parameter)`:

- `windowId` must equal the target window's `vivaldiWindowId`, which is its
  `chrome.windows` ID. Other windows ignore the dispatch. **A minimized window
  ignores it too.** The check reads Vivaldi's own window store, so a caller
  should check `chrome.windows.get(windowId)` in the same expression as the
  dispatch rather than rely on an older snapshot.
- The handler first tries `executeLocalAction(windowId, name, parameter)`, a
  small set of actions that take `parameter` as a string (below). If none
  matches, `name` goes to `executeActions`, the registry used by keyboard
  shortcuts, gestures and Quick Commands. `parameter` is not passed to that
  registry. A registry command whose definition has a default parameter
  receives that default instead.
- If `name` is not a registered command, `executeActions` looks for a
  user-defined chain with that `name` in `vivaldi.chained_commands.command_list`
  and runs its steps. It logs a lookup-failure warning either way. A chain can
  contain any command, including the ones in [What not to wrap](#what-not-to-wrap).
- The call returns nothing. An unknown name or a minimized window gives no
  error, so success means only that the event fired.

```bash
grep -oE 'executeActions\([a-z],[a-z],[a-z],[a-z]\)\{.{0,400}' "$VIVALDI_RES/bundle.js"
```

### Local actions that take a parameter

```bash
grep -oE 'case"JS_LOCAL_[A-Z_]+"' "$VIVALDI_RES/bundle.js" | sort -u
grep -oE 'getHandlerByLocalAction\(e,t,n\)\{.{0,2600}' "$VIVALDI_RES/bundle.js"
grep -oE 'getHandlerByAction:\(e,t,n\)=>\{.{0,500}' "$VIVALDI_RES/bundle.js"
```

| Name | Parameter | Effect on 8.2 (Static) |
| --- | --- | --- |
| `JS_LOCAL_ACTIVATE_WORKSPACE` | workspace ID | `setActiveWorkspace(windowId, parseInt(parameter))`. If the workspace is already active in any window, that window is focused instead. If no tab belongs to the ID, a start-page tab tagged with it is created, even when the ID is not in `vivaldi.workspaces.list`. |
| `JS_LOCAL_ACTIVATE_TAB` | tab ID | Switches to the tab's workspace, then activates the tab |
| `JS_LOCAL_ACTIVATE_WINDOW` | window ID | Focuses that window |
| `JS_LOCAL_OPEN_SESSION` | saved session ID | Opens the saved session |
| `JS_LOCAL_ADD_ACTIVE_TAB_TO_BOOKMARKS` | bookmark folder ID | Bookmarks the active tab in that folder |
| `JS_LOCAL_TOGGLE_WEBPANEL`, `JS_LOCAL_RESTORE_WEBPANEL` | web panel ID | Toggles or restores a web panel |
| `JS_LOCAL_REOPEN_CLOSED_TAB`, `JS_LOCAL_REOPEN_CLOSED_WINDOW` | closed item or session ID | Reopens it during handler lookup. No handler is returned, so the name also reaches `executeActions` and logs a lookup warning. |
| `JS_LOCAL_CLEAR_CLOSED_TABS`, `JS_LOCAL_CLEAR_CLOSED_WEBPANELS` | none | Empties the closed-items list |
| `COMMAND_OPEN_LINK` | URL | Opens the URL using the link-opening setting |
| `PERIODIC_RELOAD` | minutes | Reloads the active tab on a timer. Repeating the same interval removes the timer. |
| `PERIODIC_RELOAD_DISABLE` | `all` or anything else | `all` stops timed reloads for tabs in the window's active workspace. Anything else stops the active tab's. |

Vivaldi's own native Window menu builds its workspace items from the first row,
with `commandName:"JS_LOCAL_ACTIVATE_WORKSPACE"` and `parameter:` the workspace
ID as a string:

```bash
grep -oE '.{40}"JS_LOCAL_ACTIVATE_WORKSPACE",s=t\.id\.toString\(\).{80}' "$VIVALDI_RES/bundle.js"
```

The workspace activation behaviour in the first row comes from the function
that `setActiveWorkspace` calls. On 8.2 it is the only one containing
`"SET_ACTIVE_WORKSPACE",windowId:e,workspaceId:t`:

```bash
grep -oE 'async function [A-Za-z]+\(e,t,n\)\{if\(n\)return void await [A-Za-z]+\(e,t\);.{0,800}' "$VIVALDI_RES/bundle.js"
```

None of these were exercised live.

## Workspace switching: positional commands and the ID action (Static)

The `COMMAND_WORKSPACE_SWITCH_*` registry entries select by position:

```bash
grep -oE '\{name:"COMMAND_WORKSPACE_SWITCH_[0-9]+",action:[^}]{0,80}' "$VIVALDI_RES/bundle.js"
grep -oE 'activateWorkspaceByIndex\([a-z],[a-z]\)\{.{0,160}' "$VIVALDI_RES/bundle.js"
```

On 8.2 these show:

```text
COMMAND_WORKSPACE_SWITCH_1  -> activateWorkspaceByIndex(windowId, undefined)   no workspace
COMMAND_WORKSPACE_SWITCH_2  -> activateWorkspaceByIndex(windowId, 0)           first workspace
...
COMMAND_WORKSPACE_SWITCH_10 -> activateWorkspaceByIndex(windowId, 8)           ninth workspace

activateWorkspaceByIndex(e,t){if("number"!=typeof t)i.ZP.setActiveWorkspace(e,void 0);
  else{const n=d.Z.getWorkspaces()[t]?.id;n&&i.ZP.setActiveWorkspace(e,n)}}
```

No registered command takes an internal workspace ID, and only the first nine
workspaces have one. `WORKSPACE_MOVE_TABS_TO_0` to `_9` follow the same pattern
with an offset of one. The label helper that names them in the UI confirms the
offsets:

```bash
grep -oE 'function [A-Za-z]+\(e\)\{if\(!e\.name\.startsWith\("COMMAND_WORKSPACE_SWITCH_"\).{0,300}' "$VIVALDI_RES/bundle.js"
```

The order is the order of the `vivaldi.workspaces.list` preference. The
workspace store initializes from that preference and writes its order back
whenever it changes:

```bash
grep -oE 'actionType:"WORKSPACES_INIT".{0,160}' "$VIVALDI_RES/bundle.js"
```

```js
r.Z.dispatch({actionType:"WORKSPACES_INIT",workspaces:o.Z.get(u.kWorkspacesList),activeWorkspaces:e}),
d.Z.addListener((()=>{a.Z.set(u.kWorkspacesList,d.Z.getWorkspaces())}))
```

The same initializer sets each window's active workspace from its active tab's
`vivExtData.workspaceId`.

Remaldi currently sends `COMMAND_WORKSPACE_SWITCH_` plus a caller-supplied number
described as an internal ID, with an empty parameter. Internal IDs are 13-digit
numbers, so that name matches no registered command, and small numbers select by
position. Dispatching `JS_LOCAL_ACTIVATE_WORKSPACE` with the ID as the parameter
takes the same path as the native Window menu, with no position mapping and no
nine-workspace limit. Because an unknown ID creates a tab, a caller must check
the ID against `vivaldi.workspaces.list` first. TODO `fix-workspace-switch-by-id`
covers the change. None of this has been exercised live.

## What can be driven

### Commands (via dispatch)

The 339 registered commands cover most of what a keyboard user can do, and the
local actions above add parameterised workspace, tab, window, session and URL
operations. Useful command groups:

| Area | Commands (prefix `COMMAND_` omitted) |
| --- | --- |
| Tabs | `TAB_SWITCH_1`..`9`, `TAB_SWITCH_LAST`, `TAB_MOVE_*`, `TAB_STACK_CREATE`, `TAB_STACK_CREATE_BY_HOSTS`, `TAB_STACK_DISSOLVE`, `TAB_STACK_TILE_GRID`/`_HORIZONTAL`/`_VERTICAL`, `DISBAND_TILE_GROUP`, `CLONE_TAB`, `PIN_TAB`, `HIBERNATE_OTHER_TABS`, `CLOSE_TAB_TO_LEFT`/`_RIGHT`, `CLOSE_ALL_BUT_ACTIVE_TAB`, `TAB_REOPEN_RECENTLY_CLOSED`, `MOVE_TAB_TO_NEW_WINDOW` |
| Workspaces | `JS_LOCAL_ACTIVATE_WORKSPACE` (by ID), `WORKSPACE_SWITCH_1`..`10` (positional), `WORKSPACE_SWITCH_BACK_ORDER`/`_FORWARD_ORDER`, `WORKSPACE_MOVE_TABS_TO_0`..`9`, `WORKSPACE_CREATE_NEW`, `HIBERNATE_INACTIVE_WORKSPACES` |
| Page | `PAGE_BACK`/`_FORWARD`/`_REFRESH`/`_RELOAD_NOCACHE`, `PAGE_MUTE_ALL`/`_OTHER`, `PAGE_TOGGLE_MUTE`, `PAGE_SCROLL_*`, `PAGE_COPY_URL`, `PAGE_COPY_ALL_URLS`, `READERVIEW_TOGGLE`, `TAB_TRANSLATE_PAGE`, `FIND_IN_PAGE`, `CAPTURE_PAGE_TO_DISK`/`_TO_CLIPBOARD`, `CAPTURE_AREA_*` |
| Browser UI | `MAIN_TOGGLE_UI`, `MAIN_TOGGLE_TAB_BAR`/`_ADDRESS_BAR`, `TOGGLE_PANEL`, `TOGGLE_FLOATING_PANEL`, `TOGGLE_AUTO_HIDE_*`, `POSITION_TAB_TOP`/`_BOTTOM`/`_LEFT`/`_RIGHT`, `MAIN_UI_ZOOM_*`, `MAIN_ZOOM_*`, `FULLSCREEN`, `BREAKMODE_TOGGLE`, `TOGGLE_FORCE_DARK_MODE`, `TOGGLE_IMAGES` |
| Panels | `SHOW_*_PANEL` (bookmarks, history, notes, downloads, mail, calendar, tasks, feeds, reading list, sessions, window, translate), `SHOW_WEB_PANEL_1`..`9`, `SHOW_NEXT_PANEL`/`_PREVIOUS_PANEL` |
| Windows and focus | `NEW_TAB`, `NEW_BACKGROUND_TAB`, `NEW_WINDOW`, `NEW_PRIVATE_WINDOW`, `WINDOW_MINIMIZE`, `FOCUS_ADDRESSFIELD`/`_TABBAR`/`_PANEL`/`_WEBVIEW`, `SHOW_QUICK_COMMANDS` |
| Sessions and data | `SAVE_SESSION`, `OPEN_SESSION`, `EXPORT_*`, `IMPORT_*` |
| Mail and calendar | 33 registered `MAIL_*` and 15 `CALENDAR_*` commands |

User-defined command chains are stored in
`vivaldi.chained_commands.command_list`. Dispatching a chain's `name` runs it
(Static, see [How command dispatch works](#how-command-dispatch-works)).

### Private APIs (direct calls, with arguments)

These take arguments, so they can do what parameterless commands cannot.
Argument shapes are Unverified until a call site is checked (Step 5).

- `tabsPrivate`: `get`/`update` a tab's Vivaldi data (`vivExtData` JSON, which holds workspace membership, stack/tile grouping and fixed titles), `move`, `unstack`, `setGroupProperties`, `clone`, `scrollPage`, `insertText`, `translatePage`, `getTabPerformanceData`.
- `sessionsPrivate`: `getAll`, `add` (save), `open`, `rename`, `delete`, `getContent`, `restoreLastClosed`.
- `thumbnails`: `captureTab`, `captureUI`.
- `prefs`: `get`, `set`, `onChanged` over the preferences above.
- `windowPrivate`: `create`, `setState`, `getCurrentId`.
- `zoom`: UI zoom and default page zoom.
- `contentBlocking`: per-domain blocking exceptions, blocking statistics, filter sources.
- `notes`, `readingListPrivate`, `bookmarksPrivate`, `historyPrivate`, `calendar`, `contacts`: data stores.
- `searchEngines`, `omniboxPrivate` (search nicknames), `menuContent` (edit menus), `themePrivate`.
- `extensionActionUtils`: list toolbar extensions and run their actions.
- `utilities`: `copyToClipboard`, `getSelectedText`, `openPage`, `stripUrlTracking`, `generateQRCode`, `translateText`.
- Standard `chrome.tabs` (`create`, `query`, `move`, `group`, `discard`, `captureVisibleTab`, `setZoom`), `chrome.windows`, `chrome.sessions`, `chrome.bookmarks`, `chrome.history`, `chrome.downloads`, `chrome.scripting`, `chrome.notifications`.

### Preferences

Writes through `vivaldi.prefs.set` apply immediately and persist in the profile.
Groups relevant to control:

- `vivaldi.workspaces.list`, `.enabled`, `.link_routes` (rules that open links in a chosen workspace).
- `vivaldi.tabs.stacking.*`, `vivaldi.tabs.bar.position`.
- `vivaldi.actions` (all bindings), `vivaldi.chained_commands.command_list`.
- `vivaldi.themes.current`, `vivaldi.theme.schedule.*`, `vivaldi.layouts.saved`/`.selected`.
- `vivaldi.panels.*`, `vivaldi.toolbars.*`.

### DevTools protocol on web tabs

Every web tab is a `page` target with its own WebSocket. Through it:
`Runtime.evaluate` in the page, `Page.captureScreenshot`, `Page.navigate`,
`Page.bringToFront`, `Input.dispatchKeyEvent`/`dispatchMouseEvent`,
`Accessibility` and `DOMSnapshot` reads, and `Network`/`Fetch` observation.
Browser-wide methods go to the endpoint in `/json/version`:
`Target.setDiscoverTargets` streams tab creation, closure and navigation events,
plus `Target.activateTarget`, `Browser.getWindowForTarget`/`setWindowBounds` and
`Browser.setDownloadBehavior`.

### Browser UI changes

Expressions evaluated in `window.html` run inside the browser's own interface.
They can add a `<style>` element or change the DOM under `#browser`, which is
what community custom CSS/JS mods do through modified application files. Such
changes are lost when the UI reloads or the browser restarts, so a tool would
have to reapply them after each reconnection (Unverified).

### Events

Remaldi currently listens to `chrome.tabs` and `chrome.windows` events. Other
listenable sources include `vivaldi.prefs.onChanged`,
`vivaldi.tabsPrivate.onExtDataChanged`/`onKeyboardShortcut`/`onMouseGesture`/
`onMediaStateChanged`, `vivaldi.windowPrivate.onStateChanged`,
`vivaldi.sessionsPrivate.onChanged`, `chrome.downloads.onChanged`, and
DevTools `Target.*` events. None of these were observed firing during the probe.

## What not to wrap

These exist in the UI target and are reachable through `remaldi raw` or
`evaluate` today. Do not turn them into friendly operations:

- **Browser lifecycle**, which would break the never-restart contract:
  `vivaldi.runtimePrivate.exit`/`restart`, `chrome.runtime.restart`/`reload`,
  `vivaldi.autoUpdate.installUpdateAndRestart`,
  `vivaldi.runtimePrivate.closeActiveProfile`/`switchToGuestSession`, and the
  `EXIT` and `QUIT_MAC_MAYBE_WARN` commands. `CLOSE_WINDOW` on the last window
  may also quit the browser. User-defined chains can contain any of these
  commands.
- **Secrets**: `vivaldi.savedpasswords.*`,
  `chrome.passwordsPrivate.requestPlaintextPassword`/`exportPasswords`,
  `vivaldi.utilities.osDecrypt`, `vivaldi.utilities.get*OAuthClientSecret` and
  `getGAPIKey`, `vivaldi.utilities.getEnvVars`,
  `vivaldi.sync.backupEncryptionToken`, `chrome.autofillPrivate`,
  `chrome.cookies` (session cookies), `chrome.identity.getAuthToken`.
- **Destructive or profile-wide**: `vivaldi.prefs.resetAllToDefault`,
  `vivaldi.runtimePrivate.deleteProfile`, `vivaldi.sync.clearData`, `chrome.browsingData.*`,
  `chrome.history.deleteAll`, `vivaldi.mailPrivate` file writes and deletes,
  `vivaldi.utilities.silentlyInstallExtension`, `chrome.management.uninstall`,
  and the `MAIL_DELETE_PERMANENTLY` and `EXPORT_PASSWORDS` commands.

The debugging port has no authentication. Any local process that can open
`127.0.0.1:9222` gets all of the above whether or not Remaldi is running.
Remaldi's private socket does not reduce that exposure.

## Re-running after a Vivaldi update

1. Record the new version from `/json/version`.
2. Re-run Step 3 and diff against Appendices A and B.
3. Re-run the `commands.txt`, `registered.txt` and `default-bound.txt` commands and diff against Appendix C.
4. Re-run the dispatch and workspace greps. If the minified names changed,
   search for the unminified anchors instead: `menubar.onActivated.addListener`,
   `executeLocalAction`, `JS_LOCAL_`, `"COMMAND_WORKSPACE_SWITCH_2"`,
   `activateWorkspaceByIndex` and `WORKSPACES_INIT`.
5. Update this guide's version line and any changed findings in the same PR.

## Appendix A: `vivaldi.*` namespaces in the UI target

Live, 8.2.4133.84. Functions first, then events after `| events:`.

- `accessKeys`: `action`, `getAccessKeysForPage`
- `autoUpdate`: `checkForUpdates`, `disableUpdateNotifier`, `enableUpdateNotifier`, `getAboutInfo`, `getAboutPathsInfo`, `getAutoInstallUpdates`, `getLastCheckTime`, `getUpdateStatus`, `hasAutoUpdates`, `installUpdateAndRestart`, `isUpdateNotifierEnabled`, `needsCodecRestart`, `runStartupChecks`, `setAutoInstallUpdates`, `startUpdate` | events: `onDidAbortWithError`, `onDidDownloadUpdate`, `onDidFindValidUpdate`, `onNeedRestartToReloadCodecs`, `onUpdateFinished`, `onUpdateProgress`, `onUpdaterDidNotFindUpdate`, `onUpdaterDidRelaunchApplication`, `onUpdaterWillRelaunchApplication`, `onWillDownloadUpdate`, `onWillInstallUpdateOnQuit`
- `bookmarkContextMenu`: `close`, `show` | events: `onClose`, `onDragStart`, `onOpen`
- `bookmarksPrivate`: `emptyTrash`, `export`, `getFolderIds`, `isCustomThumbnail`, `updatePartners`, `updateSpeedDialsForWindowsJumplist` | events: `onFaviconChanged`, `onMetaInfoChanged`
- `calendar`: `create`, `createAccount`, `createEventException`, `createEventTemplate`, `createInvite`, `createNotification`, `delete`, `deleteAccount`, `deleteEvent`, `deleteEventException`, `deleteEventTemplate`, `deleteEventType`, `deleteInvite`, `deleteNotification`, `eventCreate`, `eventTypeCreate`, `eventTypeUpdate`, `eventsCreate`, `getAll`, `getAllAccounts`, `getAllEventTemplates`, `getAllEventTypes`, `getAllEvents`, `getAllNotifications`, `getParentExceptionId`, `update`, `updateAccount`, `updateEvent`, `updateEventTemplate`, `updateInvite`, `updateNotification`, `updateRecurrenceException` | events: `onCalendarDataChanged`, `onEventCreated`, `onIcsFileOpened`, `onMailtoOpened`, `onNotificationChanged`, `onWebcalUrlOpened`
- `contacts`: `addEmailAddress`, `addPropertyItem`, `create`, `createMany`, `delete`, `getAll`, `getAllEmailAddresses`, `readThunderbirdContacts`, `removeEmailAddress`, `removePropertyItem`, `update`, `updateEmailAddress`, `updatePropertyItem` | events: `onContactChanged`, `onContactCreated`, `onContactRemoved`
- `contentBlocking`: `addExceptionForDomain`, `addKnownSourceFromFile`, `addKnownSourceFromURL`, `clearAdBlockingStats`, `deleteKnownSource`, `disableSource`, `enableSource`, `fetchSourceNow`, `getActiveExceptionsList`, `getAdAttributionAllowedTrackers`, `getAdAttributionDomain`, `getAdBlockingStats`, `getAllExceptionLists`, `getBlockedUrlsInfo`, `getExceptions`, `getRuleSource`, `getRuleSources`, `isExemptByPartnerURL`, `isExemptOfFiltering`, `removeAllExceptions`, `removeExceptionForDomain`, `resetPresetSources`, `setActiveExceptionsList`, `setKnownSourceSettings` | events: `onAdAttributionDomainChanged`, `onAdAttributionTrackersAllowed`, `onExceptionsChanged`, `onRuleSourceAdded`, `onRuleSourceDisabled`, `onRuleSourceEnabled`, `onRuleSourceRemoved`, `onRuleSourceUpdated`, `onStateChanged`, `onUrlsBlocked`
- `contextMenu`: `show`, `update` | events: `onDocumentMenu`
- `devtoolsPrivate`: `closeDevtools`, `getDockingStateSizes`, `toggleDevtools` | events: `onActivateWindow`, `onClosed`, `onDevtoolsUndocked`, `onDockingSizesChanged`, `onDockingStateChanged`
- `directMatch`: `getForCategory`, `getPopularSites`, `hide`, `resetHidden` | events: `onPopularSitesReady`
- `dnsOverHttpsPrivate`: `configTest`, `dataFetcher`
- `editcommand`: `execute`
- `extensionActionUtils`: `executeExtensionAction`, `executeMenuAction`, `getExtensionMenu`, `getToolbarExtensions`, `removeExtension`, `showExtensionOptions`, `showGlobalError`, `triggerGlobalErrors` | events: `onAdded`, `onClearAllValuesForTab`, `onCommandAdded`, `onCommandRemoved`, `onExtensionDisabledInstallErrorAdded`, `onExtensionDisabledInstallErrorRemoved`, `onRemoved`, `onSidePanelActionRequested`, `onSidePanelOptionChanged`, `onUpdated`
- `historyPrivate`: `deleteVisits`, `getTopUrlsPerDay`, `updateTopSites`, `visitSearch` | events: `onVisitModified`
- `importData`: `closeThunderbirdMailbox`, `getProfiles`, `openThunderbirdMailbox`, `readMessageFromThunderbirdMailbox`, `startImport` | events: `onImportEnded`, `onImportItemEnded`, `onImportItemFailed`, `onImportItemStarted`, `onImportStarted`
- `infobars`: `sendButtonAction`, `showInfobar` | events: `onInfobarCreated`, `onInfobarRemoved`
- `mailPrivate`: `checkFolder`, `checkMailSearchDBHealth`, `createFileDirectory`, `createMessages`, `deleteMailSearchDB`, `deleteMessageFile`, `deleteMessages`, `getDBVersion`, `getFileDirectory`, `getFilePaths`, `getFullPath`, `getMailFilePaths`, `getMailSearchDBCount`, `getMailSearchDBIds`, `matchMessage`, `messageFileExists`, `openFolder`, `readFileToBuffer`, `readFileToText`, `readMessageFileToBuffer`, `renameMessageFile`, `searchMessages`, `startMigration`, `updateMessage`, `writeBufferToMessageFile`, `writeTextToMessageFile`, `writeVivaldiHeaders` | events: `onDeleteMessagesProgress`, `onUpgradeProgress`
- `menuContent`: `create`, `get`, `move`, `remove`, `removeAction`, `reset`, `resetAll`, `update` | events: `onChanged`, `onResetAll`
- `menubar`: `getHasWindows`, `setup` | events: `onActivated`
- `menubarMenu`: `getMaxId`, `show` | events: `onAction`, `onBookmarkAction`, `onClose`, `onError`, `onHover`, `onOpen`, `onOpenBookmark`
- `notes`: `beginImport`, `create`, `emptyTrash`, `endImport`, `get`, `getTree`, `move`, `remove`, `search`, `update` | events: `onChanged`, `onCreated`, `onImportBegan`, `onImportEnded`, `onMoved`, `onRemoved`
- `omniboxPrivate`: `addOrUpdateShortcut`, `deleteShortcut`, `startOmnibox` | events: `onOmniboxResultChanged`
- `pageActions`: `getScriptOverridesForTab`, `getScripts`, `setScriptOverrideForTab` | events: `onOverridesChanged`, `onScriptsChanged`
- `prefs`: `get`, `getForCache`, `getTranslateSettings`, `resetAllToDefault`, `resetTranslationPrefs`, `set`, `setLanguagePairToAlwaysTranslate`, `setLanguageToNeverTranslate`, `setSiteToNeverTranslate`, `setTranslationDeclined` | events: `onChanged`
- `pwa`: `install`, `launch` | events: `onInstallabilityChanged`
- `readingListPrivate`: `add`, `getAll`, `remove`, `setReadStatus` | events: `onModelChanged`
- `runtimePrivate`: `closeActiveProfile`, `closeGuestSession`, `createProfile`, `deleteProfile`, `exit`, `getAllFeatureFlags`, `getProfileDefaults`, `getProfileStatistics`, `getUserProfileImages`, `getUserProfiles`, `hasDesktopShortcut`, `hasGuestSession`, `isGuestSession`, `isProfileManaged`, `openNamedProfile`, `openProfileSelectionWindow`, `restart`, `switchToGuestSession`, `updateActiveProfile` | events: `onProfilesUpdated`
- `savedpasswords`: `add`, `authenticate`, `createDelegate`, `delete`, `get`, `getList`, `remove`
- `searchEngines`: `acknowledgeSwitchPrompt`, `addTemplateUrl`, `getKeywordForUrl`, `getSearchRequest`, `getSwitchPromptData`, `getTemplateUrls`, `moveTemplateUrl`, `removeTemplateUrl`, `repairPrepopulatedTemplateUrls`, `setDefault`, `setIsActive`, `updateTemplateUrl` | events: `onTemplateUrlsChanged`
- `sessionsPrivate`: `add`, `delete`, `emptyTrash`, `getAll`, `getAutosaveIds`, `getContent`, `makeContainer`, `modifyContent`, `move`, `open`, `rename`, `restoreLastClosed`, `restoreSyncTabs`, `update` | events: `onChanged`
- `settings`: `setContentSetting`
- `sitePermissions`: `getAllowedDevices`, `getAvailablePermissions`, `getDeviceGrantSites`, `getDeviceGrants`, `getOverriddenSites`, `getOverridesForPattern`, `getOverridesForSite`, `getSecurityInfo`, `getSiteData`, `resetSitePermissions`, `respondToPermissionRequest`, `revokeDeviceGrant`, `setSiteData`, `setSitePermission`, `showCertificateDialog`, `showSiteDataDialog` | events: `onDeviceChooserUpdate`, `onDeviceGrantChanged`, `onPermissionAccessed`, `onPermissionChanged`, `onPermissionCleared`, `onPermissionRequest`
- `sync`: `backupEncryptionToken`, `clearData`, `getDefaultSessionName`, `getEngineState`, `getLastCycleState`, `restoreEncryptionToken`, `setEncryptionPassword`, `setTypes`, `setupComplete` | events: `onCycleCompleted`, `onEngineStateChanged`
- `tabsPrivate`: `activateSpatnavElement`, `clone`, `closeSpatnavOrCurrentOpenMenu`, `determineTextLanguage`, `dismissSendTabToSelfEntries`, `execSendTabToSelfAction`, `get`, `getSendTabToSelfEntries`, `getSendTabToSelfTargets`, `getTabPerformanceData`, `hasBeforeUnloadOrUnload`, `insertText`, `loadViaLifeCycleUnit`, `move`, `moveSpatnavRect`, `notifyActiveWorkspace`, `notifyCollapse`, `revertTranslatePage`, `scrollPage`, `sendSendTabToSelfTarget`, `setGroupProperties`, `startDrag`, `translatePage`, `unstack`, `update` | events: `onBeforeUnloadDialogClosed`, `onDragEnd`, `onExtDataChanged`, `onIsPageTranslatedChanged`, `onKeyboardChanged`, `onKeyboardShortcut`, `onLanguageDetermined`, `onMediaStateChanged`, `onMouseChanged`, `onMouseGesture`, `onMouseGestureDetection`, `onPageTranslated`, `onPageZoom`, `onRockerGesture`, `onSendTabToSelfAdded`, `onSendTabToSelfDismissed`, `onShowTranslationUI`, `onTabResourceMetricsRefreshed`, `onTabSwitchEnd`, `onTabUpdated`, `onThemeColorChanged`, `onWebviewClickCheck`
- `themePrivate`: `download`, `export`, `getThemeData`, `import` | events: `onThemeDownloadCompleted`, `onThemeDownloadProgress`, `onThemeDownloadStarted`, `onThemesUpdated`
- `thumbnails`: `captureBookmark`, `captureTab`, `captureUI`
- `translateHistory`: `add`, `get`, `remove`, `reset` | events: `onAdded`, `onMoved`, `onRemoved`
- `utilities`: `acceptMixedDownload`, `acknowledgeCrashedSession`, `allowVPNIncognito`, `broadcastMessage`, `browserWindowReady`, `calculate`, `canOpenUrlExternally`, `canShowWhatsNewPage`, `cleanUnusedImages`, `clearAllRecentlyClosedSessions`, `clearCache`, `clearRecentlyClosedTabs`, `copyToClipboard`, `createQRCode`, `detectNewCrashes`, `downloadsDrag`, `emulateUserInput`, `exportSSLCertificates`, `focusDialog`, `generateQRCode`, `getAOLOAuthClientId`, `getAOLOAuthClientSecret`, `getBlockThirdPartyCookies`, `getCommandLineValue`, `getDefaultContentSettings`, `getEnvVars`, `getFOAuthClientId`, `getGAPIKey`, `getGOAuthClientId`, `getGOAuthClientSecret`, `getLanguage`, `getMOAuthClientId`, `getMediaAvailableState`, `getOSGeolocationState`, `getSSLCertificates`, `getSelectedText`, `getSharedData`, `getStartupAction`, `getSystemCountry`, `getSystemDateFormat`, `getUrlFragments`, `getVersion`, `getVivaldiNetOAuthClientId`, `getVivaldiNetOAuthClientSecret`, `getYOAuthClientId`, `getYOAuthClientSecret`, `hasCommandLineSwitch`, `importSSLCertificate`, `isDialogOpen`, `isDownloadManagerReady`, `isRTL`, `isRazerChromaAvailable`, `isRazerChromaReady`, `isTabInLastSession`, `isUrlValid`, `isVivaldiDefaultBrowser`, `isVivaldiPinnedToLaunchBar`, `launchNetworkSettings`, `openFolder`, `openOSGeolocationSettings`, `openPage`, `openPrivacyReportDialog`, `openTaskManager`, `osCrypt`, `osDecrypt`, `pinVivaldiToLaunchBar`, `print`, `readImage`, `releaseMutex`, `requestVivaldiSyncStatus`, `savePage`, `selectFile`, `selectLocalImage`, `setBlockThirdPartyCookies`, `setContentSettings`, `setDefaultContentSettings`, `setDialogPosition`, `setLanguage`, `setProtocolHandling`, `setRazerChromaColor`, `setSharedData`, `setStartupAction`, `setVivaldiAsDefaultBrowser`, `showAdditionalStartupPages`, `showManageSSLCertificates`, `showPasswordDialog`, `silentlyInstallExtension`, `startChromecast`, `storeImage`, `stripUrlTracking`, `takeMutex`, `translateText`, `updatePrimarySelection`, `urlToThumbnailText` | events: `onBroadcastMessage`, `onDialogCanceled`, `onDownloadManagerReady`, `onPasswordIconStatusChanged`, `onRazerChromaReady`, `onResume`, `onScroll`, `onSessionRecoveryDone`, `onSessionRecoveryStart`, `onSharedDataUpdated`, `onShowQRCode`, `onSuspend`, `onTopSitesChanged`, `onVivaldiSyncStatusUpdated`
- `vivaldiAccount`: `getState`, `login`, `logout` | events: `onAccountStateChanged`
- `windowPrivate`: `create`, `getCurrentId`, `getFocusedElementInfo`, `isOnScreenWithNotch`, `performHapticFeedback`, `setControlButtonsPosition`, `setHotSpot`, `setState`, `updateMaximizeButtonPosition` | events: `onActivated`, `onActiveTabStatusText`, `onBeforeUnloadDialogOpened`, `onFullscreenMenubarVisibilityChanged`, `onMouseCloseToEdge`, `onMouseInHotSpot`, `onPageInfoPopupChanged`, `onPositionChanged`, `onStateChanged`, `onToastMessage`, `onWebContentsHasWindow`, `onWindowClosed`, `onWindowDidChangeScreens`
- `zoom`: `getDefaultZoom`, `getVivaldiUIZoom`, `setDefaultZoom`, `setVivaldiUIZoom` | events: `onDefaultZoomChanged`, `onUIZoomChanged`

## Appendix B: `chrome.*` namespaces in the UI target

Live, 8.2.4133.84. Same format as Appendix A.

- `accessibilityFeatures`: (none)
- `alarms`: `clear`, `clearAll`, `create`, `get`, `getAll` | events: `onAlarm`
- `app`: (none)
- `autofillPrivate`: `addOrUpdateEntityInstance`, `addVirtualCard`, `authenticateUserAndFlipMandatoryAuthToggle`, `authenticateUserBeforeViewingEntityData`, `bulkDeleteAllCvcs`, `checkIfDeviceAuthAvailable`, `getAccountInfo`, `getAddressComponents`, `getAddressList`, `getAllAttributeTypesForEntityTypeName`, `getAutofillAiOptInStatus`, `getCountryList`, `getCreditCardList`, `getEntityInstanceByGuid`, `getIbanList`, `getLocalCard`, `getPayOverTimeIssuerList`, `getRequiredAttributeTypesForEntityTypeName`, `getWalletablePassDetectionOptInStatus`, `getWritableEntityTypes`, `isValidIban`, `loadEntityInstances`, `logServerCardLinkClicked`, `logServerIbanLinkClicked`, `removeAddress`, `removeEntityInstance`, `removePaymentsEntity`, `removeVirtualCard`, `saveAddress`, `saveCreditCard`, `saveIban`, `setAutofillAiOptInStatus`, `setWalletablePassDetectionOptInStatus`, `toggleAutofillAiReauthRequirement` | events: `onEntityInstancesChanged`, `onPersonalDataChanged`
- `bookmarks`: `create`, `get`, `getChildren`, `getRecent`, `getSubTree`, `getTree`, `move`, `remove`, `removeTree`, `search`, `update` | events: `onChanged`, `onChildrenReordered`, `onCreated`, `onImportBegan`, `onImportEnded`, `onMoved`, `onRemoved`
- `browsingData`: `remove`, `removeAppcache`, `removeCache`, `removeCacheStorage`, `removeCookies`, `removeDownloads`, `removeFileSystems`, `removeFormData`, `removeHistory`, `removeIndexedDB`, `removeLocalStorage`, `removePasswords`, `removePluginData`, `removeServiceWorkers`, `removeWebSQL`, `settings`
- `clipboard`: (none) | events: `onClipboardDataChanged`
- `commandLinePrivate`: `hasSwitch`
- `contentSettings`: (none)
- `contextMenus`: `create`, `remove`, `removeAll`, `update` | events: `onClicked`
- `cookies`: `get`, `getAll`, `getAllCookieStores`, `getPartitionKey`, `remove`, `set` | events: `onChanged`
- `dom`: `openOrClosedShadowRoot`
- `downloads`: `acceptDanger`, `cancel`, `download`, `erase`, `getFileIcon`, `open`, `pause`, `removeFile`, `resume`, `search`, `setShelfEnabled`, `setUiOptions`, `show`, `showDefaultFolder` | events: `onChanged`, `onCreated`, `onDeterminingFilename`, `onErased`
- `extension`: `getBackgroundPage`, `getExtensionTabs`, `getURL`, `getViews`, `isAllowedFileSchemeAccess`, `isAllowedIncognitoAccess`, `sendRequest`, `setUpdateUrlData` | events: `onRequest`, `onRequestExternal`
- `fileSystem`: `chooseEntry`, `chooseFile`, `getDisplayPath`, `getVolumeList`, `getWritableEntry`, `getWritableFileEntry`, `isRestorable`, `isWritableEntry`, `isWritableFileEntry`, `requestFileSystem`, `restoreEntry`, `retainEntry` | events: `onVolumeListChanged`
- `fontSettings`: `clearDefaultFixedFontSize`, `clearDefaultFontSize`, `clearFont`, `clearMinimumFontSize`, `getDefaultFixedFontSize`, `getDefaultFontSize`, `getFont`, `getFontList`, `getMinimumFontSize`, `setDefaultFixedFontSize`, `setDefaultFontSize`, `setFont`, `setMinimumFontSize` | events: `onDefaultFixedFontSizeChanged`, `onDefaultFontSizeChanged`, `onFontChanged`, `onMinimumFontSizeChanged`
- `history`: `addUrl`, `deleteAll`, `deleteRange`, `deleteUrl`, `getVisits`, `search` | events: `onVisitRemoved`, `onVisited`
- `i18n`: `detectLanguage`, `getAcceptLanguages`, `getMessage`, `getUILanguage`
- `identity`: `clearAllCachedAuthTokens`, `getAuthToken`, `getProfileUserInfo`, `getRedirectURL`, `launchWebAuthFlow`, `removeCachedAuthToken` | events: `onSignInChanged`
- `languageSettingsPrivate`: `addInputMethod`, `addSpellcheckWord`, `disableLanguage`, `enableLanguage`, `getAlwaysTranslateLanguages`, `getInputMethodLists`, `getLanguageList`, `getNeverTranslateLanguages`, `getSpellcheckDictionaryStatuses`, `getSpellcheckWords`, `getTranslateTargetLanguage`, `moveLanguage`, `removeInputMethod`, `removeSpellcheckWord`, `retryDownloadDictionary`, `setEnableTranslationForLanguage`, `setLanguageAlwaysTranslateState`, `setTranslateTargetLanguage` | events: `onCustomDictionaryChanged`, `onInputMethodAdded`, `onInputMethodRemoved`, `onSpellcheckDictionariesChanged`
- `management`: `createAppShortcut`, `generateAppForLink`, `get`, `getAll`, `getPermissionWarningsById`, `getPermissionWarningsByManifest`, `getSelf`, `launchApp`, `setEnabled`, `setLaunchType`, `uninstall`, `uninstallSelf` | events: `onDisabled`, `onEnabled`, `onInstalled`, `onUninstalled`
- `notifications`: `clear`, `create`, `getAll`, `getPermissionLevel`, `update` | events: `onButtonClicked`, `onClicked`, `onClosed`, `onPermissionLevelChanged`, `onShowSettings`
- `passwordsPrivate`: `addPassword`, `changeCredential`, `continueImport`, `disconnectCloudAuthenticator`, `exportPasswords`, `fetchFamilyMembers`, `getCredentialGroups`, `getCredentialsWithReusedPassword`, `getInsecureCredentials`, `getPasswordCheckStatus`, `getPasswordExceptionList`, `getSavedPasswordList`, `getUrlCollection`, `importPasswords`, `isConnectedToCloudAuthenticator`, `movePasswordsToAccount`, `muteInsecureCredential`, `recordPasswordsPageAccessInSettings`, `removeCredential`, `removePasswordException`, `requestCredentialsDetails`, `requestExportProgressStatus`, `requestPlaintextPassword`, `resetImporter`, `sharePassword`, `showExportedFileInShell`, `startPasswordCheck`, `undoRemoveSavedPasswordOrException`, `unmuteInsecureCredential` | events: `onAccountStorageActiveStateChanged`, `onInsecureCredentialsChanged`, `onPasswordCheckStatusChanged`, `onPasswordExceptionsListChanged`, `onPasswordManagerActionableErrorChanged`, `onPasswordManagerAuthTimeout`, `onPasswordsFileExportProgress`, `onSavedPasswordsListChanged`, `onShouldShowAccountStorageSettingToggleChanged`
- `permissions`: `addHostAccessRequest`, `contains`, `getAll`, `remove`, `removeHostAccessRequest`, `request` | events: `onAdded`, `onRemoved`
- `privacy`: (none)
- `proxy`: (none) | events: `onProxyError`
- `runtime`: `connect`, `getBackgroundPage`, `getContexts`, `getManifest`, `getPackageDirectoryEntry`, `getPlatformInfo`, `getURL`, `getVersion`, `openOptionsPage`, `reload`, `requestUpdateCheck`, `restart`, `restartAfterDelay`, `sendMessage`, `setUninstallURL` | events: `onBrowserUpdateAvailable`, `onConnect`, `onConnectExternal`, `onInstalled`, `onMessage`, `onMessageExternal`, `onRestartRequired`, `onStartup`, `onSuspend`, `onSuspendCanceled`, `onUpdateAvailable`, `onUserScriptConnect`, `onUserScriptMessage`
- `scripting`: `executeScript`, `getRegisteredContentScripts`, `insertCSS`, `registerContentScripts`, `removeCSS`, `unregisterContentScripts`, `updateContentScripts`
- `sessions`: `getDevices`, `getRecentlyClosed`, `restore` | events: `onChanged`
- `socket`: `accept`, `bind`, `connect`, `create`, `destroy`, `disconnect`, `getInfo`, `getJoinedGroups`, `getNetworkList`, `joinGroup`, `leaveGroup`, `listen`, `read`, `recvFrom`, `secure`, `sendTo`, `setKeepAlive`, `setMulticastLoopbackMode`, `setMulticastTimeToLive`, `setNoDelay`, `write`
- `storage`: (none) | events: `onChanged`
- `tabs`: `captureVisibleTab`, `connect`, `create`, `detectLanguage`, `discard`, `duplicate`, `get`, `getCurrent`, `getZoom`, `getZoomSettings`, `goBack`, `goForward`, `group`, `highlight`, `move`, `query`, `reload`, `remove`, `sendMessage`, `setZoom`, `setZoomSettings`, `ungroup`, `update` | events: `onActivated`, `onAttached`, `onCreated`, `onDetached`, `onHighlighted`, `onMoved`, `onRemoved`, `onReplaced`, `onUpdated`, `onZoomChange`
- `topSites`: `get`
- `webNavigation`: `getAllFrames`, `getFrame` | events: `onBeforeNavigate`, `onCommitted`, `onCompleted`, `onCreatedNavigationTarget`, `onDOMContentLoaded`, `onErrorOccurred`, `onHistoryStateUpdated`, `onReferenceFragmentUpdated`, `onTabReplaced`
- `webRequest`: `handlerBehaviorChanged` | events: `onActionIgnored`, `onAuthRequired`, `onBeforeRedirect`, `onBeforeRequest`, `onBeforeSendHeaders`, `onCompleted`, `onErrorOccurred`, `onHeadersReceived`, `onResponseStarted`, `onSendHeaders`
- `webViewRequest`: `AddRequestCookie`, `AddRequestCookieInstanceType`, `AddResponseCookie`, `AddResponseCookieInstanceType`, `AddResponseHeader`, `AddResponseHeaderInstanceType`, `CancelRequest`, `CancelRequestInstanceType`, `EditRequestCookie`, `EditRequestCookieInstanceType`, `EditResponseCookie`, `EditResponseCookieInstanceType`, `FilterResponseCookie`, `HeaderFilter`, `IgnoreRules`, `IgnoreRulesInstanceType`, `RedirectByRegEx`, `RedirectByRegExInstanceType`, `RedirectRequest`, `RedirectRequestInstanceType`, `RedirectToEmptyDocument`, `RedirectToEmptyDocumentInstanceType`, `RedirectToTransparentImage`, `RedirectToTransparentImageInstanceType`, `RemoveRequestCookie`, `RemoveRequestCookieInstanceType`, `RemoveRequestHeader`, `RemoveRequestHeaderInstanceType`, `RemoveResponseCookie`, `RemoveResponseCookieInstanceType`, `RemoveResponseHeader`, `RemoveResponseHeaderInstanceType`, `RequestCookie`, `RequestMatcher`, `RequestMatcherInstanceType`, `ResponseCookie`, `SendMessageToExtension`, `SendMessageToExtensionInstanceType`, `SetRequestHeader`, `SetRequestHeaderInstanceType`, `Stage`
- `windows`: `create`, `get`, `getAll`, `getCurrent`, `getLastFocused`, `remove`, `update` | events: `onBoundsChanged`, `onCreated`, `onFocusChanged`, `onRemoved`

## Appendix C: `COMMAND_*` names in `bundle.js`

Static, 8.2.4133.84. Grouped by the first word after `COMMAND_`. Names ending in `_` are prefixes
that the bundle tests with `startsWith`, not registered commands. 29 of these
strings are not registered commands (see `registered.txt` in Step 5).

- SHOW (50): `SHOW_ABOUT`, `SHOW_ALL`, `SHOW_BOOKMARK_BAR`, `SHOW_BOOKMARK_PANEL`, `SHOW_BOOKMARKS`, `SHOW_CALENDAR`, `SHOW_CALENDAR_PANEL`, `SHOW_CLEAR_PRIVATE_DATA`, `SHOW_CLOSED_TABS`, `SHOW_COMMUNITY`, `SHOW_CONTACTS_PANEL`, `SHOW_CONTRIBUTE`, `SHOW_DONATE`, `SHOW_DOWNLOADS_PANEL`, `SHOW_DOWNLOADS_POPOUT`, `SHOW_EXTENSIONS`, `SHOW_FEEDS_PANEL`, `SHOW_HELP`, `SHOW_HISTORY`, `SHOW_HISTORY_PANEL`, `SHOW_HOMEPAGE`, `SHOW_KEYBOARDSHORTCUTS`, `SHOW_MAIL`, `SHOW_MAIL_PANEL`, `SHOW_NEXT_PANEL`, `SHOW_NOTES`, `SHOW_NOTES_PANEL`, `SHOW_PAGE_ACCESS_KEYS`, `SHOW_PREVIOUS_PANEL`, `SHOW_PRIVACY_DASHBOARD`, `SHOW_QUICK_COMMANDS`, `SHOW_READING_LIST_PANEL`, `SHOW_SESSION_PANEL`, `SHOW_SETTINGS`, `SHOW_TAB_BUTTON_POPOUT`, `SHOW_TASKS_PANEL`, `SHOW_TRANSLATE_PANEL`, `SHOW_WEB_PANEL_`, `SHOW_WEB_PANEL_1`, `SHOW_WEB_PANEL_2`, `SHOW_WEB_PANEL_3`, `SHOW_WEB_PANEL_4`, `SHOW_WEB_PANEL_5`, `SHOW_WEB_PANEL_6`, `SHOW_WEB_PANEL_7`, `SHOW_WEB_PANEL_8`, `SHOW_WEB_PANEL_9`, `SHOW_WELCOME`, `SHOW_WINDOW_PANEL`, `SHOW_WORKSPACE_MENU`
- MAIL (38): `MAIL`, `MAIL_ADD_NEW_MAIL_ACCOUNT`, `MAIL_COMPOSE_NEW_MESSAGE`, `MAIL_COMPOSER_CHOOSE_ATTACHMENTS`, `MAIL_COMPOSER_DELETE_DRAFT`, `MAIL_COMPOSER_DOCK`, `MAIL_COMPOSER_UNDOCK`, `MAIL_DELETE_PERMANENTLY`, `MAIL_ENABLE_SENDER_VIEW`, `MAIL_ENABLE_THREADED_VIEW`, `MAIL_FORWARD`, `MAIL_GOTO_NEXT_UNREAD`, `MAIL_GOTO_PREVIOUS_UNREAD`, `MAIL_IS_A_MAILING_LIST`, `MAIL_LABEL_FLAG`, `MAIL_MARK_ALL_READ`, `MAIL_MARK_JUNK`, `MAIL_MARK_NOT_JUNK`, `MAIL_MARK_READ`, `MAIL_MARK_READ_AND_GOTO_NEXT_UNREAD`, `MAIL_MARK_THREAD_READ`, `MAIL_MARK_THREAD_UNREAD`, `MAIL_MARK_UNREAD`, `MAIL_MOVE_TO_ARCHIVE`, `MAIL_NOT_A_MAILING_LIST`, `MAIL_QUEUE_MESSAGE`, `MAIL_REPLY`, `MAIL_REPLY_ALL`, `MAIL_REPLY_LIST`, `MAIL_RESTORE_FROM_ARCHIVE`, `MAIL_SAVE_MESSAGES`, `MAIL_SEND_MESSAGE`, `MAIL_SHOW_HTML`, `MAIL_SHOW_MAIL_INFO`, `MAIL_SHOW_PLAINTEXT`, `MAIL_SHOW_QUICK_REPLY`, `MAIL_SHOW_SETTINGS`, `MAIL_TOGGLE_COMPOSE_FORMAT`
- TAB (37): `TAB_ACTION`, `TAB_DISABLE_ALL_RELOADS`, `TAB_INSTALL_PWA`, `TAB_MOVE_BACKWARD`, `TAB_MOVE_END`, `TAB_MOVE_FIRST`, `TAB_MOVE_FORWARD`, `TAB_PERIODIC_RELOAD`, `TAB_REOPEN_RECENTLY_CLOSED`, `TAB_STACK_CLOSE`, `TAB_STACK_CREATE`, `TAB_STACK_CREATE_BY_HOSTS`, `TAB_STACK_DISSOLVE`, `TAB_STACK_RELOAD`, `TAB_STACK_REMOVE`, `TAB_STACK_TILE_GRID`, `TAB_STACK_TILE_HORIZONTAL`, `TAB_STACK_TILE_VERTICAL`, `TAB_SWITCH_1`, `TAB_SWITCH_2`, `TAB_SWITCH_3`, `TAB_SWITCH_4`, `TAB_SWITCH_5`, `TAB_SWITCH_6`, `TAB_SWITCH_7`, `TAB_SWITCH_8`, `TAB_SWITCH_9`, `TAB_SWITCH_BACK_HISTORY`, `TAB_SWITCH_BACK_ORDER`, `TAB_SWITCH_BACK_SETTING`, `TAB_SWITCH_FORWARD_HISTORY`, `TAB_SWITCH_FORWARD_ORDER`, `TAB_SWITCH_FORWARD_SETTING`, `TAB_SWITCH_LAST`, `TAB_THUMBNAIL`, `TAB_TRANSLATE_PAGE`, `TAB_VIEW_PAGE_SOURCE`
- PAGE (26): `PAGE_BACK`, `PAGE_CLEAR_CACHE_AND_FORCE_RELOAD`, `PAGE_COPY_ALL_URLS`, `PAGE_COPY_URL`, `PAGE_COPY_URL_FILTERED`, `PAGE_DISABLE_KEYBOARD_SHORTCUTS`, `PAGE_FAST_FORWARD`, `PAGE_FORWARD`, `PAGE_MUTE_ALL`, `PAGE_MUTE_OTHER`, `PAGE_QR_CODE`, `PAGE_REFRESH`, `PAGE_RELOAD_NOCACHE`, `PAGE_REWIND`, `PAGE_SCROLL_BOTTOM`, `PAGE_SCROLL_DOWN`, `PAGE_SCROLL_TOP`, `PAGE_SCROLL_UP`, `PAGE_SELECTION_CLEAR`, `PAGE_SELECTION_CURRENT`, `PAGE_SELECTION_EXPAND_NEXT`, `PAGE_SELECTION_EXPAND_PREVIOUS`, `PAGE_SELECTION_TOGGLE_RELATED`, `PAGE_TOGGLE_MUTE`, `PAGE_UNMUTE_ALL`, `PAGE_UNMUTE_OTHER`
- WORKSPACE (26): `WORKSPACE_ACTION`, `WORKSPACE_CREATE_NEW`, `WORKSPACE_MOVE_TABS_TO_`, `WORKSPACE_MOVE_TABS_TO_0`, `WORKSPACE_MOVE_TABS_TO_1`, `WORKSPACE_MOVE_TABS_TO_2`, `WORKSPACE_MOVE_TABS_TO_3`, `WORKSPACE_MOVE_TABS_TO_4`, `WORKSPACE_MOVE_TABS_TO_5`, `WORKSPACE_MOVE_TABS_TO_6`, `WORKSPACE_MOVE_TABS_TO_7`, `WORKSPACE_MOVE_TABS_TO_8`, `WORKSPACE_MOVE_TABS_TO_9`, `WORKSPACE_SWITCH_`, `WORKSPACE_SWITCH_1`, `WORKSPACE_SWITCH_10`, `WORKSPACE_SWITCH_2`, `WORKSPACE_SWITCH_3`, `WORKSPACE_SWITCH_4`, `WORKSPACE_SWITCH_5`, `WORKSPACE_SWITCH_6`, `WORKSPACE_SWITCH_7`, `WORKSPACE_SWITCH_8`, `WORKSPACE_SWITCH_9`, `WORKSPACE_SWITCH_BACK_ORDER`, `WORKSPACE_SWITCH_FORWARD_ORDER`
- TOGGLE (23): `TOGGLE_APPLE_EVENTS`, `TOGGLE_AUTO_HIDE_ADDRESS_BAR`, `TOGGLE_AUTO_HIDE_BOOKMARK_BAR`, `TOGGLE_AUTO_HIDE_BOTTOM`, `TOGGLE_AUTO_HIDE_LEFT`, `TOGGLE_AUTO_HIDE_PANEL`, `TOGGLE_AUTO_HIDE_RIGHT`, `TOGGLE_AUTO_HIDE_STATUS_BAR`, `TOGGLE_AUTO_HIDE_TAB_BAR`, `TOGGLE_AUTO_HIDE_TOP`, `TOGGLE_CARET_BROWSING`, `TOGGLE_CURRENT_PANEL`, `TOGGLE_FLOATING_PANEL`, `TOGGLE_FOOTER`, `TOGGLE_FORCE_DARK_MODE`, `TOGGLE_IMAGES`, `TOGGLE_INTERFACE_COLOR`, `TOGGLE_INTERFACE_COLOR_BY_NAME`, `TOGGLE_MENU_POSITION`, `TOGGLE_MOUSE_GESTURES`, `TOGGLE_PANEL`, `TOGGLE_STARTPAGE_NAVIGATION`, `TOGGLE_WARN_ON_QUIT`
- CALENDAR (16): `CALENDAR`, `CALENDAR_CREATE_EVENT`, `CALENDAR_GOTO_DATE`, `CALENDAR_REFRESH`, `CALENDAR_SEARCH`, `CALENDAR_VIEW_NEXT_PERIOD`, `CALENDAR_VIEW_PREVIOUS_PERIOD`, `CALENDAR_VIEW_TODAY`, `CALENDAR_VIEW_ZOOM_IN`, `CALENDAR_VIEW_ZOOM_OUT`, `CALENDAR_VIEWMODE_AGENDA`, `CALENDAR_VIEWMODE_DAY`, `CALENDAR_VIEWMODE_MONTH`, `CALENDAR_VIEWMODE_MULTIWEEK`, `CALENDAR_VIEWMODE_WEEK`, `CALENDAR_VIEWMODE_YEAR`
- MAIN (16): `MAIN_TOGGLE_ADDRESS_BAR`, `MAIN_TOGGLE_MAIL_BAR`, `MAIN_TOGGLE_PANEL_TOGGLE`, `MAIN_TOGGLE_TAB_BAR`, `MAIN_TOGGLE_UI`, `MAIN_TOGGLE_UI_AUTOHIDE`, `MAIN_UI_ZOOM`, `MAIN_UI_ZOOM_IN`, `MAIN_UI_ZOOM_OUT`, `MAIN_UI_ZOOM_RESET`, `MAIN_ZOOM`, `MAIN_ZOOM_DOUBLE`, `MAIN_ZOOM_HALF`, `MAIN_ZOOM_IN`, `MAIN_ZOOM_OUT`, `MAIN_ZOOM_RESET`
- CLIPBOARD (10): `CLIPBOARD_COPY`, `CLIPBOARD_COPY_FILTERED`, `CLIPBOARD_CUT`, `CLIPBOARD_PASTE`, `CLIPBOARD_PASTE_AS_NOTE`, `CLIPBOARD_PASTE_AS_PLAIN_TEXT`, `CLIPBOARD_PASTE_AS_PLAIN_TEXT_OR_PASTE_AND_GO`, `CLIPBOARD_REDO`, `CLIPBOARD_SELECT_ALL`, `CLIPBOARD_UNDO`
- FOCUS (10): `FOCUS_ADDRESSFIELD`, `FOCUS_BOOKMARKBAR`, `FOCUS_MAINMENU`, `FOCUS_NEXT`, `FOCUS_PANEL`, `FOCUS_PANELBAR`, `FOCUS_PREVIOUS`, `FOCUS_SEARCHFIELD`, `FOCUS_TABBAR`, `FOCUS_WEBVIEW`
- OPEN (9): `OPEN_IN_NEW_PRIVATE_WINDOW`, `OPEN_IN_NEW_WINDOW`, `OPEN_LINK`, `OPEN_LINK_BACKGROUND`, `OPEN_LINK_CURRENT`, `OPEN_LINK_DEFAULT`, `OPEN_LINK_IN_TILED_TAB`, `OPEN_PAGE`, `OPEN_SESSION`
- ADD (8): `ADD_BOOKMARK`, `ADD_CALENDAR_EVENT`, `ADD_CALENDAR_EVENT_WITH_INVITE`, `ADD_CALENDAR_ITEM`, `ADD_CALENDAR_TASK`, `ADD_NEW_CALENDAR_ACCOUNT`, `ADD_TO_READING_LIST`, `ADD_TO_WEB_PANEL`
- NEW (8): `NEW_BACKGROUND_TAB`, `NEW_BACKGROUND_TAB_LINK`, `NEW_GUEST_WINDOW`, `NEW_PRIVATE_WINDOW`, `NEW_TAB`, `NEW_TAB_LINK`, `NEW_TAB_OUTSIDE_GROUP`, `NEW_WINDOW`
- SET (7): `SET_ANIMATIONS_LOOP`, `SET_ANIMATIONS_NEVER`, `SET_ANIMATIONS_ONCE`, `SET_LOAD_IMAGES_ALWAYS`, `SET_LOAD_IMAGES_CACHE`, `SET_LOAD_IMAGES_NEVER`, `SET_NAMED_MENU`
- CLOSE (5): `CLOSE_ALL_BUT_ACTIVE_TAB`, `CLOSE_TAB`, `CLOSE_TAB_TO_LEFT`, `CLOSE_TAB_TO_RIGHT`, `CLOSE_WINDOW`
- EXPORT (5): `EXPORT_DATA`, `EXPORT_FEEDS`, `EXPORT_NOTES`, `EXPORT_PASSWORDS`, `EXPORT_READINGLIST`
- CAPTURE (4): `CAPTURE_AREA_TO_CLIPBOARD`, `CAPTURE_AREA_TO_DISK`, `CAPTURE_PAGE_TO_CLIPBOARD`, `CAPTURE_PAGE_TO_DISK`
- POSITION (4): `POSITION_TAB_BOTTOM`, `POSITION_TAB_LEFT`, `POSITION_TAB_RIGHT`, `POSITION_TAB_TOP`
- SPATNAV (4): `SPATNAV_DOWN`, `SPATNAV_LEFT`, `SPATNAV_RIGHT`, `SPATNAV_UP`
- FIND (3): `FIND_IN_PAGE`, `FIND_NEXT_IN_PAGE`, `FIND_PREVIOUS_IN_PAGE`
- IMPORT (3): `IMPORT_DATA`, `IMPORT_NOTES`, `IMPORT_READINGLIST`
- SAVE (3): `SAVE_PAGE`, `SAVE_SELECTED_SESSION`, `SAVE_SESSION`
- BLOCK (2): `BLOCK_TRACKING`, `BLOCK_TRACKING_AND_ADS`
- CUSTOMIZE (2): `CUSTOMIZE_PANELS`, `CUSTOMIZE_TOOLBAR`
- DEVTOOLS (2): `DEVTOOLS_CONSOLE`, `DEVTOOLS_INSPECTOR`
- HIBERNATE (2): `HIBERNATE_INACTIVE_WORKSPACES`, `HIBERNATE_OTHER_TABS`
- HIDE (2): `HIDE_OTHERS`, `HIDE_VIVALDI`
- MAC (2): `MAC_ALL_WINDOWS_TO_FRONT`, `MAC_ZOOM`
- RENAME (2): `RENAME_TAB`, `RENAME_TAB_STACK`
- SEARCH (2): `SEARCH_SELECTION_WITH_CUSTOM_ENGINE`, `SEARCH_WITH_SELECTION`
- WINDOW (2): `WINDOW_MINIMIZE`, `WINDOW_MINIMIZE_ALL`
- Other (35): `APPEARANCE`, `APPEND_SELECTION_TO_NOTE`, `APPLICATION`, `BOOKMARK_SELECTED_TABS`, `BREAKMODE_TOGGLE`, `CHAIN`, `CHAINED_SLEEP`, `CHECK_FOR_UPDATES`, `CLONE_TAB`, `COPY_SELECTION_TO_NOTE`, `DEFAULT_MAIN_ZOOM`, `DELETE`, `DEVELOPER_TOOLS`, `DISBAND_TILE_GROUP`, `EMAIL_LINK_OVERRIDE`, `EXIT`, `FULLSCREEN`, `GO_TO_PARENT_DIRECTORY`, `INITIALIZE`, `MANAGE_PEOPLE`, `MOVE_TAB_TO_NEW_WINDOW`, `PIN_TAB`, `PRINT_PAGE`, `QUIT_MAC_MAYBE_WARN`, `READERVIEW_TOGGLE`, `REMOVE_COMMAND`, `REPORT_BUG`, `RESET`, `SHARE_VIVALDI`, `START_CHROMECAST`, `STOP_PAGE`, `TASK_MANAGER`, `TRANSLATE_SELECTION`, `UPDATE_COMMAND`, `WEBPAGE_NAVIGATION`

## Appendix D: preference groups in `prefs_definitions.json`

Static, 8.2.4133.84. Leaf counts for each `vivaldi.*` group (622 leaves in total):

`mail` 83, `tabs` 68, `address_bar` 53, `calendar` 49, `panels` 40, `startpage` 27, `startup` 21, `webpages` 21, `bookmarks` 19, `quick_commands` 18, `biscuit` 14, `notes` 13, `privacy` 13, `system` 12, `themes` 9, `toolbars` 9, `clock` 9, `keyboard` 8, `theme` 8, `auto_hide` 8, `downloads` 7, `mouse_gestures` 7, `sessions` 7, `settings` 7, `appearance` 7, `workspaces` 6, `dashboard` 6, `geolocation` 6, `vivaldi_account` 5, `hue` 4, `rss` 4, `features` 3, `reading_list` 3, `razer_chroma` 3, `menu` 3, `chained_commands` 3, `sync` 3, `windows` 3, `clear_private_data` 2, `contact` 2, `mouse_wheel` 2, `page` 2, `status_bar` 2, `translate` 2, `welcome` 2, `oauth` 2, `layouts` 2, `actions` 1, `show_extensions_banner` 1, `context_dialogs` 1, `dot_net` 1, `homepage` 1, `homepage_cache` 1, `history` 1, `incognito` 1, `list` 1, `popups` 1, `plugins` 1, `toolbar_button` 1, `panel_editor` 1, `direct_match` 1, `policy` 1
