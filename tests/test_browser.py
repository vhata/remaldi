import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from websockets.asyncio.server import serve

from remaldi.adapter import VivaldiAdapter
from remaldi.browser import UI_SUFFIX, Browser
from remaldi.errors import ControlError


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.sockets = []
        self.reject_subscription = False

        async def handler(socket):
            self.sockets.append(socket)
            async for raw in socket:
                request = json.loads(raw)
                self.received.append(request)
                if self.reject_subscription and request["method"] == "Runtime.enable":
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
        self.addAsyncCleanup(self.server.close)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        self.browser = Browser("http://127.0.0.1:9222")
        self.addAsyncCleanup(self.browser.close)

    def target(self, identifier):
        return {
            "id": identifier,
            "url": "chrome-extension://" + UI_SUFFIX,
            "webSocketDebuggerUrl": self.url,
        }

    async def test_refresh_reuses_connection_then_replaces_disappeared_target(self):
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

    async def test_discovery_failure_discards_targets_and_connections(self):
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

    async def test_endpoint_rejection_is_distinct_from_missing_ui(self):
        import urllib.error

        rejection = urllib.error.HTTPError(
            "http://127.0.0.1:9222/json/list", 403, "Forbidden", {}, None
        )
        with patch.object(self.browser, "_discover", side_effect=rejection):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "endpoint_rejected")
        self.assertIn("403", self.browser.detail)
        with patch.object(self.browser, "_discover", return_value=[]):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "ui_target_unavailable")

    async def test_refresh_reconnects_same_target_after_disconnect(self):
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
            first = self.browser.connections["first"]
            await first.close()
            await self.browser.refresh()
        self.assertIsNot(self.browser.connections["first"], first)
        self.assertTrue(self.browser.connections["first"].connected)
        self.assertEqual(await self.browser.request("Browser.getVersion"), {"ok": True})

    async def test_missing_explicit_target_is_structured_error(self):
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
        with self.assertRaises(ControlError) as caught:
            await self.browser.request("Browser.getVersion", target="missing")
        self.assertEqual(caught.exception.code, "target_unavailable")
        self.assertEqual(caught.exception.details["target"], "missing")

    async def test_explicit_target_handshake_failure_is_structured_error(self):
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

    async def test_browser_binding_event_invalidates_adapter(self):
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

    async def test_unsupported_event_subscription_uses_ttl_fallback(self):
        self.reject_subscription = True
        with patch.object(self.browser, "_discover", return_value=[self.target("first")]):
            await self.browser.refresh()
        self.assertEqual(self.browser.state, "connected")
        self.assertEqual(self.browser.event_support, "ttl_only")
        adapter = VivaldiAdapter(self.browser)
        adapter.evaluate = AsyncMock(return_value={"windows": [], "capabilities": {}})
        await adapter.snapshot()
        await adapter.snapshot()
        self.assertEqual(adapter.evaluate.await_count, 1)
        adapter.updated -= 6
        await adapter.snapshot()
        self.assertEqual(adapter.evaluate.await_count, 2)
