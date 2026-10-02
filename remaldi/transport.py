"""Correlated DevTools transport; transmitted requests are never replayed."""

import asyncio
import json
from collections.abc import Callable
from typing import cast

from websockets.asyncio.client import ClientConnection, connect

from .errors import ControlError
from .protocol import JsonObject


class CDPConnection:
    def __init__(self, url: str, timeout: float = 5) -> None:
        self.url = url
        self.timeout = timeout
        self.socket: ClientConnection | None = None
        self.reader: asyncio.Task[None] | None = None
        self.pending: dict[int, asyncio.Future[JsonObject]] = {}
        self.sequence = 0
        self.on_event: Callable[[JsonObject], None] = lambda event: None

    async def connect(self) -> None:
        self.socket = await connect(
            self.url, open_timeout=self.timeout, proxy=None, max_size=8 * 1024 * 1024
        )
        self.reader = asyncio.create_task(self._read())

    @property
    def connected(self) -> bool:
        return self.reader is not None and not self.reader.done()

    async def _read(self) -> None:
        assert self.socket is not None
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                if "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        future.set_result(message)
                else:
                    self.on_event(message)
        except Exception:
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(
                        ControlError(
                            "unknown_outcome",
                            "Connection lost after request transmission; request was not replayed.",
                        )
                    )

    async def request(self, method: str, params: JsonObject | None = None) -> JsonObject:
        if not self.connected:
            raise ControlError("disconnected", "DevTools connection is unavailable.")
        assert self.socket is not None
        self.sequence += 1
        identifier = self.sequence
        future: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            await self.socket.send(
                json.dumps({"id": identifier, "method": method, "params": params or {}})
            )
            response = await asyncio.wait_for(future, self.timeout)
            if "error" in response:
                raise ControlError(
                    "devtools_error",
                    "DevTools rejected the request.",
                    error=response["error"],
                )
            return cast(JsonObject, response.get("result", {}))
        except (TimeoutError, OSError) as exc:
            raise ControlError(
                "unknown_outcome",
                "Request may have executed; it was not replayed.",
                reason=str(exc),
            ) from exc
        except ControlError:
            raise
        except Exception as exc:
            raise ControlError(
                "unknown_outcome",
                "Request transmission failed; it was not replayed.",
                reason=str(exc),
            ) from exc
        finally:
            self.pending.pop(identifier, None)

    async def close(self) -> None:
        if self.socket:
            await self.socket.close()
        if self.reader:
            await self.reader
