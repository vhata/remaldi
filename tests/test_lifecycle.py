"""Subprocess tests use a private temporary runtime and never launch Vivaldi."""

import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="remaldi-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.environment = dict(
            os.environ, REMALDI_RUNTIME_DIR=self.temp.name, REMALDI_ENDPOINT="http://127.0.0.1:1"
        )
        self.addCleanup(self.stop_service)

    def command(self, *arguments: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "remaldi", *arguments],
            env=self.environment,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def result(self, completed: subprocess.CompletedProcess[str]) -> Any:
        value = json.loads(completed.stdout)
        return value.get("result", value)

    def stop_service(self) -> None:
        self.command("stop")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.result(self.command("status")).get("service") != "running":
                return
            time.sleep(0.05)
        self.fail("test daemon did not stop")

    def test_status_and_stop_do_not_start_service(self) -> None:
        status = self.command("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertNotEqual(self.result(status).get("service"), "running")
        stopped = self.command("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertNotEqual(self.result(self.command("status")).get("service"), "running")

    def test_concurrent_first_use_starts_one_service_and_reuses_it(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            calls = list(
                executor.map(lambda _: self.command("raw", "Browser.getVersion"), range(4))
            )
        self.assertTrue(all(call.returncode != 0 for call in calls))
        status = self.result(self.command("status"))
        self.assertEqual(status["service"], "running")
        pid = status["pid"]
        self.assertGreater(pid, 0)
        self.assertEqual(status["browser"]["state"], "endpoint_unavailable")
        self.assertNotEqual(self.command("raw", "Browser.getVersion").returncode, 0)
        self.assertEqual(self.result(self.command("status"))["pid"], pid)
        self.stop_service()
        self.assertNotEqual(self.result(self.command("status")).get("service"), "running")

    def test_relative_runtime_first_use_outside_package_root(self) -> None:
        package_root = str(Path(__file__).resolve().parent.parent)
        self.environment["PYTHONPATH"] = (
            package_root + os.pathsep + self.environment.get("PYTHONPATH", "")
        )
        self.environment["REMALDI_RUNTIME_DIR"] = "."
        # Cleanup uses the absolute path even if startup at the relative path fails.
        self.addCleanup(self.environment.update, REMALDI_RUNTIME_DIR=self.temp.name)

        listed = self.command("command", "list", cwd=self.temp.name)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertTrue((Path(self.temp.name) / "control.sock").is_socket())
        status = self.result(self.command("status", cwd=self.temp.name))
        self.assertEqual(status["service"], "running")
        pid = status["pid"]
        repeated = self.command("command", "list", cwd=self.temp.name)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(self.result(self.command("status", cwd=self.temp.name))["pid"], pid)

        # An absolute override from another cwd must address the same daemon.
        self.environment["REMALDI_RUNTIME_DIR"] = self.temp.name
        self.assertEqual(self.result(self.command("status"))["pid"], pid)
        self.environment["REMALDI_RUNTIME_DIR"] = "."
        stopped = self.command("stop", cwd=self.temp.name)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertEqual(self.result(stopped)["service"], "stopping")
        self.environment["REMALDI_RUNTIME_DIR"] = self.temp.name
        self.stop_service()
        self.environment["REMALDI_RUNTIME_DIR"] = "."
        self.assertEqual(
            self.result(self.command("status", cwd=self.temp.name))["service"], "stopped"
        )

    def test_first_use_recovers_stale_socket(self) -> None:
        socket_path = Path(self.temp.name) / "control.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(socket_path))
        self.assertTrue(socket_path.exists())
        self.command("raw", "Browser.getVersion")
        self.assertEqual(self.result(self.command("status"))["service"], "running")

    def test_socket_protocol_rejects_version_mismatch_then_accepts_status(self) -> None:
        self.command("raw", "Browser.getVersion")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(Path(self.temp.name) / "control.sock"))
            with client.makefile("rwb") as stream:
                stream.write(b'{"version":2,"id":"bad","operation":"status"}\n')
                stream.flush()
                rejected = json.loads(stream.readline())
                self.assertFalse(rejected["ok"])
                self.assertEqual(rejected["id"], "bad")
                self.assertEqual(rejected["error"]["code"], "protocol_mismatch")
                stream.write(b'{"version":1,"id":"good","operation":"status"}\n')
                stream.flush()
                accepted = json.loads(stream.readline())
                self.assertTrue(accepted["ok"])
                self.assertEqual(accepted["id"], "good")
                self.assertEqual(accepted["result"]["service"], "running")

    def test_command_cli_lists_and_denies_without_a_browser(self) -> None:
        listed = self.command("command", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        result = json.loads(listed.stdout)
        self.assertEqual(result["vivaldi_version"], "8.2.4133.84")
        allowed = {entry["name"]: entry["allowed"] for entry in result["commands"]}
        self.assertTrue(allowed["COMMAND_MAIN_TOGGLE_TAB_BAR"])
        self.assertFalse(allowed["COMMAND_EXIT"])
        denied = self.command("command", "run", "COMMAND_EXIT", "--window-id", "1")
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(json.loads(denied.stderr)["error"]["code"], "command_denied")
        misuse = self.command("command", "run", "COMMAND_PIN_TAB", "--parameter", "1")
        self.assertEqual(json.loads(misuse.stderr)["error"]["code"], "invalid_parameters")
