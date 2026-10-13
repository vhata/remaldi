import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from remaldi.adapter import SNAPSHOT, VivaldiAdapter, normalize_snapshot
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
        self.assertEqual(values, [normalize_snapshot(state)] * 8)
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

    def switch_adapter(self, result):
        adapter, controller, state = self.adapter()
        controller.request.side_effect = [
            {"result": {"value": state}},
            {"result": {"value": result}},
            {"result": {"value": state}},
        ]
        return adapter, controller

    def evaluated(self, controller):
        return [call.args[1]["expression"] for call in controller.request.await_args_list]

    async def test_switch_dispatches_local_workspace_action_once_and_invalidates_snapshot(self):
        adapter, controller = self.switch_adapter({"dispatched": True})
        self.assertEqual(await adapter.switch_workspace("1712345678901"), {"dispatched": True})
        dispatches = [
            expression
            for expression in self.evaluated(controller)
            if "JS_LOCAL_ACTIVATE_WORKSPACE" in expression
        ]
        self.assertEqual(len(dispatches), 1)
        expression = dispatches[0]
        self.assertIn('const workspaceId = "1712345678901";', expression)
        self.assertIn("const windowId = 7;", expression)
        self.assertIn(
            "vivaldi.menubar.onActivated.dispatch(windowId, 'JS_LOCAL_ACTIVATE_WORKSPACE', workspaceId)",
            expression,
        )
        self.assertNotIn("COMMAND_WORKSPACE_SWITCH_", expression)
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 3)

    async def test_switch_parameter_is_canonical_decimal_id(self):
        for value, parameter in [(2, "2"), ("0002", "2"), ("0", "0"), (2**53 - 1, str(2**53 - 1))]:
            with self.subTest(value=value):
                adapter, controller = self.switch_adapter({"dispatched": True})
                await adapter.switch_workspace(value)
                self.assertIn(f'const workspaceId = "{parameter}";', self.evaluated(controller)[1])

    async def test_switch_uses_explicit_window(self):
        adapter, controller, state = self.adapter()
        state["windows"] = [{"id": 7, "focused": True}, {"id": 9, "focused": False}]
        controller.request.side_effect = [
            {"result": {"value": state}},
            {"result": {"value": {"dispatched": True}}},
        ]
        await adapter.switch_workspace(2, window_id=9)
        self.assertIn("const windowId = 9;", self.evaluated(controller)[1])

    async def test_switch_checks_preference_and_window_before_dispatch(self):
        adapter, controller = self.switch_adapter({"dispatched": True})
        await adapter.switch_workspace(2)
        expression = self.evaluated(controller)[1]
        dispatch = expression.index("vivaldi.menubar.onActivated.dispatch(")
        self.assertEqual(expression.count(".dispatch("), 1)
        checks = [
            "vivaldi.prefs.get('vivaldi.workspaces.list',",
            "String(entry.id) === workspaceId",
            "chrome.windows.get(windowId,",
            "selected.state === 'minimized'",
        ]
        for check in checks:
            with self.subTest(check=check):
                self.assertLess(expression.index(check), dispatch)
        rejections = [
            "rejected: 'workspaces_unavailable'",
            "rejected: 'unknown_workspace'",
            "rejected: 'window_unavailable'",
            "rejected: 'minimized_window'",
        ]
        for rejection in rejections:
            with self.subTest(rejection=rejection):
                self.assertEqual(expression.count(rejection), 1)
                self.assertLess(expression.index(rejection), dispatch)
        self.assertGreater(expression.index("return { dispatched: true }"), dispatch)

    async def test_browser_rejections_are_structured_errors_without_replay(self):
        cases = {
            "unknown_workspace": "unknown_workspace",
            "minimized_window": "minimized_window",
            "workspaces_unavailable": "workspaces_unavailable",
            "window_unavailable": "invalid_parameters",
        }
        for rejection, code in cases.items():
            with self.subTest(rejection=rejection):
                adapter, controller = self.switch_adapter({"rejected": rejection})
                with self.assertRaises(ControlError) as caught:
                    await adapter.switch_workspace(2)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.details, {"workspace_id": "2", "window_id": 7})
                self.assertEqual(controller.request.await_count, 2)
                await adapter.snapshot()
                self.assertEqual(controller.request.await_count, 3)

    async def test_unexpected_switch_result_is_not_success(self):
        values = [
            None,
            {},
            {"dispatched": False},
            {"dispatched": 1},
            {"dispatched": 1.0},
            {"rejected": "other"},
            {"rejected": ["unknown_workspace"]},
            {"rejected": {"code": "unknown_workspace"}},
            [True],
        ]
        for value in values:
            with self.subTest(value=value):
                adapter, controller = self.switch_adapter(value)
                with self.assertRaises(ControlError) as caught:
                    await adapter.switch_workspace(2)
                self.assertEqual(caught.exception.code, "unsupported_result")
                self.assertEqual(controller.request.await_count, 2)
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
        for value in [
            True,
            -1,
            "2; dangerous()",
            None,
            "",
            "\u00b2",
            "\u0661\u0662",
            2**53,
            str(2**53),
            2.0,
        ]:
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
        self.assertEqual(await asyncio.gather(*calls), [normalize_snapshot(state)] * 8)
        self.assertEqual(controller.request.await_count, 1)
        await adapter.snapshot(refresh=True)
        self.assertEqual(controller.request.await_count, 2)


