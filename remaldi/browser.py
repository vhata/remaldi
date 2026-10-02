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

EVENT_HOOKS = """(() => {
 const key = '__remaldiEventHooks';
 if (globalThis[key]) return globalThis[key].length;
 const notify = () => { if (typeof globalThis.__remaldiChanged === 'function') globalThis.__remaldiChanged('dirty'); };
 const installed = [];
 const groups = [
   [chrome.tabs, ['onCreated','onRemoved','onUpdated','onMoved','onActivated','onAttached','onDetached']],
   [chrome.windows, ['onCreated','onRemoved','onFocusChanged']],
   [typeof vivaldi === 'undefined' ? null : vivaldi.workspaces, ['onCreated','onRemoved','onChanged','onActivated']]
 ];
 for (const [api, names] of groups) for (const name of names) {
   if (typeof api?.[name]?.addListener === 'function') { api[name].addListener(notify); installed.push([api[name], notify]); }
 }
 globalThis[key] = installed;
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
