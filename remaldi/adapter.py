"""Vivaldi-specific operations, isolated from daemon and CDP machinery."""

import asyncio
import json
import time
from typing import Any, Protocol

from .errors import ControlError
from .protocol import JsonObject

MAX_SAFE_INTEGER = 2**53 - 1

# The browser side only collects raw values; normalize_snapshot shapes and validates them.
SNAPSHOT = """(async () => {
 const windows = await new Promise((resolve, reject) => chrome.windows.getAll({populate:true}, value => {
   if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message)); else resolve(value);
 }));
 const switchSupported = typeof vivaldi !== 'undefined' && typeof vivaldi.menubar?.onActivated?.dispatch === 'function';
 const prefsSupported = typeof vivaldi !== 'undefined' && typeof vivaldi.prefs?.get === 'function';
 const workspacePreference = prefsSupported ? await new Promise(resolve => {
   try {
     vivaldi.prefs.get('vivaldi.workspaces.list', value => {
       const error = chrome.runtime.lastError;
       resolve(error ? {error:String(error.message ?? error)} : {result:value ?? null});
     });
   } catch (error) { resolve({error:String(error?.message ?? error)}); }
 }) : null;
 return {windows, workspace_preference:workspacePreference, capabilities:{windows:true, tabs:true, workspace_switch:switchSupported}};
})()"""

# Checks and dispatch run in one evaluation, so the workspace list and window
# state are read immediately before dispatching. JS_LOCAL_ACTIVATE_WORKSPACE is
# the action Vivaldi's native Window menu sends; it takes the internal ID as a
# string. Vivaldi creates a tab tagged with an ID it does not know and ignores
# dispatches to a minimized window, so both are rejected first.
SWITCH_WORKSPACE = """(async () => {
 const workspaceId = __WORKSPACE_ID__;
 const windowId = __WINDOW_ID__;
 const workspaces = await new Promise(resolve => {
   if (typeof vivaldi === 'undefined' || typeof vivaldi.prefs?.get !== 'function') { resolve(null); return; }
   vivaldi.prefs.get('vivaldi.workspaces.list', pref => resolve(chrome.runtime.lastError ? null : pref?.value));
 });
 if (!Array.isArray(workspaces)) return { rejected: 'workspaces_unavailable' };
 const known = workspaces.some(entry => entry !== null && typeof entry === 'object'
   && Number.isSafeInteger(entry.id) && entry.id >= 0 && String(entry.id) === workspaceId);
 if (!known) return { rejected: 'unknown_workspace' };
 const selected = await new Promise(resolve => chrome.windows.get(windowId, value => {
   resolve(chrome.runtime.lastError ? null : value);
 }));
 if (!selected) return { rejected: 'window_unavailable' };
 if (selected.state === 'minimized') return { rejected: 'minimized_window' };
 vivaldi.menubar.onActivated.dispatch(windowId, 'JS_LOCAL_ACTIVATE_WORKSPACE', workspaceId);
 return { dispatched: true };
})()"""

SWITCH_REJECTIONS = {
    "workspaces_unavailable": (
        "workspaces_unavailable",
        "Vivaldi's workspace list preference could not be read; nothing was dispatched.",
    ),
    "unknown_workspace": (
        "unknown_workspace",
        "workspace_id is not in Vivaldi's workspace list; nothing was dispatched.",
    ),
    "window_unavailable": (
        "invalid_parameters",
        "window_id must identify a current browser window.",
    ),
    "minimized_window": (
        "minimized_window",
        "The selected window is minimized and would ignore the switch; nothing was dispatched.",
    ),
}

MAX_WORKSPACE_ID = 2**53 - 1


def workspace_parameter(workspace_id: object) -> str:
    """Return the canonical decimal form of a workspace ID, or raise."""
    value = -1
    if isinstance(workspace_id, int) and not isinstance(workspace_id, bool):
        value = workspace_id
    elif isinstance(workspace_id, str) and workspace_id.isascii() and workspace_id.isdigit():
        digits = workspace_id.lstrip("0") or "0"
        if len(digits) <= len(str(MAX_WORKSPACE_ID)):
            value = int(digits)
    if not 0 <= value <= MAX_WORKSPACE_ID:
        raise ControlError("invalid_parameters", "workspace_id must be a nonnegative decimal ID.")
    return str(value)


