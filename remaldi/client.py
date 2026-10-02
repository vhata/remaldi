import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from . import PROTOCOL_VERSION
from .errors import ControlError
from .protocol import MAX_MESSAGE, JsonObject
from .runtime import lock_file, runtime_dir


async def exchange(path: Path, operation: str, params: JsonObject | None = None) -> Any:
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(path / "control.sock", limit=MAX_MESSAGE), 1
    )
    identifier = uuid.uuid4().hex
    try:
        request = {
            "version": PROTOCOL_VERSION,
            "id": identifier,
            "operation": operation,
            "params": params or {},
        }
        encoded = (json.dumps(request) + "\n").encode()
        if len(encoded) > MAX_MESSAGE:
            raise ControlError("message_too_large", "Request exceeds the socket frame limit.")
        writer.write(encoded)
        await writer.drain()
        response = json.loads(await asyncio.wait_for(reader.readline(), 15))
        if response.get("version") != PROTOCOL_VERSION or response.get("id") != identifier:
            raise ControlError("protocol_mismatch", "Unexpected service response.")
        if not response.get("ok"):
            error = response["error"]
            raise ControlError(
                error["code"],
                error["message"],
                **{key: value for key, value in error.items() if key not in {"code", "message"}},
            )
        return response["result"]
    except (TimeoutError, ConnectionError, ValueError) as exc:
        raise ControlError(
            "unknown_outcome",
            "Service response unavailable; command was not replayed.",
            reason=str(exc),
        ) from exc
    finally:
        writer.close()
        await writer.wait_closed()


def start_service(path: Path) -> None:
    # Serialize first-use launches. Service has a separate lifetime lock.
    deadline = time.monotonic() + 8
    lock = None
    while lock is None:
        try:
            lock = lock_file(path / "startup.lock", blocking=False)
        except BlockingIOError as exc:
            if time.monotonic() >= deadline:
                raise ControlError(
                    "startup_timeout", "Timed out waiting for service startup lock."
                ) from exc
            time.sleep(0.05)
    try:
        try:
            asyncio.run(exchange(path, "status"))
            return
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        # A live owner may still be binding its socket; do not launch another.
        try:
            owner = lock_file(path / "service.lock", blocking=False)
        except BlockingIOError:
            process = None
        else:
            os.close(owner)
            package_root = str(Path(__file__).resolve().parent.parent)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = (
                package_root + os.pathsep + environment.get("PYTHONPATH", "")
            )
            with open(path / "startup.log", "wb") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "remaldi", "serve"],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                    cwd=package_root,
                    env=environment,
                )
        while time.monotonic() < deadline:
            try:
                asyncio.run(exchange(path, "status"))
                return
            except (FileNotFoundError, ConnectionRefusedError) as exc:
                if process is not None and process.poll() is not None:
                    raise ControlError(
                        "startup_failed", f"Service exited; see {path / 'startup.log'}."
                    ) from exc
                time.sleep(0.05)
        raise ControlError(
            "startup_timeout",
            f"Service did not become ready; see {path / 'startup.log'}.",
        )
    finally:
        os.close(lock)


def call(operation: str, params: JsonObject | None = None) -> Any:
    path = runtime_dir()
    try:
        return asyncio.run(exchange(path, operation, params))
    except (FileNotFoundError, ConnectionRefusedError):
        if operation in {"status", "stop"}:
            return {"service": "stopped"}
    start_service(path)
    return asyncio.run(exchange(path, operation, params))
