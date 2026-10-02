"""Exercise the CDP wire against a real local WebSocket server."""

import asyncio
import json
import unittest

from websockets.asyncio.server import serve

from remaldi.errors import ControlError
from remaldi.transport import CDPConnection


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, handler, timeout=0.2):
        server = await serve(handler, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addAsyncCleanup(server.close)
        port = server.sockets[0].getsockname()[1]
        connection = CDPConnection(f"ws://127.0.0.1:{port}", timeout=timeout)
        await connection.connect()
        self.addAsyncCleanup(connection.close)
        return connection

    async def test_correlates_out_of_order_replies_with_events_between(self):
        async def handler(socket):
            requests = [json.loads(await socket.recv()) for _ in range(2)]
            await socket.send(
                json.dumps({"method": "Runtime.consoleAPICalled", "params": {"type": "log"}})
            )
            for request in reversed(requests):
                await socket.send(
                    json.dumps({"id": request["id"], "result": {"method": request["method"]}})
                )
            await socket.wait_closed()

        connection = await self.connect(handler)
        events = []
        connection.on_event = events.append
        first, second = await asyncio.gather(
            connection.request("Browser.getVersion", {}),
            connection.request("Runtime.getHeapUsage", {}),
        )
        self.assertEqual(first, {"method": "Browser.getVersion"})
        self.assertEqual(second, {"method": "Runtime.getHeapUsage"})
        self.assertEqual(events[0]["method"], "Runtime.consoleAPICalled")

    async def test_request_timeout_does_not_break_next_request(self):
        async def handler(socket):
            first = json.loads(await socket.recv())
            await asyncio.sleep(0.1)
            await socket.send(json.dumps({"id": first["id"], "result": {"late": True}}))
            second = json.loads(await socket.recv())
            await socket.send(json.dumps({"id": second["id"], "result": {"ok": True}}))
            await socket.wait_closed()

        connection = await self.connect(handler, timeout=0.05)
        with self.assertRaises(ControlError) as caught:
            await connection.request("Browser.getVersion", {})
        self.assertEqual(caught.exception.code, "unknown_outcome")
        await asyncio.sleep(0.1)
        self.assertEqual(await connection.request("Browser.getVersion", {}), {"ok": True})

    async def test_cdp_error_is_reported(self):
        async def handler(socket):
            request = json.loads(await socket.recv())
            await socket.send(
                json.dumps(
                    {"id": request["id"], "error": {"code": -32601, "message": "Unknown method"}}
                )
            )
            await socket.wait_closed()

        connection = await self.connect(handler)
        with self.assertRaises(ControlError) as caught:
            await connection.request("Unavailable.operation", {})
        self.assertEqual(caught.exception.code, "devtools_error")
        self.assertEqual(caught.exception.details["error"]["code"], -32601)

    async def test_disconnect_fails_pending_requests_without_replaying(self):
        received = []

        async def handler(socket):
            received.append(json.loads(await socket.recv()))
            await socket.close()

        connection = await self.connect(handler)
        with self.assertRaises(ControlError) as caught:
            await connection.request("Runtime.evaluate", {"expression": "doSomething()"})
        self.assertEqual(caught.exception.code, "unknown_outcome")
        self.assertEqual(len(received), 1)
