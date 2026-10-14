import asyncio
import json
import unittest
import urllib.error
from email.message import Message
from unittest.mock import AsyncMock, patch

from websockets.asyncio.server import ServerConnection, serve

from remaldi.adapter import VivaldiAdapter
from remaldi.browser import EVENT_HOOKS, INCOGNITO_PROBE, UI_SUFFIX, Browser
from remaldi.errors import ControlError
from remaldi.protocol import JsonObject


def socket_path(socket: ServerConnection) -> str:
    assert socket.request is not None
    return socket.request.path.strip("/")


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.received: list[JsonObject] = []
        self.sockets: list[ServerConnection] = []
        self.reject_subscription = False
        self.received_by_path: dict[str, list[JsonObject]] = {}
        self.probe_values: dict[str, bool] = {}

        async def handler(socket: ServerConnection) -> None:
            self.sockets.append(socket)
            async for raw in socket:
                request = json.loads(raw)
                self.received.append(request)
                path = socket_path(socket)
                self.received_by_path.setdefault(path, []).append(request)
                expression = request.get("params", {}).get("expression")
                if expression == INCOGNITO_PROBE and path in self.probe_values:
                    response = {
                        "id": request["id"],
                        "result": {"result": {"value": self.probe_values[path]}},
                    }
                elif self.reject_subscription and request["method"] == "Runtime.enable":
                    response = {
                        "id": request["id"],
                        "error": {"code": -32601, "message": "Unsupported"},
                    }
                else:
                    result = (
                        {"result": {"value": 3}}
                        if request["method"] == "Runtime.evaluate"
                        else {"ok": True}
                    )
                    response = {"id": request["id"], "result": result}
                await socket.send(json.dumps(response))

        self.server = await serve(handler, "127.0.0.1", 0)
        self.addAsyncCleanup(self.server.wait_closed)
        self.addCleanup(self.server.close)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        self.browser = Browser("http://127.0.0.1:9222")
        self.addAsyncCleanup(self.browser.close)

    def target(self, identifier: str, path: str = "") -> JsonObject:
        return {
            "id": identifier,
            "url": "chrome-extension://" + UI_SUFFIX,
            "webSocketDebuggerUrl": f"{self.url}/{path}" if path else self.url,
        }

    def methods(self, path: str) -> list[str]:
        return [request["method"] for request in self.received_by_path.get(path, [])]

    async def test_incognito_ui_target_is_skipped_for_regular_profile(self) -> None:
        self.probe_values = {"incognito": True, "regular": False}
        targets = [self.target("private", "incognito"), self.target("normal", "regular")]
        with patch.object(self.browser, "_discover", return_value=targets):
            await self.browser.refresh()
            self.assertEqual(self.browser.state, "connected")
            self.assertEqual(self.browser.ui_target_id, "normal")
            self.assertEqual(list(self.browser.connections), ["normal"])
            self.assertEqual(await self.browser.request("Browser.getVersion"), {"ok": True})
            # Classification is cached, so later refreshes do not probe again.
            await self.browser.refresh()
        self.assertEqual(self.methods("incognito"), ["Runtime.evaluate"])
        self.assertEqual(
            self.methods("regular"),
            [
                "Runtime.evaluate",
                "Runtime.enable",
                "Runtime.addBinding",
                "Runtime.evaluate",
                "Browser.getVersion",
            ],
        )

    async def test_only_incognito_ui_targets_leave_ui_unavailable(self) -> None:
        self.probe_values = {"one": True, "two": True}
        targets = [self.target("first", "one"), self.target("second", "two")]
        with patch.object(self.browser, "_discover", return_value=targets):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "ui_target_unavailable")
        self.assertEqual(self.browser.connections, {})
        with self.assertRaises(ControlError) as caught:
            await self.browser.request("Browser.getVersion")
        self.assertEqual(caught.exception.code, "ui_target_unavailable")

    async def test_probe_connections_are_closed(self) -> None:
        self.probe_values = {"incognito": True, "regular": False}
        targets = [self.target("private", "incognito"), self.target("normal", "regular")]
        with patch.object(self.browser, "_discover", return_value=targets):
            await self.browser.refresh()
        open_paths: list[str] = []
        for _ in range(50):
            open_paths = [
                socket_path(socket) for socket in self.sockets if socket.state.name == "OPEN"
            ]
            if open_paths == ["regular"]:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(open_paths, ["regular"])

    async def test_unclassified_ui_target_is_retried_after_a_delay(self) -> None:
        # The default handler answers the probe with a non-boolean value.
        self.probe_values = {"regular": False}
        unknown = self.target("unknown", "unknown")
        broken = {**self.target("broken"), "webSocketDebuggerUrl": "ws://127.0.0.1:1"}
        normal = self.target("normal", "regular")
        with patch.object(self.browser, "_discover", return_value=[unknown, broken]):
            await self.browser.refresh()
            self.assertEqual(self.browser.state, "ui_target_unavailable")
            await self.browser.refresh()
        self.assertEqual(self.methods("unknown"), ["Runtime.evaluate"])
        for key in self.browser.probe_retry:
            self.browser.probe_retry[key] = 0
        with patch.object(self.browser, "_discover", return_value=[unknown, broken, normal]):
            await self.browser.refresh()
            # Once a regular target is selected, unclassified ones are not probed again.
            for key in self.browser.probe_retry:
                self.browser.probe_retry[key] = 0
            await self.browser.refresh()
        self.assertEqual(self.browser.ui_target_id, "normal")
        self.assertEqual(self.methods("unknown"), ["Runtime.evaluate", "Runtime.evaluate"])
        self.assertEqual(list(self.browser.connections), ["normal"])

    async def test_switching_ui_target_invalidates_and_hooks_existing_connection(self) -> None:
        self.probe_values = {"incognito": True, "regular": False}
        adapter = VivaldiAdapter(self.browser)
        self.browser.on_change = adapter.invalidate
        private, normal = self.target("private", "incognito"), self.target("normal", "regular")
        with patch.object(self.browser, "_discover", return_value=[private]):
            await self.browser.refresh()
        self.assertEqual(self.browser.ui_target_id, "private")
        # A raw request can reach a listed target before it is selected, for example
        # while its probe is waiting to be retried.
        self.browser.targets = [private, normal]
        with patch.object(self.browser, "_discover", return_value=[private, normal]):
            await self.browser.request("Browser.getVersion", target="normal")
            self.assertEqual(self.methods("regular"), ["Browser.getVersion"])
            unhooked = self.browser.connections["normal"]
            revision = adapter.revision
            await self.browser.refresh()
        self.assertEqual(self.browser.ui_target_id, "normal")
        self.assertGreater(adapter.revision, revision)
        self.assertFalse(unhooked.connected)
        self.assertTrue(self.browser.connections["normal"].connected)
        self.assertEqual(
            self.methods("regular")[-3:],
            ["Runtime.enable", "Runtime.addBinding", "Runtime.evaluate"],
        )

    async def test_refresh_reuses_connection_then_replaces_disappeared_target(self) -> None:
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
            first = self.browser.connections["first"]
            generation = self.browser.generation
            await self.browser.refresh()
            self.assertIs(self.browser.connections["first"], first)
            self.assertEqual(self.browser.generation, generation)
            self.assertEqual(await self.browser.request("Browser.getVersion"), {"ok": True})
        with patch.object(self.browser, "_discover", return_value=[self.target("replacement")]):
            await self.browser.refresh()
        self.assertFalse(first.connected)
        self.assertEqual(list(self.browser.connections), ["replacement"])
        self.assertGreater(self.browser.generation, generation)
        self.assertEqual(self.browser.state, "connected")

    async def test_discovery_failure_discards_targets_and_connections(self) -> None:
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
        with patch.object(self.browser, "_discover", side_effect=OSError("browser unavailable")):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "endpoint_unavailable")
        self.assertEqual(self.browser.connections, {})
        self.assertEqual(self.browser.targets, [])
        with self.assertRaises(ControlError) as caught:
            await self.browser.request("Browser.getVersion")
        self.assertEqual(caught.exception.code, "endpoint_unavailable")

    async def test_endpoint_rejection_is_distinct_from_missing_ui(self) -> None:
        rejection = urllib.error.HTTPError(
            "http://127.0.0.1:9222/json/list", 403, "Forbidden", Message(), None
        )
        with patch.object(self.browser, "_discover", side_effect=rejection):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "endpoint_rejected")
        self.assertIn("403", self.browser.detail)
        with patch.object(self.browser, "_discover", return_value=[]):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "ui_target_unavailable")

    async def test_refresh_reconnects_same_target_after_disconnect(self) -> None:
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
            first = self.browser.connections["first"]
            await first.close()
            await self.browser.refresh()
        self.assertIsNot(self.browser.connections["first"], first)
        self.assertTrue(self.browser.connections["first"].connected)
        self.assertEqual(await self.browser.request("Browser.getVersion"), {"ok": True})

    async def test_missing_explicit_target_is_structured_error(self) -> None:
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
        with self.assertRaises(ControlError) as caught:
            await self.browser.request("Browser.getVersion", target="missing")
        self.assertEqual(caught.exception.code, "target_unavailable")
        self.assertEqual(caught.exception.details["target"], "missing")

    async def test_explicit_target_handshake_failure_is_structured_error(self) -> None:
        target = {
            "id": "broken",
            "url": "https://example.invalid",
            "webSocketDebuggerUrl": "ws://127.0.0.1:1",
        }
        with patch.object(self.browser, "_discover", return_value=[self.target("first"), target]):
            await self.browser.refresh()
        with self.assertRaises(ControlError) as caught:
            await self.browser.request("Browser.getVersion", target="broken")
        self.assertEqual(caught.exception.code, "target_connection_failed")
        self.assertEqual(caught.exception.details["target"], "broken")

    async def test_browser_binding_event_invalidates_adapter(self) -> None:
        adapter = VivaldiAdapter(self.browser)
        self.browser.on_change = adapter.invalidate
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
        self.assertEqual(self.browser.event_support, "subscribed")
        self.assertEqual(
            [request["method"] for request in self.received],
            ["Runtime.enable", "Runtime.addBinding", "Runtime.evaluate"],
        )
        revision = adapter.revision
        await self.sockets[0].send(
            json.dumps(
                {
                    "method": "Runtime.bindingCalled",
                    "params": {"name": "__remaldiChanged", "payload": "dirty"},
                }
            )
        )
        for _ in range(50):
            if adapter.revision > revision:
                break
            await asyncio.sleep(0.01)
        self.assertGreater(adapter.revision, revision)

    async def test_unsupported_event_subscription_uses_ttl_fallback(self) -> None:
        self.reject_subscription = True
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "connected")
        self.assertEqual(self.browser.event_support, "ttl_only")
        adapter = VivaldiAdapter(self.browser)
        evaluate = self.enterContext(
            patch.object(
                adapter, "evaluate", AsyncMock(return_value={"windows": [], "capabilities": {}})
            )
        )
        await adapter.snapshot()
        await adapter.snapshot()
        self.assertEqual(evaluate.await_count, 1)
        adapter.updated -= 6
        await adapter.snapshot()
        self.assertEqual(evaluate.await_count, 2)

    async def test_event_hooks_watch_workspace_preference_and_tab_data(self) -> None:
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
        expression = next(
            request["params"]["expression"]
            for request in self.received
            if request["method"] == "Runtime.evaluate"
        )
        self.assertEqual(expression, EVENT_HOOKS)
        self.assertIn("[viv?.prefs, ['onChanged'], prefChanged]", expression)
        self.assertIn("[viv?.tabsPrivate, ['onExtDataChanged'], notify]", expression)
        self.assertIn("path => { if (path === 'vivaldi.workspaces.list') notify(); }", expression)
        self.assertNotIn("vivaldi.workspaces,", expression)
        recorded = expression.index("hooks.installed.push([event, listener]);")
        self.assertLess(expression.index("globalThis[key] = hooks;"), recorded)
        self.assertLess(
            recorded,
            expression.index("try { event.addListener(listener); hooks.added += 1; } catch {}"),
        )
