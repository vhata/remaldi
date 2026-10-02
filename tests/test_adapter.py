import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from remaldi.adapter import VivaldiAdapter
from remaldi.errors import ControlError


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, capabilities=None):
        state = {
            "windows": [{"id": 7, "focused": True}],
            "workspaces": [{"id": 2}],
            "capabilities": capabilities or {"workspace_switch": True},
        }
        controller = SimpleNamespace(
            generation=1, request=AsyncMock(return_value={"result": {"value": state}})
        )
        return VivaldiAdapter(controller), controller, state

    async def test_concurrent_refreshes_share_snapshot_and_cache_expires(self):
        adapter, controller, state = self.adapter()
        values = await asyncio.gather(*(adapter.snapshot() for _ in range(8)))
        self.assertEqual(values, [state] * 8)
        self.assertEqual(controller.request.await_count, 1)
        adapter.updated -= 6
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 2)
        adapter.invalidate()
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 3)
        controller.generation += 1
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 4)

    async def test_switch_dispatches_once_and_invalidates_snapshot(self):
        adapter, controller, state = self.adapter()
        controller.request.side_effect = [
            {"result": {"value": state}},
            {"result": {"value": {"dispatched": True}}},
            {"result": {"value": state}},
        ]
        self.assertEqual(await adapter.switch_workspace(2), {"dispatched": True})
        expressions = [call.args[1]["expression"] for call in controller.request.await_args_list]
        dispatches = [
            expression for expression in expressions if "COMMAND_WORKSPACE_SWITCH_2" in expression
        ]
        self.assertEqual(len(dispatches), 1)
        self.assertIn("dispatch(7,", dispatches[0])
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 3)

    async def test_unsupported_switch_has_no_mutation(self):
        adapter, controller, _ = self.adapter({"workspace_switch": False})
        with self.assertRaises(ControlError) as caught:
            await adapter.switch_workspace(2)
        self.assertEqual(caught.exception.code, "unsupported_operation")
        self.assertEqual(controller.request.await_count, 1)

    async def test_invalid_workspace_is_rejected_before_browser_call(self):
        adapter, controller, _ = self.adapter()
        for value in [True, -1, "2; dangerous()", None]:
            with self.subTest(value=value), self.assertRaises(ControlError) as caught:
                await adapter.switch_workspace(value)
            self.assertEqual(caught.exception.code, "invalid_parameters")
        controller.request.assert_not_awaited()

    async def test_failed_mutation_invalidates_state_without_replay(self):
        adapter, controller, state = self.adapter()
        controller.request.side_effect = [
            {"result": {"value": state}},
            ControlError("unknown_outcome", "lost"),
            {"result": {"value": state}},
        ]
        with self.assertRaises(ControlError) as caught:
            await adapter.switch_workspace(2)
        self.assertEqual(caught.exception.code, "unknown_outcome")
        self.assertEqual(controller.request.await_count, 2)
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 3)

    async def test_overlapping_forced_refreshes_share_browser_request(self):
        adapter, controller, state = self.adapter()
        await adapter.snapshot()
        controller.request.reset_mock()
        started, release = asyncio.Event(), asyncio.Event()

        async def blocked(*args, **kwargs):
            started.set()
            await release.wait()
            return {"result": {"value": state}}

        controller.request.side_effect = blocked
        calls = [asyncio.create_task(adapter.snapshot(refresh=True)) for _ in range(8)]
        await started.wait()
        await asyncio.sleep(0)
        release.set()
        self.assertEqual(await asyncio.gather(*calls), [state] * 8)
        self.assertEqual(controller.request.await_count, 1)
        await adapter.snapshot(refresh=True)
        self.assertEqual(controller.request.await_count, 2)
