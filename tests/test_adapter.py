import asyncio
import json
import unittest
from collections.abc import Iterable
from unittest.mock import AsyncMock

from remaldi.adapter import SNAPSHOT, VivaldiAdapter, _select_window, normalize_snapshot
from remaldi.errors import ControlError
from remaldi.protocol import JsonObject


class FakeController:
    def __init__(self, value: object = None) -> None:
        self.generation = 1
        self.request = AsyncMock(return_value={"result": {"value": value}})


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def adapter(
        self, capabilities: JsonObject | None = None
    ) -> tuple[VivaldiAdapter, FakeController, JsonObject]:
        state: JsonObject = {
            "windows": [{"id": 7, "focused": True}],
            "workspaces": [{"id": 2}],
            "capabilities": capabilities or {"workspace_switch": True},
        }
        controller = FakeController(state)
        return VivaldiAdapter(controller), controller, state

    async def test_concurrent_refreshes_share_snapshot_and_cache_expires(self) -> None:
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

    def switch_adapter(self, result: object) -> tuple[VivaldiAdapter, FakeController]:
        adapter, controller, state = self.adapter()
        controller.request.side_effect = [
            {"result": {"value": state}},
            {"result": {"value": result}},
            {"result": {"value": state}},
        ]
        return adapter, controller

    def evaluated(self, controller: FakeController) -> list[str]:
        return [call.args[1]["expression"] for call in controller.request.await_args_list]

    async def test_switch_dispatches_local_workspace_action_once_and_invalidates_snapshot(
        self,
    ) -> None:
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

    async def test_switch_parameter_is_canonical_decimal_id(self) -> None:
        for value, parameter in [(2, "2"), ("0002", "2"), ("0", "0"), (2**53 - 1, str(2**53 - 1))]:
            with self.subTest(value=value):
                adapter, controller = self.switch_adapter({"dispatched": True})
                await adapter.switch_workspace(value)
                self.assertIn(f'const workspaceId = "{parameter}";', self.evaluated(controller)[1])

    async def test_switch_uses_explicit_window(self) -> None:
        adapter, controller, state = self.adapter()
        state["windows"] = [{"id": 7, "focused": True}, {"id": 9, "focused": False}]
        controller.request.side_effect = [
            {"result": {"value": state}},
            {"result": {"value": {"dispatched": True}}},
        ]
        await adapter.switch_workspace(2, window_id=9)
        self.assertIn("const windowId = 9;", self.evaluated(controller)[1])

    async def test_switch_checks_preference_and_window_before_dispatch(self) -> None:
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

    async def test_browser_rejections_are_structured_errors_without_replay(self) -> None:
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

    async def test_unexpected_switch_result_is_not_success(self) -> None:
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

    async def test_unsupported_switch_has_no_mutation(self) -> None:
        adapter, controller, _ = self.adapter({"workspace_switch": False})
        with self.assertRaises(ControlError) as caught:
            await adapter.switch_workspace(2)
        self.assertEqual(caught.exception.code, "unsupported_operation")
        self.assertEqual(controller.request.await_count, 1)

    async def test_invalid_workspace_is_rejected_before_browser_call(self) -> None:
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

    async def test_failed_mutation_invalidates_state_without_replay(self) -> None:
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

    async def test_overlapping_forced_refreshes_share_browser_request(self) -> None:
        adapter, controller, state = self.adapter()
        await adapter.snapshot()
        controller.request.reset_mock()
        started, release = asyncio.Event(), asyncio.Event()

        async def blocked(*_args: object, **_kwargs: object) -> JsonObject:
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


def workspace_reading(value: object) -> JsonObject:
    """A successful vivaldi.prefs.get reading as the SNAPSHOT expression returns it."""
    return {"result": {"value": value, "defaultValue": [], "store": "user"}}


def tab(identifier: int, ext_data: object = None) -> JsonObject:
    item: JsonObject = {"id": identifier, "windowId": 7}
    if ext_data is not None:
        item["vivExtData"] = ext_data if isinstance(ext_data, str) else json.dumps(ext_data)
    return item


class WorkspaceSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def snapshot(self, reading: object, tabs: Iterable[object] = ()) -> JsonObject:
        raw: JsonObject = {
            "windows": [{"id": 7, "focused": True, "tabs": list(tabs)}],
            "capabilities": {"windows": True, "tabs": True, "workspace_switch": True},
        }
        if reading is not ...:
            raw["workspace_preference"] = reading
        return await VivaldiAdapter(FakeController(raw)).snapshot()

    def assert_unsupported(self, state: JsonObject) -> None:
        self.assertIsNone(state["workspaces"])
        self.assertFalse(state["capabilities"]["workspaces"])
        self.assertTrue(state["capabilities"]["workspace_switch"])
        self.assertEqual(state["windows"][0]["id"], 7)
        self.assertNotIn("workspace_preference", state)

    def test_command_dispatch_needs_menubar_dispatch_and_prefs(self) -> None:
        # Every command run reads the chain list with vivaldi.prefs.get.
        for definition in [
            (
                "const switchSupported = typeof vivaldi !== 'undefined'"
                " && typeof vivaldi.menubar?.onActivated?.dispatch === 'function';"
            ),
            (
                "const prefsSupported = typeof vivaldi !== 'undefined'"
                " && typeof vivaldi.prefs?.get === 'function';"
            ),
            "workspace_switch:switchSupported,",
            "command_dispatch:switchSupported && prefsSupported}",
        ]:
            with self.subTest(definition=definition):
                self.assertEqual(SNAPSHOT.count(definition), 1)

    def test_snapshot_reads_workspace_preference(self) -> None:
        self.assertIn("vivaldi.prefs.get('vivaldi.workspaces.list'", SNAPSHOT)
        prefs_read = SNAPSHOT[SNAPSHOT.index("vivaldi.prefs.get(") :]
        self.assertIn("const error = chrome.runtime.lastError;", prefs_read)
        self.assertIn("resolve(error ? {error:", prefs_read)
        self.assertNotIn("vivaldi.workspaces.getAll", SNAPSHOT)

    async def test_supported_preference_lists_workspaces_without_icons(self) -> None:
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

    async def test_empty_preference_is_supported_with_no_workspaces(self) -> None:
        state = await self.snapshot(workspace_reading([]))
        self.assertEqual(state["workspaces"], [])
        self.assertTrue(state["capabilities"]["workspaces"])

    async def test_tabs_report_workspace_membership(self) -> None:
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

    async def test_tab_workspace_id_in_exponent_form_is_an_integer(self) -> None:
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

    async def test_tab_workspace_id_rejects_unusable_floats(self) -> None:
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

    async def test_workspace_list_ids_stay_strict_integers(self) -> None:
        state = await self.snapshot(workspace_reading([{"id": 5.0, "name": "Invented"}]))
        self.assertIsNone(state["workspaces"])

    async def test_malformed_tab_data_is_null_per_tab(self) -> None:
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
        tabs: list[object] = [tab(index, value) for index, value in enumerate(values)]
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

    async def test_malformed_preference_reports_unsupported(self) -> None:
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

    async def test_last_error_reports_unsupported(self) -> None:
        state = await self.snapshot({"error": "Invented unknown preference"})
        self.assert_unsupported(state)
        state = await self.snapshot(
            {"error": "Invented", "result": {"value": [{"id": WORKSPACE_A, "name": "X"}]}}
        )
        self.assert_unsupported(state)

    async def test_missing_preference_api_reports_unsupported(self) -> None:
        self.assert_unsupported(await self.snapshot(None))
        self.assert_unsupported(await self.snapshot(...))

    def test_normalize_does_not_mutate_browser_value(self) -> None:
        raw = {
            "windows": [{"id": 7, "tabs": [tab(1, {"workspaceId": WORKSPACE_A})]}],
            "workspace_preference": workspace_reading([]),
            "capabilities": {"workspace_switch": False},
        }
        before = json.loads(json.dumps(raw))
        normalize_snapshot(raw)
        self.assertEqual(raw, before)


