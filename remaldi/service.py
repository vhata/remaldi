import asyncio
import json
import logging
import os
import signal
from collections.abc import Awaitable, Callable, Set
from logging.handlers import RotatingFileHandler
from typing import Any

from . import PROTOCOL_VERSION
from .adapter import VivaldiAdapter
from .browser import Browser
from .errors import ControlError
from .protocol import MAX_MESSAGE, JsonObject
from .runtime import lock_file, runtime_dir

REQUEST_TIMEOUT = 12


class Service:
    def __init__(self, endpoint: str) -> None:
        self.browser = Browser(endpoint)
        self.adapter = VivaldiAdapter(self.browser)
        self.browser.on_change = self.adapter.invalidate
        self.stopping = asyncio.Event()
        self.operations: dict[str, Callable[[JsonObject], Awaitable[Any]]] = {
            "state": self.state,
            "workspace.switch": self.workspace_switch,
        }

    async def state(self, params: JsonObject) -> JsonObject:
        self.validate(params, {"refresh"})
        if "refresh" in params and not isinstance(params["refresh"], bool):
            raise ControlError("invalid_parameters", "refresh must be boolean.")
        return await self.adapter.snapshot(params.get("refresh", False))

    async def workspace_switch(self, params: JsonObject) -> Any:
        self.validate(params, {"workspace_id", "window_id"}, {"workspace_id"})
        return await self.adapter.switch_workspace(**params)

    @staticmethod
    def validate(params: JsonObject, allowed: Set[str], required: Set[str] = frozenset()) -> None:
        if set(params) - allowed or required - set(params):
            raise ControlError("invalid_parameters", "Unexpected or missing operation parameters.")

    async def dispatch(self, request: object) -> Any:
        if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
            raise ControlError("protocol_mismatch", "Expected protocol version 1.")
        operation = request.get("operation")
        params = request.get("params", {})
        if not isinstance(operation, str) or not isinstance(params, dict):
            raise ControlError(
                "invalid_request", "Operation must be a string and params an object."
            )
        if operation == "status":
            return {
                "service": "running",
                "pid": os.getpid(),
                "protocol": PROTOCOL_VERSION,
                "browser": {
                    "state": self.browser.state,
                    "detail": self.browser.detail,
                    "events": self.browser.event_support,
                },
                "targets": [
                    {"id": item.get("id"), "type": item.get("type")}
                    for item in self.browser.targets
                ],
            }
        if operation == "stop":
            self.stopping.set()
            return {"service": "stopping"}
        if operation == "raw":
            self.validate(params, {"method", "params", "target"}, {"method"})
            if (
                not isinstance(params["method"], str)
                or not isinstance(params.get("params", {}), dict)
                or (params.get("target") is not None and not isinstance(params["target"], str))
            ):
                raise ControlError(
                    "invalid_parameters", "Invalid DevTools method, params, or target."
                )
            try:
                return await self.browser.request(**params)
            finally:
                self.adapter.invalidate()
        handler = self.operations.get(operation)
        if handler is None:
            raise ControlError("unknown_operation", f"Unknown operation: {operation}")
        return await handler(params)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        identifier = None
        try:
            while not self.stopping.is_set():
                line = await asyncio.wait_for(reader.readline(), 30)
                if not line:
                    break
                try:
                    request = json.loads(line)
                    identifier = request.get("id") if isinstance(request, dict) else None
                    try:
                        result = await asyncio.wait_for(self.dispatch(request), REQUEST_TIMEOUT)
                    except TimeoutError as exc:
                        raise ControlError(
                            "unknown_outcome",
                            "Operation deadline exceeded; pending work was cancelled and the command was not replayed.",
                        ) from exc
                    response = {
                        "version": PROTOCOL_VERSION,
                        "id": identifier,
                        "ok": True,
                        "result": result,
                    }
                except (ValueError, TypeError) as exc:
                    response = {
                        "version": PROTOCOL_VERSION,
                        "id": identifier,
                        "ok": False,
                        "error": {"code": "invalid_request", "message": str(exc)},
                    }
                except ControlError as exc:
                    response = {
                        "version": PROTOCOL_VERSION,
                        "id": identifier,
                        "ok": False,
                        "error": exc.as_dict(),
                    }
                encoded = (json.dumps(response) + "\n").encode()
                if len(encoded) > MAX_MESSAGE:
                    encoded = (
                        json.dumps(
                            {
                                "version": PROTOCOL_VERSION,
                                "id": identifier,
                                "ok": False,
                                "error": {
                                    "code": "response_too_large",
                                    "message": "Operation completed but its result exceeds the socket frame limit; it was not replayed.",
                                },
                            }
                        )
                        + "\n"
                    ).encode()
                writer.write(encoded)
                await writer.drain()
        except (ConnectionError, TimeoutError, ValueError):
            pass
        except Exception:
            logging.exception("Client request failed")
        finally:
            writer.close()
            await writer.wait_closed()


async def serve(endpoint: str) -> None:
    path = runtime_dir()
    try:
        owner = lock_file(path / "service.lock", blocking=False)
    except BlockingIOError as exc:
        raise ControlError(
            "already_running", "A service already owns this runtime directory."
        ) from exc
    socket = path / "control.sock"
    service = Service(endpoint)
    monitor = None
    server = None
    handlers: set[asyncio.Task[None]] = set()
    try:
        socket.unlink(missing_ok=True)
        handler = RotatingFileHandler(path / "service.log", maxBytes=1024 * 1024, backupCount=2)
        logging.basicConfig(
            level=logging.INFO,
            handlers=[handler],
            format="%(asctime)s %(levelname)s %(message)s",
        )

        def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            task = asyncio.create_task(service.handle(reader, writer))
            handlers.add(task)
            task.add_done_callback(handlers.discard)

        server = await asyncio.start_unix_server(accept, path=socket, limit=MAX_MESSAGE)
        os.chmod(socket, 0o600)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, service.stopping.set)
        monitor = asyncio.create_task(service.browser.monitor())
        logging.info("Service ready pid=%s", os.getpid())
        await service.stopping.wait()
    finally:
        if server:
            server.close()
            await server.wait_closed()
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if handlers:
            _, pending = await asyncio.wait(handlers, timeout=0.2)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await service.browser.close()
        socket.unlink(missing_ok=True)
        os.close(owner)
