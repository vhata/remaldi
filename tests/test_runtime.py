import os
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from remaldi.errors import ControlError
from remaldi.runtime import SOCKET_PATH_LIMIT, runtime_dir


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="remaldi-path-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_relative_override_returns_absolute_directory(self) -> None:
        with (
            patch.dict(os.environ, REMALDI_RUNTIME_DIR="run"),
            patch("os.getcwd", return_value=self.temp.name),
        ):
            self.assertEqual(runtime_dir(), self.root / "run")

    def test_absolute_socket_path_length_boundary(self) -> None:
        prefix_length = len(os.fsencode(self.root / "control.sock")) + 1
        for socket_length in (SOCKET_PATH_LIMIT - 1, SOCKET_PATH_LIMIT):
            with self.subTest(socket_length=socket_length):
                relative = "r" * (socket_length - prefix_length)
                with (
                    patch.dict(os.environ, REMALDI_RUNTIME_DIR=relative),
                    patch("os.getcwd", return_value=self.temp.name),
                ):
                    if socket_length < SOCKET_PATH_LIMIT:
                        self.assertEqual(runtime_dir(), self.root / relative)
                    else:
                        with self.assertRaises(ControlError) as raised:
                            runtime_dir()
                        self.assertEqual(raised.exception.code, "runtime_path_too_long")

    def test_absolute_socket_path_length_counts_encoded_bytes(self) -> None:
        relative = "é" * 40
        socket_path = self.root / relative / "control.sock"
        self.assertLess(len(str(socket_path)), SOCKET_PATH_LIMIT)
        self.assertGreaterEqual(len(os.fsencode(socket_path)), SOCKET_PATH_LIMIT)
        with (
            patch.dict(os.environ, REMALDI_RUNTIME_DIR=relative),
            patch("os.getcwd", return_value=self.temp.name),
            self.assertRaises(ControlError) as raised,
        ):
            runtime_dir()
        self.assertEqual(raised.exception.code, "runtime_path_too_long")

    def test_relative_symlink_runtime_is_rejected(self) -> None:
        (self.root / "link").symlink_to(self.root, target_is_directory=True)
        with (
            patch.dict(os.environ, REMALDI_RUNTIME_DIR="link"),
            chdir(self.root),
            self.assertRaises(ControlError) as raised,
        ):
            runtime_dir()
        self.assertEqual(raised.exception.code, "unsafe_runtime_directory")
