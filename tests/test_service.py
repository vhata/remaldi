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


class RefreshParameterTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_and_window_list_validate_and_forward_refresh(self) -> None:
        service = Service("http://127.0.0.1:1")
        listed: WindowList = {"default_window_id": None, "windows": []}
        snapshot: JsonObject = {"windows": [], "capabilities": {}}
        handlers = {
            "state": (
                self.enterContext(
                    patch.object(service.adapter, "snapshot", AsyncMock(return_value=snapshot))
                ),
                snapshot,
            ),
            "window.list": (
                self.enterContext(
                    patch.object(service.adapter, "list_windows", AsyncMock(return_value=listed))
                ),
                listed,
            ),
        }
        for operation, (handler, expected) in handlers.items():
            for params, refresh in [
                ({}, False),
                ({"refresh": False}, False),
                ({"refresh": True}, True),
            ]:
                with self.subTest(operation=operation, params=params):
                    handler.reset_mock()
                    result = await service.dispatch(
                        {"version": 1, "operation": operation, "params": params}
                    )
                    self.assertEqual(result, expected)
                    handler.assert_awaited_once_with(refresh=refresh)
            handler.reset_mock()
            for bad in [{"refresh": 1}, {"refresh": "yes"}, {"window_id": 7}]:
                with (
                    self.subTest(operation=operation, params=bad),
                    self.assertRaises(ControlError) as caught,
                ):
                    await service.dispatch({"version": 1, "operation": operation, "params": bad})
                self.assertEqual(caught.exception.code, "invalid_parameters")
                handler.assert_not_awaited()


class RawDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_forwards_method_params_and_target(self) -> None:
        service = Service("http://127.0.0.1:1")
        # autospec binds calls to Browser.request's signature, so the assertions
        # hold whether arguments are passed by position or by keyword.
        request = self.enterContext(
            patch.object(service.browser, "request", autospec=True, return_value={"product": "x"})
        )
        revision = service.adapter.revision
        result = await service.dispatch(
            {
                "version": 1,
                "operation": "raw",
                "params": {"method": "Target.getTargets", "params": {"a": 1}, "target": "t"},
            }
        )
        self.assertEqual(result, {"product": "x"})
        request.assert_awaited_once_with("Target.getTargets", {"a": 1}, "t")
        self.assertEqual(service.adapter.revision, revision + 1)
        request.reset_mock()
        await service.dispatch(
            {"version": 1, "operation": "raw", "params": {"method": "Browser.getVersion"}}
        )
        request.assert_awaited_once_with("Browser.getVersion", {}, None)

    async def test_raw_rejects_invalid_method_params_or_target(self) -> None:
        service = Service("http://127.0.0.1:1")
        request = self.enterContext(patch.object(service.browser, "request", AsyncMock()))
        bad_params: list[JsonObject] = [
            {"method": 1},
            {"method": "Browser.getVersion", "params": None},
            {"method": "Browser.getVersion", "params": []},
            {"method": "Browser.getVersion", "target": 7},
        ]
        for bad in bad_params:
            with self.subTest(params=bad), self.assertRaises(ControlError) as caught:
                await service.dispatch({"version": 1, "operation": "raw", "params": bad})
            self.assertEqual(caught.exception.code, "invalid_parameters")
            self.assertEqual(str(caught.exception), "Invalid DevTools method, params, or target.")
        request.assert_not_awaited()
