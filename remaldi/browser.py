import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Callable

from .errors import ControlError
from .protocol import JsonObject
from .transport import CDPConnection

UI_SUFFIX = "mpognobbkildjkofajifpdfhcoklimli/main.html"
EVENT_SETUP_TIMEOUT = 2

# Hooks survive in the UI document across service restarts, so a changed hook set bumps
# the version and replaces listeners installed by an earlier one.
# The vivaldi.prefs.onChanged argument shape has not been observed. The filter accepts a
# path string, or an object (or array of objects) with a string path or key, and
# invalidates on any shape it does not recognise.
EVENT_HOOKS = """(() => {
 const key = '__remaldiEventHooks';
 const version = 2;
 const previous = globalThis[key];
 if (previous?.version === version) return previous.installed.length;
 for (const [event, listener] of (Array.isArray(previous) ? previous : previous?.installed ?? [])) {
   try { event.removeListener(listener); } catch {}
 }
 const notify = () => { if (typeof globalThis.__remaldiChanged === 'function') globalThis.__remaldiChanged('dirty'); };
 const workspacesPath = 'vivaldi.workspaces.list';
 const prefPath = item => typeof item === 'string' ? item
   : typeof item?.path === 'string' ? item.path
   : typeof item?.key === 'string' ? item.key : null;
 const related = path => path === workspacesPath || path.startsWith(workspacesPath + '.') || workspacesPath.startsWith(path + '.');
 const prefChanged = change => {
   const paths = (Array.isArray(change) ? change : [change]).map(prefPath);
   if (paths.length === 0 || paths.includes(null) || paths.some(related)) notify();
 };
 const viv = typeof vivaldi === 'undefined' ? null : vivaldi;
 const installed = [];
 const groups = [
   [chrome.tabs, ['onCreated','onRemoved','onUpdated','onMoved','onActivated','onAttached','onDetached'], notify],
   [chrome.windows, ['onCreated','onRemoved','onFocusChanged'], notify],
   [viv?.prefs, ['onChanged'], prefChanged],
   [viv?.tabsPrivate, ['onExtDataChanged'], notify]
 ];
 for (const [api, names, listener] of groups) for (const name of names) {
   if (typeof api?.[name]?.addListener === 'function') { api[name].addListener(listener); installed.push([api[name], listener]); }
 }
 globalThis[key] = {version, installed};
 return installed.length;
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
                ui = next(
                    (target for target in targets if UI_SUFFIX in target.get("url", "")),
                    None,
                )
                if ui is None:
                    self.state = "ui_target_unavailable"
                    self.detail = "Debugger responds, but Vivaldi UI target is unavailable."
                    return
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
            if UI_SUFFIX in target.get("url", ""):
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
                    if (item.get("id") == target if target else UI_SUFFIX in item.get("url", ""))
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

    async def monitor(self) -> None:
        delay = 0.25
        while True:
            await self.refresh()
            delay = 1 if self.state == "connected" else min(delay * 2, 10)
            await asyncio.sleep(delay)