def _safe_id(value: object) -> int | None:
    """Return a nonnegative JavaScript safe integer, or None for anything else."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_SAFE_INTEGER:
        return value
    return None


def _workspaces(reading: object) -> list[JsonObject] | None:
    """Validate the workspace preference reading; None unless the whole list is well formed."""
    if not isinstance(reading, dict) or "error" in reading:
        return None
    preference = reading.get("result")
    if not isinstance(preference, dict) or not isinstance(preference.get("value"), list):
        return None
    workspaces: list[JsonObject] = []
    seen: set[int] = set()
    for item in preference["value"]:
        if not isinstance(item, dict):
            return None
        identifier = _safe_id(item.get("id"))
        name, emoji = item.get("name"), item.get("emoji")
        if (
            identifier is None
            or identifier in seen
            or not isinstance(name, str)
            or not (emoji is None or isinstance(emoji, str))
        ):
            return None
        seen.add(identifier)
        # An empty emoji means none, so clients see a single "no emoji" value.
        workspaces.append({"id": identifier, "name": name, "emoji": emoji or None})
    return workspaces


def _tab_workspace(tab: JsonObject) -> int | None:
    """Read a tab's workspace ID from its vivExtData JSON; web-panel tabs have none."""
    data = tab.get("vivExtData")
    if not isinstance(data, str):
        return None
    try:
        parsed = json.loads(data)
    except (ValueError, RecursionError):
        return None
    if not isinstance(parsed, dict) or parsed.get("panelId") is not None:
        return None
    identifier = parsed.get("workspaceId")
    # Vivaldi writes these IDs in JSON exponent form (1.234567890123e+12), which
    # json.loads parses as a float; accept integral floats in the safe range.
    # is_integer() is also false for NaN and infinities.
    if isinstance(identifier, float):
        if not identifier.is_integer():
            return None
        identifier = int(identifier)
    return _safe_id(identifier)


def _window(window: object) -> object:
    if not isinstance(window, dict) or not isinstance(window.get("tabs"), list):
        return window
    tabs = [
        {**tab, "workspace_id": _tab_workspace(tab)} if isinstance(tab, dict) else tab
        for tab in window["tabs"]
    ]
    return {**window, "tabs": tabs}


def normalize_snapshot(raw: JsonObject) -> JsonObject:
    """Shape the raw browser reading into the reported state.

    A missing, failed or malformed workspace preference reports ``workspaces: null``
    with the capability false rather than failing the snapshot.
    """
    state = {key: value for key, value in raw.items() if key != "workspace_preference"}
    workspaces = _workspaces(raw.get("workspace_preference"))
    if isinstance(raw.get("windows"), list):
        state["windows"] = [_window(window) for window in raw["windows"]]
    state["workspaces"] = workspaces
    state["capabilities"] = {**raw["capabilities"], "workspaces": workspaces is not None}
    return state


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
                self.cached = normalize_snapshot(value)
                self.cached_revision = revision
                self.generation = generation
                self.updated = time.monotonic()
                self.refresh_sequence += 1
            return self.cached

    async def switch_workspace(self, workspace_id: object, window_id: object = None) -> Any:
        parameter = workspace_parameter(workspace_id)
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
            expression = SWITCH_WORKSPACE.replace(
                "__WORKSPACE_ID__", json.dumps(parameter)
            ).replace("__WINDOW_ID__", str(window_id))
            try:
                result = await self.evaluate(expression)
            finally:
                self.invalidate()
            if isinstance(result, dict) and result.keys() == {"dispatched"}:
                if result["dispatched"] is True:
                    return result
            rejection = result.get("rejected") if isinstance(result, dict) else None
            if isinstance(rejection, str) and rejection in SWITCH_REJECTIONS:
                code, message = SWITCH_REJECTIONS[rejection]
                raise ControlError(code, message, workspace_id=parameter, window_id=window_id)
            raise ControlError("unsupported_result", "Unexpected workspace switch result.")