class WindowListTests(unittest.IsolatedAsyncioTestCase):
    async def list_windows(self, windows: list[object]) -> object:
        state: JsonObject = {"windows": windows, "capabilities": {"workspace_switch": True}}
        return await VivaldiAdapter(FakeController(state)).list_windows()

    async def test_lists_window_fields_and_tab_counts_without_tab_content(self) -> None:
        windows: list[object] = [
            {
                "id": 7,
                "focused": True,
                "state": "maximized",
                "type": "normal",
                "incognito": False,
                "left": 0,
                "top": 0,
                "tabs": [
                    {"id": 1, "title": "Secret title", "url": "https://private.example/"},
                    {"id": 2, "title": "Other title", "url": "https://other.example/"},
                ],
            },
            {"id": 9, "focused": False, "state": "minimized", "type": "popup", "tabs": []},
        ]
        result = await self.list_windows(windows)
        self.assertEqual(
            result,
            {
                "default_window_id": 7,
                "windows": [
                    {
                        "id": 7,
                        "focused": True,
                        "state": "maximized",
                        "type": "normal",
                        "tab_count": 2,
                    },
                    {
                        "id": 9,
                        "focused": False,
                        "state": "minimized",
                        "type": "popup",
                        "tab_count": 0,
                    },
                ],
            },
        )
        encoded = json.dumps(result)
        for private in ["Secret title", "Other title", "private.example", "other.example"]:
            self.assertNotIn(private, encoded)

    async def test_default_window_follows_the_selection_rule(self) -> None:
        for windows in [
            [{"id": 7, "focused": True}, {"id": 9, "focused": False}],
            [{"id": 7, "focused": False}, {"id": 9, "focused": True}],
            [{"id": 7, "focused": False}, {"id": 9, "focused": False}],
            [{"id": 7, "focused": True}, {"id": 9, "focused": True}],
            [{"id": 7, "focused": 1}],
            [],
        ]:
            with self.subTest(windows=windows):
                state: JsonObject = {"windows": windows}
                try:
                    expected: int | None = _select_window(state, None)
                except ControlError as error:
                    self.assertEqual(error.code, "ambiguous_window")
                    expected = None
                result = await self.list_windows(list(windows))
                self.assertIsInstance(result, dict)
                assert isinstance(result, dict)
                self.assertEqual(result["default_window_id"], expected)

    async def test_unusable_window_fields_are_null(self) -> None:
        windows: list[object] = [
            {"id": True, "focused": "yes", "state": 3, "type": None, "tabs": "many"},
            {"focused": False},
            "not a window",
        ]
        self.assertEqual(
            await self.list_windows(windows),
            {
                "default_window_id": None,
                "windows": [
                    {"id": None, "focused": False, "state": None, "type": None, "tab_count": None},
                    {"id": None, "focused": False, "state": None, "type": None, "tab_count": None},
                ],
            },
        )

    async def test_focused_window_without_a_usable_id_is_not_the_default(self) -> None:
        result = await self.list_windows([{"id": "7", "focused": True}])
        self.assertIsInstance(result, dict)
        assert isinstance(result, dict)
        self.assertIsNone(result["default_window_id"])

    async def test_reads_the_cached_snapshot_unless_refreshed(self) -> None:
        state: JsonObject = {
            "windows": [{"id": 7, "focused": True, "tabs": []}],
            "capabilities": {},
        }
        controller = FakeController(state)
        adapter = VivaldiAdapter(controller)
        await adapter.list_windows()
        await adapter.list_windows()
        self.assertEqual(controller.request.await_count, 1)
        await adapter.list_windows(refresh=True)
        self.assertEqual(controller.request.await_count, 2)
        self.assertEqual(controller.request.await_args_list[0].args[1]["expression"], SNAPSHOT)
