import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from remaldi.__main__ import main
from remaldi.client import exchange
from remaldi.protocol import MAX_MESSAGE


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_response_larger_than_default_stream_limit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="remaldi-wire-", dir="/tmp") as directory:
            path = Path(directory)
            payload = {"tabs": "x" * (128 * 1024)}

            async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments: str, result: object) -> tuple[int, str, list[object]]:
        calls: list[object] = []

        def call(operation: str, params: object = None) -> object:
            calls.append((operation, params))
            return result

        output = io.StringIO()
        with (
            patch("sys.argv", ["remaldi", *arguments]),
            patch("remaldi.__main__.call", call),
            contextlib.redirect_stdout(output),
        ):
            status = main()
        return status, output.getvalue(), calls

    def test_window_list_requests_the_window_list_operation(self) -> None:
        listed = {
            "default_window_id": 7,
            "windows": [
                {"id": 7, "focused": True, "state": "normal", "type": "normal", "tab_count": 3}
            ],
        }
        for arguments, refresh in [((), False), (("--refresh",), True)]:
            with self.subTest(arguments=arguments):
                status, output, calls = self.run_cli("window", "list", *arguments, result=listed)
                self.assertEqual(status, 0)
                self.assertEqual(calls, [("window.list", {"refresh": refresh})])
                self.assertEqual(json.loads(output), listed)
