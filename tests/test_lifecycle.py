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


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="remaldi-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.environment = dict(
            os.environ, REMALDI_RUNTIME_DIR=self.temp.name, REMALDI_ENDPOINT="http://127.0.0.1:1"
        )
        self.addCleanup(self.stop_service)

    def command(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "remaldi", *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def result(self, completed):
        value = json.loads(completed.stdout)
        return value.get("result", value)

    def stop_service(self):
        self.command("stop")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.result(self.command("status")).get("service") != "running":
                return
            time.sleep(0.05)
        self.fail("test daemon did not stop")

    def test_status_and_stop_do_not_start_service(self):
        status = self.command("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertNotEqual(self.result(status).get("service"), "running")
        stopped = self.command("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertNotEqual(self.result(self.command("status")).get("service"), "running")

    def test_concurrent_first_use_starts_one_service_and_reuses_it(self):
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

    def test_first_use_recovers_stale_socket(self):
        socket_path = Path(self.temp.name) / "control.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(socket_path))
        self.assertTrue(socket_path.exists())
        self.command("raw", "Browser.getVersion")
        self.assertEqual(self.result(self.command("status"))["service"], "running")

    def test_socket_protocol_rejects_version_mismatch_then_accepts_status(self):
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

    def test_command_cli_lists_and_denies_without_a_browser(self):
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
