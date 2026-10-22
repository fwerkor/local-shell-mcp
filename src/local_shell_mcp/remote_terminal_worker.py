"""Worker-owned, controller-initiated PTY attachment for the Native WebUI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import select
import signal
import struct
import subprocess
from urllib.parse import urlencode, urlsplit, urlunsplit

from .shell_environment import subprocess_env
from .shell_ops import list_shells
from .tmux_helper import resolve_tmux, tmux_socket_name

_ACTIVE_ATTACHMENTS: set[asyncio.Task[None]] = set()


class _TmuxPtyAttachment:
    def __init__(self, session_id: str, cols: int, rows: int):
        import fcntl
        import pty
        import termios

        self.fcntl = fcntl
        self.termios = termios
        selection = resolve_tmux()
        if not selection.path:
            raise RuntimeError("tmux is unavailable")
        env = subprocess_env()
        env.update(
            {
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "TERM_PROGRAM": "local-shell-mcp-webui",
            }
        )
        self.fd, slave = pty.openpty()
        self.process: subprocess.Popen[bytes] | None = None
        try:
            self.resize(cols, rows)
            self.process = subprocess.Popen(
                [
                    selection.path,
                    "-L",
                    tmux_socket_name(),
                    "attach-session",
                    "-t",
                    f"={session_id}",
                ],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                close_fds=True,
                start_new_session=True,
            )
        except BaseException:
            os.close(self.fd)
            raise
        finally:
            os.close(slave)
        os.set_blocking(self.fd, False)

    def resize(self, cols: int, rows: int) -> None:
        self.fcntl.ioctl(self.fd, self.termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        if self.process and self.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGWINCH)

    async def read(self) -> bytes:
        while True:
            try:
                return os.read(self.fd, 65536)
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except OSError:
                return b""

    async def write(self, data: bytes) -> None:
        def write_all() -> None:
            remaining = memoryview(data)
            while remaining:
                try:
                    sent = os.write(self.fd, remaining)
                    if sent <= 0:
                        raise OSError("PTY write stopped")
                    remaining = remaining[sent:]
                except BlockingIOError:
                    select.select([], [self.fd], [], 0.1)

        await asyncio.to_thread(write_all)

    async def close(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self.fd)
        process = self.process
        if process is not None and process.poll() is None:
            # On macOS a tmux client may move out of its initial process group.
            # Fall back to signaling the owned subprocess when the group is inaccessible.
            def signal_process(sig: int) -> None:
                try:
                    os.killpg(process.pid, sig)
                except PermissionError:
                    with contextlib.suppress(ProcessLookupError):
                        process.send_signal(sig)
                except ProcessLookupError:
                    with contextlib.suppress(ProcessLookupError):
                        process.send_signal(sig)

            signal_process(signal.SIGTERM)
            waiter = asyncio.create_task(asyncio.to_thread(process.wait))
            try:
                await asyncio.wait_for(asyncio.shield(waiter), timeout=2)
            except TimeoutError:
                signal_process(signal.SIGKILL)
                await waiter


def _bridge_url(server: str, ticket: str) -> str:
    source = urlsplit(server)
    if source.scheme not in {"http", "https"} or not source.netloc:
        raise ValueError("invalid controller URL for remote terminal")
    return urlunsplit(
        (
            "wss" if source.scheme == "https" else "ws",
            source.netloc,
            source.path.rstrip("/") + "/remote/terminal/ws",
            urlencode({"ticket": ticket}),
            "",
        )
    )


async def _run_attachment(
    session_id: str,
    cols: int,
    rows: int,
    url: str,
    token: str,
    ready: asyncio.Future[None],
) -> None:
    attachment: _TmuxPtyAttachment | None = None
    try:
        from .remote_terminal_ws_client import TerminalWebSocket

        attachment = _TmuxPtyAttachment(session_id, cols, rows)
        async with TerminalWebSocket(url, token) as websocket:
            if not ready.done():
                ready.set_result(None)

            async def upload() -> None:
                while chunk := await attachment.read():
                    await websocket.send(chunk)

            async def download() -> None:
                async for message in websocket:
                    if isinstance(message, bytes):
                        await attachment.write(message)
                    else:
                        with contextlib.suppress(ValueError, TypeError):
                            payload = json.loads(message)
                            if isinstance(payload, dict) and payload.get("type") == "resize":
                                columns, lines = payload.get("cols"), payload.get("rows")
                                if (
                                    type(columns) is int
                                    and type(lines) is int
                                    and 20 <= columns <= 1600
                                    and 8 <= lines <= 500
                                ):
                                    attachment.resize(columns, lines)

            tasks = {asyncio.create_task(upload()), asyncio.create_task(download())}
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        if not ready.done():
            ready.set_exception(exc)
    finally:
        if attachment is not None:
            await attachment.close()


async def start_remote_terminal_stream(
    session_id: str,
    cols: int,
    rows: int,
    ticket: str,
    server: str,
    token: str,
) -> dict[str, str]:
    if os.name != "posix":
        raise RuntimeError("PTY streaming is currently supported on POSIX workers only")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id is required")
    if (
        type(cols) is not int
        or type(rows) is not int
        or not (20 <= cols <= 1600 and 8 <= rows <= 500)
    ):
        raise ValueError("invalid terminal dimensions")
    if not isinstance(ticket, str) or len(ticket) < 32 or not server or not token:
        raise ValueError("invalid terminal relay credentials")
    sessions = (await list_shells()).get("sessions") or []
    if not any(
        row.get("session_id") == session_id and str(row.get("backend") or "").startswith("tmux-")
        for row in sessions
    ):
        raise ValueError("terminal session is not a tmux session")
    ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(
        _run_attachment(session_id, cols, rows, _bridge_url(server, ticket), token, ready)
    )
    _ACTIVE_ATTACHMENTS.add(task)
    task.add_done_callback(_ACTIVE_ATTACHMENTS.discard)
    try:
        await asyncio.wait_for(ready, timeout=12)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    return {"status": "attached"}
