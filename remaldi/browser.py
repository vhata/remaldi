import asyncio
import contextlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable

from .errors import ControlError
from .protocol import JsonObject
from .transport import CDPConnection

UI_SUFFIX = "mpognobbkildjkofajifpdfhcoklimli/main.html"
EVENT_SETUP_TIMEOUT = 2
# Each profile context has its own main.html, and a Private window adds an incognito
# one whose chrome.windows only sees incognito windows. Order in /json/list is not
# stable, so a candidate is classified before it is chosen.
INCOGNITO_PROBE = "chrome.extension.inIncognitoContext"
INCOGNITO_PROBE_TIMEOUT = 2

# Hooks survive in the UI document across service restarts, so a changed hook set bumps
# the version and replaces listeners installed by an earlier one. Each listener is
# recorded before it is added and added in its own try, so one failing addListener
# neither stops the rest nor leaves unrecorded listeners behind; the result counts the
# listeners actually added.
# vivaldi.prefs.onChanged listeners receive (path, {value, defaultValue, store}) with the
# full dotted preference path; this is how Vivaldi 8.2's own preference cache reads it
# (static reading, see docs/VIVALDI_CONTROL_SURFACE.md "Events").
EVENT_HOOKS = """(() => {
 const key = '__remaldiEventHooks';
 const version = 2;
 const previous = globalThis[key];
 if (previous?.version === version) return previous.added;
 for (const [event, listener] of (Array.isArray(previous) ? previous : previous?.installed ?? [])) {
   try { event.removeListener(listener); } catch {}
 }
 const notify = () => { if (typeof globalThis.__remaldiChanged === 'function') globalThis.__remaldiChanged('dirty'); };
 const prefChanged = path => { if (path === 'vivaldi.workspaces.list') notify(); };
 const viv = typeof vivaldi === 'undefined' ? null : vivaldi;
 const hooks = {version, installed:[], added:0};
 globalThis[key] = hooks;
 const groups = [
   [chrome.tabs, ['onCreated','onRemoved','onUpdated','onMoved','onActivated','onAttached','onDetached'], notify],
   [chrome.windows, ['onCreated','onRemoved','onFocusChanged'], notify],
   [viv?.prefs, ['onChanged'], prefChanged],
   [viv?.tabsPrivate, ['onExtDataChanged'], notify]
 ];
 for (const [api, names, listener] of groups) for (const name of names) {
   const event = api?.[name];
   if (typeof event?.addListener !== 'function') continue;
   hooks.installed.push([event, listener]);
   try { event.addListener(listener); hooks.added += 1; } catch {}
 }
 return hooks.added;
})()"""


