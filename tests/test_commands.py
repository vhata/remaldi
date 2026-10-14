import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from remaldi.adapter import RUN_COMMAND, VivaldiAdapter
from remaldi.commands import (
    DENIED,
    LOCAL_ACTIONS,
    REGISTERED_COMMANDS,
    VIVALDI_VERSION,
    command_list,
)
from remaldi.errors import ControlError
from remaldi.service import Service

ALWAYS_DENIED = {
    "COMMAND_EXIT",
    "COMMAND_QUIT_MAC_MAYBE_WARN",
    "COMMAND_CLOSE_WINDOW",
    "COMMAND_MAIL_DELETE_PERMANENTLY",
    "COMMAND_EXPORT_PASSWORDS",
    "COMMAND_MANAGE_PEOPLE",
    "JS_LOCAL_CLEAR_CLOSED_TABS",
    "JS_LOCAL_CLEAR_CLOSED_WEBPANELS",
    "COMMAND_NEW_GUEST_WINDOW",
    "JS_LOCAL_ACTIVATE_WORKSPACE",
}

# Vivaldi names a chain COMMAND_ plus a generated key, so a chain name looks
# like a command. This one is invented in that shape.
CHAIN_NAME = "COMMAND_ckinventedchainkey"


class AllowlistTests(unittest.TestCase):
    def test_allowlist_is_labelled_with_its_vivaldi_version(self):
        self.assertEqual(VIVALDI_VERSION, "8.2.4133.84")

    def test_registry_matches_the_guide_procedure_counts(self):
        # docs/VIVALDI_CONTROL_SURFACE.md: 339 registered commands on 8.2.
        self.assertEqual(len(REGISTERED_COMMANDS), 339)
        self.assertTrue(all(name.startswith("COMMAND_") for name in REGISTERED_COMMANDS))
        for name in ["COMMAND_MAIN_TOGGLE_TAB_BAR", "COMMAND_TAB_STACK_CREATE", "COMMAND_PIN_TAB"]:
            self.assertIn(name, REGISTERED_COMMANDS)
        # Strings in the bundle that are not registered commands.
        for name in ["COMMAND_INITIALIZE", "COMMAND_WORKSPACE_SWITCH_", "COMMAND_CHAIN"]:
            self.assertNotIn(name, REGISTERED_COMMANDS)

    def test_always_denied_names_are_denied(self):
        self.assertEqual(DENIED.keys(), ALWAYS_DENIED)
        self.assertLessEqual(DENIED.keys(), REGISTERED_COMMANDS | LOCAL_ACTIONS.keys())

    def test_command_list_has_names_and_allowed_flags_without_bindings(self):
        entries = command_list()
        names = [entry["name"] for entry in entries]
        self.assertEqual(names, sorted(set(names)))
        self.assertEqual(set(names), REGISTERED_COMMANDS | LOCAL_ACTIONS.keys())
        for entry in entries:
            with self.subTest(name=entry["name"]):
                self.assertEqual(entry.keys(), {"name", "kind", "allowed", "parameter"})
                self.assertIs(entry["allowed"], entry["name"] not in DENIED)
        by_name = {entry["name"]: entry for entry in entries}
        self.assertEqual(
            by_name["COMMAND_MAIN_TOGGLE_TAB_BAR"],
            {
                "name": "COMMAND_MAIN_TOGGLE_TAB_BAR",
                "kind": "command",
                "allowed": True,
                "parameter": None,
            },
        )
        self.assertEqual(by_name["JS_LOCAL_ACTIVATE_TAB"]["kind"], "local_action")
        self.assertEqual(by_name["JS_LOCAL_ACTIVATE_TAB"]["parameter"], "tab ID")
        self.assertEqual(by_name["COMMAND_OPEN_LINK"]["kind"], "local_action")
        self.assertFalse(by_name["COMMAND_EXIT"]["allowed"])
        self.assertFalse(by_name["JS_LOCAL_ACTIVATE_WORKSPACE"]["allowed"])
        self.assertNotIn(CHAIN_NAME, by_name)


class RunCommandTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, result=..., windows=None, capabilities=None):
        state = {
            "windows": windows or [{"id": 7, "focused": True}],
            "capabilities": capabilities or {"command_dispatch": True},
        }
        controller = SimpleNamespace(generation=1, request=AsyncMock())
        controller.request.side_effect = [
            {"result": {"value": state}},
            {"result": {"value": {"dispatched": True} if result is ... else result}},
            {"result": {"value": state}},
        ]
        return VivaldiAdapter(controller), controller

    def evaluated(self, controller):
        return [call.args[1]["expression"] for call in controller.request.await_args_list]

    def dispatches(self, controller):
        return [
            expression
            for expression in self.evaluated(controller)
            if "vivaldi.menubar.onActivated.dispatch(" in expression
        ]

    async def test_allowed_command_dispatches_once_with_empty_parameter(self):
        adapter, controller = self.adapter()
        result = await adapter.run_command("COMMAND_MAIN_TOGGLE_TAB_BAR")
        self.assertEqual(result, {"dispatched": True})
        [expression] = self.dispatches(controller)
        self.assertIn('const name = "COMMAND_MAIN_TOGGLE_TAB_BAR";', expression)
        self.assertIn('const parameter = "";', expression)
        self.assertIn("const windowId = 7;", expression)
        self.assertEqual(expression.count(".dispatch("), 1)
        self.assertIn("vivaldi.menubar.onActivated.dispatch(windowId, name, parameter)", expression)
        self.assertEqual(controller.request.await_count, 2)

    async def test_dispatch_invalidates_state(self):
        adapter, controller = self.adapter()
        await adapter.run_command("COMMAND_MAIN_TOGGLE_TAB_BAR")
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 3)

    async def test_checks_chains_and_window_before_dispatch_in_one_expression(self):
        adapter, controller = self.adapter()
        await adapter.run_command("COMMAND_PAGE_TOGGLE_MUTE")
        expression = self.evaluated(controller)[1]
        dispatch = expression.index("vivaldi.menubar.onActivated.dispatch(")
        checks = [
            "vivaldi.prefs.get('vivaldi.chained_commands.command_list',",
            "chains.some(chain => chain?.name === name)",
            "chrome.windows.get(windowId,",
            "selected.state === 'minimized'",
        ]
        for check in checks:
            with self.subTest(check=check):
                self.assertLess(expression.index(check), dispatch)
        for rejection in [
            "rejected: 'chains_unavailable'",
            "rejected: 'chain_name'",
            "rejected: 'window_unavailable'",
            "rejected: 'minimized_window'",
        ]:
            with self.subTest(rejection=rejection):
                self.assertEqual(expression.count(rejection), 1)
                self.assertLess(expression.index(rejection), dispatch)
        self.assertGreater(expression.index("return { dispatched: true }"), dispatch)

    async def test_denied_names_never_reach_the_browser(self):
        for name in sorted(DENIED):
            with self.subTest(name=name):
                adapter, controller = self.adapter()
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command(name, parameter="1")
                self.assertEqual(caught.exception.code, "command_denied")
                self.assertEqual(caught.exception.details, {"name": name})
                controller.request.assert_not_awaited()

    async def test_unknown_and_chain_names_never_reach_the_browser(self):
        names = [
            CHAIN_NAME,
            "COMMAND_INITIALIZE",
            "COMMAND_WORKSPACE_SWITCH_",
            "COMMAND_WORKSPACE_SWITCH_11",
            "command_main_toggle_tab_bar",
            "COMMAND_MAIN_TOGGLE_TAB_BAR ",
            "Close Other and Open Defined Tab",
            "JS_LOCAL_UNKNOWN",
        ]
        for name in names:
            with self.subTest(name=name):
                adapter, controller = self.adapter()
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command(name)
                self.assertEqual(caught.exception.code, "unknown_command")
                self.assertIn(VIVALDI_VERSION, str(caught.exception))
                controller.request.assert_not_awaited()

    async def test_invalid_names_are_rejected_before_browser_call(self):
        for name in [None, "", 3, True, ["COMMAND_PIN_TAB"]]:
            with self.subTest(name=name):
                adapter, controller = self.adapter()
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command(name)
                self.assertEqual(caught.exception.code, "invalid_parameters")
                controller.request.assert_not_awaited()

    async def test_chain_sharing_the_name_is_a_structured_rejection(self):
        adapter, controller = self.adapter({"rejected": "chain_name"})
        with self.assertRaises(ControlError) as caught:
            await adapter.run_command("JS_LOCAL_REOPEN_CLOSED_TAB", parameter="invented")
        self.assertEqual(caught.exception.code, "chain_not_allowed")
        self.assertEqual(
            caught.exception.details, {"name": "JS_LOCAL_REOPEN_CLOSED_TAB", "window_id": 7}
        )

    async def test_local_action_passes_its_parameter(self):
        cases = [
            ("JS_LOCAL_ACTIVATE_TAB", "42", "42"),
            ("JS_LOCAL_ACTIVATE_TAB", "0042", "42"),
            ("JS_LOCAL_ACTIVATE_WINDOW", "9", "9"),
            ("PERIODIC_RELOAD", "5", "5"),
            ("PERIODIC_RELOAD", "05", "5"),
            ("JS_LOCAL_ACTIVATE_TAB", "0", "0"),
            ("PERIODIC_RELOAD_DISABLE", "all", "all"),
            ("COMMAND_OPEN_LINK", "https://example.com/a?b='c'", "https://example.com/a?b='c'"),
            ("JS_LOCAL_TOGGLE_WEBPANEL", 'Web"Panel\\\n</script>', 'Web"Panel\\\n</script>'),
        ]
        for name, parameter, sent in cases:
            with self.subTest(name=name, parameter=parameter):
                adapter, controller = self.adapter()
                await adapter.run_command(name, parameter=parameter)
                [expression] = self.dispatches(controller)
                self.assertIn(f"const name = {json.dumps(name)};", expression)
                self.assertIn(f"const parameter = {json.dumps(sent)};", expression)

    async def test_placeholder_text_in_a_parameter_is_sent_verbatim(self):
        for parameter in [
            "https://example.com/__WINDOW_ID__",
            "https://example.com/__NAME__/__PARAMETER__",
        ]:
            with self.subTest(parameter=parameter):
                adapter, controller = self.adapter()
                await adapter.run_command("COMMAND_OPEN_LINK", parameter=parameter)
                [expression] = self.dispatches(controller)
                self.assertIn(f"const parameter = {json.dumps(parameter)};", expression)
                self.assertIn("const windowId = 7;", expression)
                self.assertIn('const name = "COMMAND_OPEN_LINK";', expression)

    async def test_parameter_applies_only_to_local_actions(self):
        for parameter in ["1", ""]:
            with self.subTest(parameter=parameter):
                adapter, controller = self.adapter()
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command("COMMAND_MAIN_TOGGLE_TAB_BAR", parameter=parameter)
                self.assertEqual(caught.exception.code, "invalid_parameters")
                controller.request.assert_not_awaited()

    async def test_local_actions_require_a_valid_parameter(self):
        cases = [
            ("JS_LOCAL_ACTIVATE_TAB", None),
            ("JS_LOCAL_ACTIVATE_TAB", ""),
            ("JS_LOCAL_ACTIVATE_TAB", "-1"),
            ("JS_LOCAL_ACTIVATE_TAB", "1.5"),
            ("JS_LOCAL_ACTIVATE_TAB", "1; dangerous()"),
            ("JS_LOCAL_ACTIVATE_TAB", "١"),
            ("JS_LOCAL_ACTIVATE_TAB", str(2**53)),
            ("JS_LOCAL_ACTIVATE_TAB", 42),
            ("COMMAND_OPEN_LINK", None),
            ("COMMAND_OPEN_LINK", "x" * 8193),
            ("JS_LOCAL_OPEN_SESSION", "session"),
            ("PERIODIC_RELOAD", "0"),
            ("PERIODIC_RELOAD", "000"),
            ("PERIODIC_RELOAD_DISABLE", ["all"]),
        ]
        for name, parameter in cases:
            with self.subTest(name=name, parameter=str(parameter)[:20]):
                adapter, controller = self.adapter()
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command(name, parameter=parameter)
                self.assertEqual(caught.exception.code, "invalid_parameters")
                controller.request.assert_not_awaited()

    async def test_window_selection_matches_workspace_switching(self):
        windows = [{"id": 7, "focused": False}, {"id": 9, "focused": True}]
        adapter, controller = self.adapter(windows=windows)
        await adapter.run_command("COMMAND_PIN_TAB")
        self.assertIn("const windowId = 9;", self.evaluated(controller)[1])

        adapter, controller = self.adapter(windows=windows)
        await adapter.run_command("COMMAND_PIN_TAB", window_id=7)
        self.assertIn("const windowId = 7;", self.evaluated(controller)[1])

        for windows, window_id, code in [
            ([{"id": 7, "focused": True}, {"id": 9, "focused": True}], None, "ambiguous_window"),
            ([{"id": 7, "focused": False}], None, "ambiguous_window"),
            ([{"id": 7, "focused": True}], 8, "invalid_parameters"),
            ([{"id": 7, "focused": True}], "7", "invalid_parameters"),
            ([{"id": 1, "focused": True}], True, "invalid_parameters"),
        ]:
            with self.subTest(windows=windows, window_id=window_id):
                adapter, controller = self.adapter(windows=windows)
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command("COMMAND_PIN_TAB", window_id=window_id)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(controller.request.await_count, 1)
                self.assertEqual(self.dispatches(controller), [])

    async def test_browser_rejections_are_structured_errors_without_replay(self):
        cases = {
            "minimized_window": "minimized_window",
            "window_unavailable": "invalid_parameters",
            "chains_unavailable": "command_chains_unavailable",
            "chain_name": "chain_not_allowed",
        }
        for rejection, code in cases.items():
            with self.subTest(rejection=rejection):
                adapter, controller = self.adapter({"rejected": rejection})
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command("COMMAND_MAIN_TOGGLE_TAB_BAR")
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(
                    caught.exception.details,
                    {"name": "COMMAND_MAIN_TOGGLE_TAB_BAR", "window_id": 7},
                )
                self.assertEqual(controller.request.await_count, 2)
                await adapter.snapshot()
                self.assertEqual(controller.request.await_count, 3)

    async def test_unexpected_result_is_not_success(self):
        for value in [None, {}, {"dispatched": False}, {"dispatched": 1}, {"rejected": "x"}, [1]]:
            with self.subTest(value=value):
                adapter, controller = self.adapter(value)
                with self.assertRaises(ControlError) as caught:
                    await adapter.run_command("COMMAND_MAIN_TOGGLE_TAB_BAR")
                self.assertEqual(caught.exception.code, "unsupported_result")
                self.assertEqual(controller.request.await_count, 2)

    async def test_lost_reply_invalidates_state_without_replay(self):
        adapter, controller = self.adapter()
        state = {
            "windows": [{"id": 7, "focused": True}],
            "capabilities": {"command_dispatch": True},
        }
        controller.request.side_effect = [
            {"result": {"value": state}},
            ControlError("unknown_outcome", "lost"),
            {"result": {"value": state}},
        ]
        with self.assertRaises(ControlError) as caught:
            await adapter.run_command("COMMAND_MAIN_TOGGLE_TAB_BAR")
        self.assertEqual(caught.exception.code, "unknown_outcome")
        self.assertEqual(controller.request.await_count, 2)
        await adapter.snapshot()
        self.assertEqual(controller.request.await_count, 3)

    async def test_unsupported_dispatch_has_no_mutation(self):
        adapter, controller = self.adapter(capabilities={"command_dispatch": False})
        with self.assertRaises(ControlError) as caught:
            await adapter.run_command("COMMAND_MAIN_TOGGLE_TAB_BAR")
        self.assertEqual(caught.exception.code, "unsupported_operation")
        self.assertEqual(controller.request.await_count, 1)

    async def test_commands_serialize_with_other_mutations(self):
        adapter, controller = self.adapter()
        await adapter.mutation_lock.acquire()
        try:
            task = asyncio.create_task(adapter.run_command("COMMAND_PIN_TAB"))
            await asyncio.sleep(0.01)
            self.assertFalse(task.done())
            controller.request.assert_not_awaited()
        finally:
            adapter.mutation_lock.release()
        self.assertEqual(await task, {"dispatched": True})

    def test_expression_template_placeholders(self):
        for placeholder in ["__NAME__", "__PARAMETER__", "__WINDOW_ID__"]:
            self.assertEqual(RUN_COMMAND.count(placeholder), 1)


class CommandServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_list_needs_no_browser(self):
        service = Service("http://127.0.0.1:1")
        service.browser.request = AsyncMock()
        result = await service.dispatch({"version": 1, "operation": "command.list"})
        self.assertEqual(result["vivaldi_version"], VIVALDI_VERSION)
        self.assertEqual(result["commands"], command_list())
        service.browser.request.assert_not_awaited()

    async def test_command_run_validates_and_forwards_parameters(self):
        service = Service("http://127.0.0.1:1")
        service.adapter.run_command = AsyncMock(return_value={"dispatched": True})
        params = {"name": "COMMAND_PIN_TAB", "parameter": None, "window_id": 7}
        result = await service.dispatch(
            {"version": 1, "operation": "command.run", "params": params}
        )
        self.assertEqual(result, {"dispatched": True})
        service.adapter.run_command.assert_awaited_once_with(**params)
        for bad in [{}, {"name": "COMMAND_PIN_TAB", "binding": "x"}]:
            with self.subTest(params=bad), self.assertRaises(ControlError) as caught:
                await service.dispatch({"version": 1, "operation": "command.run", "params": bad})
            self.assertEqual(caught.exception.code, "invalid_parameters")
        with self.assertRaises(ControlError):
            await service.dispatch(
                {"version": 1, "operation": "command.list", "params": {"all": True}}
            )
