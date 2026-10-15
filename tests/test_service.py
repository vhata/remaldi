import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from remaldi.adapter import WindowList
from remaldi.client import exchange
from remaldi.errors import ControlError
from remaldi.protocol import JsonObject
from remaldi.service import Service


class ServiceDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="remaldi-deadline-", dir="/tmp")
        self.path = Path(self.directory.name)
        self.service = Service("http://127.0.0.1:1")
        self.tasks: set[asyncio.Task[None]] = set()

        def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            task = asyncio.create_task(self.service.handle(reader, writer))
            self.tasks.add(task)

        self.server = await asyncio.start_unix_server(handle, path=self.path / "control.sock")

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.directory.cleanup()

    async def test_deadline_cancels_running_operation(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def operation(_params: JsonObject) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.service.operations["blocked"] = operation
        with patch("remaldi.service.REQUEST_TIMEOUT", 0.05):
            request = asyncio.create_task(exchange(self.path, "blocked"))
            await started.wait()
            with self.assertRaises(ControlError) as caught:
                await request
        self.assertEqual(caught.exception.code, "unknown_outcome")
        self.assertTrue(cancelled.is_set())

    async def test_expired_queued_mutations_do_not_execute_after_lock_release(self) -> None:
        executed: list[JsonObject] = []

        async def mutation(params: JsonObject) -> JsonObject:
            async with self.service.adapter.mutation_lock:
                executed.append(params)
                return {"dispatched": True}

        self.service.operations["mutation"] = mutation
        await self.service.adapter.mutation_lock.acquire()
        try:
            with patch("remaldi.service.REQUEST_TIMEOUT", 0.05):
                responses = await asyncio.gather(
                    exchange(self.path, "mutation", {"value": 1}),
                    exchange(self.path, "mutation", {"value": 2}),
                    return_exceptions=True,
                )
            self.assertTrue(all(isinstance(response, ControlError) for response in responses))
            self.assertEqual(
                [response.code for response in responses if isinstance(response, ControlError)],
                ["unknown_outcome"] * 2,
            )
        finally:
            self.service.adapter.mutation_lock.release()
        await asyncio.sleep(0.02)
        self.assertEqual(executed, [])


class WindowListServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_window_list_validates_and_forwards_refresh(self) -> None:
        service = Service("http://127.0.0.1:1")
        listed: WindowList = {"default_window_id": None, "windows": []}
        list_windows = self.enterContext(
            patch.object(service.adapter, "list_windows", AsyncMock(return_value=listed))
        )
        for params, refresh in [
            ({}, False),
            ({"refresh": False}, False),
            ({"refresh": True}, True),
        ]:
            with self.subTest(params=params):
                list_windows.reset_mock()
                result = await service.dispatch(
                    {"version": 1, "operation": "window.list", "params": params}
                )
                self.assertEqual(result, listed)
                list_windows.assert_awaited_once_with(refresh=refresh)
        for bad in [{"refresh": 1}, {"refresh": "yes"}, {"window_id": 7}]:
            with self.subTest(params=bad), self.assertRaises(ControlError) as caught:
                await service.dispatch({"version": 1, "operation": "window.list", "params": bad})
            self.assertEqual(caught.exception.code, "invalid_parameters")
