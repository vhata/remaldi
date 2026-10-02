"""Vivaldi-specific operations, isolated from daemon and CDP machinery."""

import asyncio
import json
import time
from typing import Any, Protocol

from .errors import ControlError
from .protocol import JsonObject

SNAPSHOT = """(async () => {
 const windows = await new Promise((resolve, reject) => chrome.windows.getAll({populate:true}, value => {
   if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message)); else resolve(value);
 }));
 const workspacesSupported = typeof vivaldi !== 'undefined' && typeof vivaldi.workspaces?.getAll === 'function';
 const switchSupported = typeof vivaldi !== 'undefined' && typeof vivaldi.menubar?.onActivated?.dispatch === 'function';
 const workspaces = workspacesSupported ? await new Promise((resolve, reject) => vivaldi.workspaces.getAll(value => {
   if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message)); else resolve(value);
 })) : null;
 return {windows, workspaces, capabilities:{windows:true, tabs:true, workspaces:workspacesSupported, workspace_switch:switchSupported}};
})()"""


class Controller(Protocol):
    generation: int

    async def request(
        self, method: str, params: JsonObject | None = None, target: str | None = None
    ) -> JsonObject: ...


class VivaldiAdapter:
    def __init__(self, controller: Controller, ttl: float = 5) -> None:
        self.controller = controller
        self.ttl = ttl
        self.cached: JsonObject | None = None
        self.updated = 0.0
        self.revision = 0
        self.cached_revision = -1
        self.generation = -1
        self.refresh_lock = asyncio.Lock()
        self.mutation_lock = asyncio.Lock()
        self.refresh_sequence = 0

    def invalidate(self) -> None:
        self.revision += 1

    async def evaluate(self, expression: str) -> Any:
        response = await self.controller.request(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        if "exceptionDetails" in response:
            raise ControlError(
                "browser_exception",
                "Browser evaluation failed.",
                exception=response["exceptionDetails"],
            )
        result = response.get("result", {})
        if "value" not in result:
            raise ControlError("unsupported_result", "Browser did not return a JSON value.")
        return result["value"]

    async def snapshot(self, refresh: bool = False) -> JsonObject:
        sequence = self.refresh_sequence
        async with self.refresh_lock:
            generation = self.controller.generation
            if (
                (refresh and sequence == self.refresh_sequence)
                or self.cached is None
                or self.cached_revision != self.revision
                or generation != self.generation
                or time.monotonic() - self.updated > self.ttl
            ):
                revision = self.revision
                value = await self.evaluate(SNAPSHOT)
                if not isinstance(value, dict) or not isinstance(value.get("capabilities"), dict):
                    raise ControlError("unsupported_result", "Unexpected browser state shape.")
                self.cached = value
                self.cached_revision = revision
                self.generation = generation
                self.updated = time.monotonic()
                self.refresh_sequence += 1
            return self.cached

    async def switch_workspace(self, workspace_id: object, window_id: object = None) -> Any:
        if (
            not isinstance(workspace_id, (str, int))
            or isinstance(workspace_id, bool)
            or not str(workspace_id).isdigit()
        ):
            raise ControlError(
                "invalid_parameters", "workspace_id must be a nonnegative decimal ID."
            )
        async with self.mutation_lock:
            state = await self.snapshot()
            if not state["capabilities"].get("workspace_switch"):
                raise ControlError(
                    "unsupported_operation",
                    "This Vivaldi UI does not expose workspace switching.",
                )
            windows = state.get("windows", [])
            if window_id is None:
                focused = [window for window in windows if window.get("focused")]
                if len(focused) != 1:
                    raise ControlError(
                        "ambiguous_window",
                        "Specify window_id when no unique focused window exists.",
                    )
                window_id = focused[0]["id"]
            if (
                not isinstance(window_id, int)
                or isinstance(window_id, bool)
                or not any(window.get("id") == window_id for window in windows)
            ):
                raise ControlError(
                    "invalid_parameters",
                    "window_id must identify a current browser window.",
                )
            command = "COMMAND_WORKSPACE_SWITCH_" + str(workspace_id)
            expression = f"(() => {{ vivaldi.menubar.onActivated.dispatch({window_id}, {json.dumps(command)}, ''); return {{dispatched:true}}; }})()"
            try:
                return await self.evaluate(expression)
            finally:
                self.invalidate()