class Browser:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.targets: list[JsonObject] = []
        self.connections: dict[str, CDPConnection] = {}
        self.state = "endpoint_unavailable"
        self.detail = "Not connected yet."
        self.generation = 0
        self.on_change: Callable[[], None] = lambda: None
        self.lock = asyncio.Lock()
        self.event_support = "unavailable"
        self.ui_target_id: str | None = None
        self.incognito: dict[tuple[str, str], bool] = {}

    def _discover(self) -> list[JsonObject]:
        # Local discovery must not inherit HTTP proxy configuration.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.endpoint + "/json/list", timeout=2) as response:
            targets = json.load(response)
        if not isinstance(targets, list):
            raise ValueError("Debugger returned a non-list target document")
        return targets

    async def refresh(self) -> None:
        async with self.lock:
            try:
                targets = await asyncio.to_thread(self._discover)
                self.targets = targets
                by_id = {target["id"]: target for target in targets}
                for identifier, connection in list(self.connections.items()):
                    target = by_id.get(identifier)
                    if (
                        not connection.connected
                        or not target
                        or target.get("webSocketDebuggerUrl") != connection.url
                    ):
                        await connection.close()
                        del self.connections[identifier]
                        self.generation += 1
                        self.on_change()
                ui = await self._select_ui(targets)
                if ui is None:
                    self.ui_target_id = None
                    self.state = "ui_target_unavailable"
                    self.detail = "Debugger responds, but Vivaldi UI target is unavailable."
                    return
                self.ui_target_id = ui["id"]
                await self._connection(ui)
                self.state, self.detail = "connected", "Vivaldi UI connected."
            except Exception as exc:
                self.state = (
                    "endpoint_rejected"
                    if isinstance(exc, urllib.error.HTTPError)
                    else "endpoint_unavailable"
                )
                self.detail = str(exc)
                await self.close()

    async def _select_ui(self, targets: list[JsonObject]) -> JsonObject | None:
        """Return the regular profile's UI target, skipping incognito contexts."""
        candidates = [target for target in targets if UI_SUFFIX in target.get("url", "")]
        if len(candidates) <= 1:
            return candidates[0] if candidates else None
        keys = {(target["id"], target.get("webSocketDebuggerUrl", "")) for target in candidates}
        self.incognito = {key: value for key, value in self.incognito.items() if key in keys}
        for target in candidates:
            key = (target["id"], target.get("webSocketDebuggerUrl", ""))
            incognito = self.incognito.get(key)
            if incognito is None:
                # A failed probe is not cached, so the next refresh retries it.
                incognito = await self._probe_incognito(target)
                if incognito is not None:
                    self.incognito[key] = incognito
            if incognito is False:
                return target
        return None

    async def _probe_incognito(self, target: JsonObject) -> bool | None:
        """Classify a UI target on a short-lived connection without installing hooks."""
        url = target.get("webSocketDebuggerUrl")
        if not url:
            return None
        connection = CDPConnection(url, timeout=INCOGNITO_PROBE_TIMEOUT)
        try:
            await connection.connect()
            result = await connection.request(
                "Runtime.evaluate", {"expression": INCOGNITO_PROBE, "returnByValue": True}
            )
        except Exception:
            return None
        finally:
            with contextlib.suppress(Exception):
                await connection.close()
        value = result.get("result", {}).get("value")
        return value if isinstance(value, bool) else None

    async def _connection(self, target: JsonObject) -> CDPConnection:
        identifier = target["id"]
        connection = self.connections.get(identifier)
        if connection is None:
            url = target.get("webSocketDebuggerUrl")
            if not url:
                raise ControlError("target_unavailable", "Target has no debugger WebSocket.")
            connection = CDPConnection(url)
            try:
                await connection.connect()
            except Exception as exc:
                raise ControlError(
                    "target_connection_failed",
                    "Could not connect to the debugger target.",
                    target=identifier,
                    reason=str(exc),
                ) from exc
            connection.on_event = lambda event: self.on_change()
            self.connections[identifier] = connection
            self.generation += 1
            self.on_change()
            if identifier == self.ui_target_id:
                try:
                    async with asyncio.timeout(EVENT_SETUP_TIMEOUT):
                        await connection.request("Runtime.enable")
                        await connection.request("Runtime.addBinding", {"name": "__remaldiChanged"})
                        result = await connection.request(
                            "Runtime.evaluate",
                            {"expression": EVENT_HOOKS, "returnByValue": True},
                        )
                        self.event_support = (
                            "subscribed" if result.get("result", {}).get("value", 0) else "ttl_only"
                        )
                except (ControlError, TimeoutError):
                    self.event_support = "ttl_only"
        return connection

    async def request(
        self, method: str, params: JsonObject | None = None, target: str | None = None
    ) -> JsonObject:
        if self.detail == "Not connected yet.":
            await self.refresh()
        async with self.lock:
            selected = next(
                (
                    item
                    for item in self.targets
                    if item.get("id") == (target if target else self.ui_target_id)
                ),
                None,
            )
            if selected is None:
                if target is not None:
                    raise ControlError(
                        "target_unavailable",
                        "Requested debugger target is not available.",
                        target=target,
                    )
                raise ControlError(self.state, self.detail)
            connection = self.connections.get(selected["id"])
            if connection is not None and not connection.connected:
                raise ControlError(
                    "disconnected", "Browser connection lost; reconnection is pending."
                )
            connection = await self._connection(selected)
        return await connection.request(method, params)

    async def close(self) -> None:
        self.event_support = "unavailable"
        if self.connections:
            connections, self.connections = self.connections, {}
            self.generation += 1
            self.on_change()
            await asyncio.gather(
                *(item.close() for item in connections.values()), return_exceptions=True
            )
        self.targets = []
        self.ui_target_id = None

    async def monitor(self) -> None:
        delay = 0.25
        while True:
            await self.refresh()
            delay = 1 if self.state == "connected" else min(delay * 2, 10)
            await asyncio.sleep(delay)
