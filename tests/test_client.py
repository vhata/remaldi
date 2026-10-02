import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from remaldi.client import exchange
from remaldi.protocol import MAX_MESSAGE


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_response_larger_than_default_stream_limit(self):
        with tempfile.TemporaryDirectory(prefix="remaldi-wire-", dir="/tmp") as directory:
            path = Path(directory)
            payload = {"tabs": "x" * (128 * 1024)}

            async def handle(reader, writer):
                try:
                    request = json.loads(await reader.readline())
                    writer.write(
                        (
                            json.dumps(
                                {"version": 1, "id": request["id"], "ok": True, "result": payload}
                            )
                            + "\n"
                        ).encode()
                    )
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

            server = await asyncio.start_unix_server(
                handle, path=path / "control.sock", limit=MAX_MESSAGE
            )
            try:
                self.assertEqual(await exchange(path, "state"), payload)
            finally:
                server.close()
                await server.wait_closed()