WORKSPACE_A = 1700000000001
WORKSPACE_B = 1700000000002


def workspace_reading(value):
    """A successful vivaldi.prefs.get reading as the SNAPSHOT expression returns it."""
    return {"result": {"value": value, "defaultValue": [], "store": "user"}}


def tab(identifier, ext_data=None):
    item = {"id": identifier, "windowId": 7}
    if ext_data is not None:
        item["vivExtData"] = ext_data if isinstance(ext_data, str) else json.dumps(ext_data)
    return item


class WorkspaceSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def snapshot(self, reading, tabs=()):
        raw = {
            "windows": [{"id": 7, "focused": True, "tabs": list(tabs)}],
            "capabilities": {"windows": True, "tabs": True, "workspace_switch": True},
        }
        if reading is not ...:
            raw["workspace_preference"] = reading
        controller = SimpleNamespace(
            generation=1, request=AsyncMock(return_value={"result": {"value": raw}})
        )
        return await VivaldiAdapter(controller).snapshot()

    def assert_unsupported(self, state):
        self.assertIsNone(state["workspaces"])
        self.assertFalse(state["capabilities"]["workspaces"])
        self.assertTrue(state["capabilities"]["workspace_switch"])
        self.assertEqual(state["windows"][0]["id"], 7)
        self.assertNotIn("workspace_preference", state)

    def test_snapshot_reports_command_dispatch_with_workspace_switch(self):
        self.assertIn(
            "workspace_switch:switchSupported, command_dispatch:switchSupported", SNAPSHOT
        )

    def test_snapshot_reads_workspace_preference(self):
        self.assertIn("vivaldi.prefs.get('vivaldi.workspaces.list'", SNAPSHOT)
        prefs_read = SNAPSHOT[SNAPSHOT.index("vivaldi.prefs.get(") :]
        self.assertIn("const error = chrome.runtime.lastError;", prefs_read)
        self.assertIn("resolve(error ? {error:", prefs_read)
        self.assertNotIn("vivaldi.workspaces.getAll", SNAPSHOT)

    async def test_supported_preference_lists_workspaces_without_icons(self):
        state = await self.snapshot(
            workspace_reading(
                [
                    {"id": WORKSPACE_A, "name": "Invented One", "icon": "<svg/>", "emoji": "*"},
                    {"id": WORKSPACE_B, "name": "Invented Two", "icon": "<svg/>"},
                    {"id": 0, "name": "Invented Zero", "icon": "<svg/>", "emoji": None},
                    {"id": 2**53 - 1, "name": "Invented Max", "icon": "<svg/>", "emoji": ""},
                ]
            )
        )
        self.assertEqual(
            state["workspaces"],
            [
                {"id": WORKSPACE_A, "name": "Invented One", "emoji": "*"},
                {"id": WORKSPACE_B, "name": "Invented Two", "emoji": None},
                {"id": 0, "name": "Invented Zero", "emoji": None},
                {"id": 2**53 - 1, "name": "Invented Max", "emoji": None},
            ],
        )
        self.assertTrue(state["capabilities"]["workspaces"])
        self.assertTrue(state["capabilities"]["workspace_switch"])
        self.assertNotIn("workspace_preference", state)

    async def test_empty_preference_is_supported_with_no_workspaces(self):
        state = await self.snapshot(workspace_reading([]))
        self.assertEqual(state["workspaces"], [])
        self.assertTrue(state["capabilities"]["workspaces"])

    async def test_tabs_report_workspace_membership(self):
        state = await self.snapshot(
            workspace_reading([{"id": WORKSPACE_A, "name": "Invented", "icon": ""}]),
            [
                tab(1, {"workspaceId": WORKSPACE_A, "ext": "kept"}),
                tab(2, {}),
                tab(3),
                tab(4, {"panelId": "WebPanel_invented", "workspaceId": WORKSPACE_A}),
                tab(5, {"workspaceId": 0}),
                tab(6, {"panelId": None, "workspaceId": WORKSPACE_B}),
                tab(7, {"workspaceId": 2**53 - 1}),
            ],
        )
        tabs = state["windows"][0]["tabs"]
        self.assertEqual(
            [item["workspace_id"] for item in tabs],
            [WORKSPACE_A, None, None, None, 0, WORKSPACE_B, 2**53 - 1],
        )
        self.assertEqual(json.loads(tabs[0]["vivExtData"])["ext"], "kept")

    async def test_tab_workspace_id_in_exponent_form_is_an_integer(self):
        # Vivaldi writes vivExtData workspace IDs in JSON exponent form, which
        # json.loads parses as a float.
        exponent_id = 1712345678901
        state = await self.snapshot(
            workspace_reading([{"id": exponent_id, "name": "Invented", "icon": ""}]),
            [
                tab(1, '{"workspaceId":1.712345678901e+12}'),
                tab(2, '{"workspaceId":5.0}'),
                tab(3, '{"workspaceId":0.0}'),
                tab(4, '{"workspaceId":9.007199254740991e+15}'),
            ],
        )
        reported = [item["workspace_id"] for item in state["windows"][0]["tabs"]]
        self.assertEqual(reported, [exponent_id, 5, 0, 2**53 - 1])
        self.assertTrue(all(type(value) is int for value in reported))
        self.assertEqual(reported[0], state["workspaces"][0]["id"])

    async def test_tab_workspace_id_rejects_unusable_floats(self):
        values = {
            "fractional": '{"workspaceId":1.7123456789015e+12}',
            "small fraction": '{"workspaceId":0.5}',
            "negative": '{"workspaceId":-1.0e+3}',
            "above safe range": '{"workspaceId":9.007199254740992e+15}',
            "huge": '{"workspaceId":1e+300}',
            "NaN": '{"workspaceId":NaN}',
            "infinity": '{"workspaceId":Infinity}',
            "negative infinity": '{"workspaceId":-Infinity}',
        }
        tabs = [tab(index, value) for index, value in enumerate(values.values())]
        state = await self.snapshot(workspace_reading([]), tabs)
        reported = state["windows"][0]["tabs"]
        for index, label in enumerate(values):
            with self.subTest(label):
                self.assertIsNone(reported[index]["workspace_id"])

    async def test_workspace_list_ids_stay_strict_integers(self):
        state = await self.snapshot(workspace_reading([{"id": 5.0, "name": "Invented"}]))
        self.assertIsNone(state["workspaces"])

    async def test_malformed_tab_data_is_null_per_tab(self):
        values = [
            "{not json",
            "",
            "[1, 2]",
            '"text"',
            "[" * 100000,
            {"workspaceId": str(WORKSPACE_A)},
            {"workspaceId": True},
            {"workspaceId": -1},
            {"workspaceId": 1.5},
            {"workspaceId": 2**53},
            {"workspaceId": None},
        ]
        tabs = [tab(index, value) for index, value in enumerate(values)]
        tabs += [{"id": 98, "vivExtData": {"workspaceId": WORKSPACE_A}}, "not a tab"]
        tabs.append(tab(99, {"workspaceId": WORKSPACE_B}))
        state = await self.snapshot(workspace_reading([]), tabs)
        reported = state["windows"][0]["tabs"]
        for index, value in enumerate(values):
            with self.subTest(value=str(value)[:40]):
                self.assertIsNone(reported[index]["workspace_id"])
        self.assertIsNone(reported[-3]["workspace_id"])
        self.assertEqual(reported[-2], "not a tab")
        self.assertEqual(reported[-1]["workspace_id"], WORKSPACE_B)
        self.assertTrue(state["capabilities"]["workspaces"])

    async def test_malformed_preference_reports_unsupported(self):
        valid = {"id": WORKSPACE_A, "name": "Invented", "icon": ""}
        readings = {
            "result is null": {"result": None},
            "result not an object": {"result": [valid]},
            "value missing": {"result": {"defaultValue": []}},
            "value not a list": {"result": {"value": {"0": valid}}},
            "value is JSON text": workspace_reading(json.dumps([valid])),
            "item not an object": workspace_reading([valid, "invented"]),
            "id missing": workspace_reading([{"name": "Invented"}]),
            "id negative": workspace_reading([{**valid, "id": -1}]),
            "id boolean": workspace_reading([{**valid, "id": True}]),
            "id fractional": workspace_reading([{**valid, "id": 1.5}]),
            "id string": workspace_reading([{**valid, "id": str(WORKSPACE_A)}]),
            "id unsafe": workspace_reading([{**valid, "id": 2**53}]),
            "id duplicated": workspace_reading([valid, {**valid, "name": "Other"}]),
            "name missing": workspace_reading([{"id": WORKSPACE_A}]),
            "name not text": workspace_reading([{**valid, "name": 3}]),
            "emoji not text": workspace_reading([{**valid, "emoji": 3}]),
            "reading not an object": "invented",
        }
        for label, reading in readings.items():
            with self.subTest(label):
                state = await self.snapshot(reading, [tab(1, {"workspaceId": WORKSPACE_A})])
                self.assert_unsupported(state)
                self.assertEqual(state["windows"][0]["tabs"][0]["workspace_id"], WORKSPACE_A)

    async def test_last_error_reports_unsupported(self):
        state = await self.snapshot({"error": "Invented unknown preference"})
        self.assert_unsupported(state)
        state = await self.snapshot(
            {"error": "Invented", "result": {"value": [{"id": WORKSPACE_A, "name": "X"}]}}
        )
        self.assert_unsupported(state)

    async def test_missing_preference_api_reports_unsupported(self):
        self.assert_unsupported(await self.snapshot(None))
        self.assert_unsupported(await self.snapshot(...))

    def test_normalize_does_not_mutate_browser_value(self):
        raw = {
            "windows": [{"id": 7, "tabs": [tab(1, {"workspaceId": WORKSPACE_A})]}],
            "workspace_preference": workspace_reading([]),
            "capabilities": {"workspace_switch": False},
        }
        before = json.loads(json.dumps(raw))
        normalize_snapshot(raw)
        self.assertEqual(raw, before)
