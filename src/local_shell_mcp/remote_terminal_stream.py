"""One-use authenticated WebSocket relay for browser-to-worker PTY streams."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from dataclasses import dataclass, field

from starlette.websockets import WebSocket, WebSocketDisconnect

from .remote import _bearer_token, remote_manager

_LOGGER = logging.getLogger(__name__)


@dataclass
class _PendingTerminal:
    machine: str
    future: asyncio.Future[WebSocket]
    released: asyncio.Event = field(default_factory=asyncio.Event)


_PENDING: dict[str, _PendingTerminal] = {}


class RemoteTerminalProcess:
    def __init__(self, socket: WebSocket, pending: _PendingTerminal):
        self.socket = socket
        self.pending = pending
        self.closed = False

    async def read(self) -> bytes:
        try:
            message = await self.socket.receive()
            if message["type"] == "websocket.disconnect":
                self.closed = True
                return b""
            return message.get("bytes") or b""
        except (WebSocketDisconnect, RuntimeError):
            self.closed = True
            return b""

    async def write(self, data: bytes) -> None:
        if data and not self.closed:
            await self.socket.send_bytes(data)

    async def resize(self, cols: int, rows: int) -> None:
        if not self.closed:
            await self.socket.send_text(json.dumps({"type": "resize", "cols": cols, "rows": rows}))

    async def exit_code(self) -> int | None:
        return 1 if self.closed else None

    async def close(self) -> None:
        self.closed = True
        self.pending.released.set()


async def open_remote_terminal(
    machine: str, session_id: str, cols: int, rows: int
) -> RemoteTerminalProcess:
    ticket = secrets.token_urlsafe(32)
    pending = _PendingTerminal(machine, asyncio.get_running_loop().create_future())
    _PENDING[ticket] = pending
    attached = False
    try:
        result = await remote_manager().call(
            machine,
            "ui_terminal_stream_start",
            {"session_id": session_id, "cols": cols, "rows": rows, "ticket": ticket},
            execution_timeout_s=16,
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("message") or "Remote terminal bridge unavailable")
        socket = await asyncio.wait_for(pending.future, timeout=5)
        attached = True
        return RemoteTerminalProcess(socket, pending)
    finally:
        _PENDING.pop(ticket, None)
        if not attached:
            pending.released.set()


async def remote_terminal_websocket(websocket: WebSocket) -> None:
    ticket = websocket.query_params.get("ticket", "")
    pending = _PENDING.get(ticket)
    if pending is None:
        await websocket.close(code=4403)
        return
    try:
        worker = remote_manager()._worker_by_token(_bearer_token(websocket))
    except (PermissionError, ValueError):
        await websocket.close(code=4403)
        return
    if worker.name != pending.machine or _PENDING.pop(ticket, None) is not pending:
        await websocket.close(code=4403)
        return
    try:
        await websocket.accept()
        pending.future.set_result(websocket)
        await pending.released.wait()
    except Exception as exc:
        if not pending.future.done():
            pending.future.set_exception(exc)
        else:
            _LOGGER.debug("Remote terminal transport closed unexpectedly", exc_info=True)
    finally:
        pending.released.set()
        with contextlib.suppress(WebSocketDisconnect, RuntimeError, OSError):
            await websocket.close()
