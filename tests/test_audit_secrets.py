import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

AUDIT = Path(__file__).resolve().parents[1] / "scripts" / "audit-secrets.py"


class HistoricalAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        # Hooks can export selectors for the parent checkout. Every fixture
        # subprocess must operate on this disposable repository instead.
        self.environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        self.value = hashlib.sha256(b"historical-audit-fixture").hexdigest()
        self.git("init", "--quiet")
        self.git("config", "core.hooksPath", os.devnull)
        self.git("config", "commit.gpgSign", "false")
        self.git("config", "user.name", "Audit fixture")
        self.git("config", "user.email", "audit@example.invalid")

    def git(self, *arguments: str) -> str:
        executable = shutil.which("git")
        assert executable is not None
        return subprocess.run(
            [executable, *arguments],
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def commit(self) -> None:
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Synthetic fixture")

    def write_fixture(self, path: str) -> None:
        filename = self.root / path
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_text(f'password = "{self.value}"\n')

    def audit(self, expected: int) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, str(AUDIT)],
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        # Do not let assertion diagnostics disclose the synthetic value.
        self.assertFalse(self.value in result.stdout, "credential value appeared in stdout")
        self.assertFalse(self.value in result.stderr, "credential value appeared in stderr")
        self.assertEqual(result.returncode, expected, result.stderr)
        payload: dict[str, Any] = json.loads(result.stdout)
        return payload

    def assert_history_finding(self, payload: dict[str, Any], path: str) -> None:
        self.assertTrue(
            any(finding["file"].startswith(f"history:{path}:") for finding in payload["findings"])
        )
        for finding in payload["findings"]:
            self.assertEqual(set(finding), {"file", "type", "line"})

    def test_cold_audit_detects_renamed_then_deleted_fixture(self) -> None:
        self.write_fixture("config.py")
        self.commit()
        self.git("mv", "config.py", "poetry.lock")
        self.commit()
        self.git("rm", "poetry.lock")
        self.commit()
        self.assertFalse((self.root / ".git" / "remaldi-secret-audit").exists())

        payload = self.audit(1)
        self.assertEqual(payload["files"], 0)
        self.assertEqual(payload["history_blobs"], 1)
        self.assert_history_finding(payload, "config.py")
        # Finding-bearing contexts remain pending even after clean lockfile
        # contexts have been cached by the first run.
        self.assert_history_finding(self.audit(1), "config.py")

    def test_clean_cached_lockfile_does_not_hide_new_filename_context(self) -> None:
        self.write_fixture("poetry.lock")
        self.commit()
        self.assertEqual(self.audit(0)["findings"], [])
        self.assertEqual(self.audit(0)["scanned"], 0)
        self.git("mv", "poetry.lock", "config.py")
        self.commit()
        self.git("rm", "config.py")
        self.commit()

        self.assert_history_finding(self.audit(1), "config.py")

    def test_directory_contexts_are_not_interchangeable(self) -> None:
        self.write_fixture("swagger/config.py")
        self.commit()
        self.assertEqual(self.audit(0)["findings"], [])
        self.git("mv", "swagger/config.py", "config.py")
        self.commit()
        self.git("rm", "config.py")
        self.commit()

        self.assert_history_finding(self.audit(1), "config.py")

    def test_other_refs_and_unusual_historical_paths_are_scanned(self) -> None:
        self.git("commit", "--quiet", "--allow-empty", "-m", "Empty base")
        base = self.git("rev-parse", "HEAD")
        path = 'nested/tab\tquote"line\nconfig.py'
        self.write_fixture(path)
        self.commit()
        self.git("branch", "fixture-history")
        self.git("checkout", "--quiet", "--detach", base)

        self.assert_history_finding(self.audit(1), path)

    def test_tree_tag_survives_commit_ref_removal(self) -> None:
        self.write_fixture("config.py")
        self.commit()
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("tag", "-a", "fixture-tree", tree, "-m", "Synthetic tree")
        branch = self.git("symbolic-ref", "HEAD")
        self.git("rm", "config.py")
        self.git("update-ref", "-d", branch)

        self.assert_history_finding(self.audit(1), "config.py")

    def test_historical_file_can_later_be_a_directory(self) -> None:
        self.write_fixture("config.py/nested.py")
        self.commit()
        self.git("mv", "config.py/nested.py", "temporary.py")
        (self.root / "config.py").rmdir()
        self.git("mv", "temporary.py", "config.py")
        self.commit()
        self.git("rm", "config.py")
        self.commit()

        payload = self.audit(1)
        self.assert_history_finding(payload, "config.py/nested.py")
        self.assert_history_finding(payload, "config.py")
