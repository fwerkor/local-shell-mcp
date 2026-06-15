from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import audit
from .fs_ops import relative_display, resolve_path
from .settings import get_settings

CONPTY_BUFFER_BYTES = 1_000_000
CONPTY_READ_CHARS = 65536

try:
    import winpty
except ImportError:  # pragma: no cover - covered through monkeypatched module state.
    winpty = None

_CONPTY_SHELL_SESSIONS: dict[str, ConPtyShellSession] = {}


@dataclass
class TailBuffer:
    keep_bytes: int
    data: bytearray
    total_bytes: int = 0

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.total_bytes += len(chunk)
        self.data.extend(chunk)
        overflow = len(self.data) - self.keep_bytes
        if overflow > 0:
            del self.data[:overflow]


@dataclass
class ConPtyShellSession:
    session_id: str
    process: Any
    cwd: Path
    command: str
    created: int
    output: TailBuffer
    reader: asyncio.Task[None] | None
    lock: asyncio.Lock


def is_available() -> bool:
    return winpty is not None and hasattr(winpty, "PtyProcess")


def has_session(session_id: str) -> bool:
    return session_id in _CONPTY_SHELL_SESSIONS


def _session_name(name: str | None = None) -> str:
    base = name or f"mcp-{uuid.uuid4().hex[:8]}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", base)[:64]


def _subprocess_env() -> dict[str, str]:
    settings = get_settings()
    blocked = set(settings.shell_env_blocklist)
    prefixes = tuple(settings.shell_env_blocked_prefixes)
    return {
        key: value
        for key, value in os.environ.items()
        if key not in blocked and not key.startswith(prefixes)
    }


def _shell_program_name(shell: str) -> str:
    return Path(shell).name.lower()


def _shell_command_args(command: str) -> list[str]:
    settings = get_settings()
    shell = settings.shell_executable
    name = _shell_program_name(shell)
    ps = "power" + "shell"
    if name in {ps + ".exe", ps, "pwsh.exe", "pwsh"}:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    if name in {"cmd.exe", "cmd"}:
        return [shell, "/S", "/C", command]
    return [shell, "-lc", command]


def _persistent_shell_args(command: str | None = None) -> list[str]:
    settings = get_settings()
    if command:
        return _shell_command_args(command)
    return [settings.shell_executable]


def _spawn_command(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


def _spawn_pty(argv: list[str], cwd: Path) -> Any:
    if not is_available():
        raise RuntimeError("pywinpty is not available")
    assert winpty is not None
    spawn = winpty.PtyProcess.spawn
    env = _subprocess_env()
    try:
        return spawn(argv, cwd=str(cwd), env=env)
    except TypeError:
        return spawn(_spawn_command(argv), cwd=str(cwd), env=env)


def _pty_is_alive(process: Any) -> bool:
    isalive = getattr(process, "isalive", None)
    if callable(isalive):
        return bool(isalive())
    return getattr(process, "exitstatus", None) is None


def _read_pty(process: Any) -> str | bytes:
    try:
        return process.read(CONPTY_READ_CHARS)
    except TypeError:
        return process.read()


async def _read_conpty_shell(session: ConPtyShellSession) -> None:
    try:
        while _pty_is_alive(session.process):
            chunk = await asyncio.to_thread(_read_pty, session.process)
            if not chunk:
                await asyncio.sleep(0.02)
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode(errors="replace")
            session.output.append(chunk)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        session.output.append(f"\n<conpty shell reader stopped: {exc!r}>\n".encode())


def _get_session(session_id: str) -> ConPtyShellSession:
    session = _CONPTY_SHELL_SESSIONS.get(session_id)
    if session is None:
        raise RuntimeError(f"Persistent shell session not found: {session_id}")
    if not _pty_is_alive(session.process):
        _CONPTY_SHELL_SESSIONS.pop(session_id, None)
        raise RuntimeError(f"Persistent shell session exited: {session_id}")
    return session


async def start_shell(
    cwd: str = ".",
    name: str | None = None,
    command: str | None = None,
    check_command_policy=None,
) -> dict:
    resolved_cwd = resolve_path(cwd, must_exist=True)
    max_sessions = max(1, get_settings().max_tmux_sessions)
    active = [
        session_id
        for session_id, session in list(_CONPTY_SHELL_SESSIONS.items())
        if _pty_is_alive(session.process)
    ]
    for session_id in list(_CONPTY_SHELL_SESSIONS):
        if session_id not in active:
            _CONPTY_SHELL_SESSIONS.pop(session_id, None)
    if len(active) >= max_sessions:
        raise RuntimeError(f"Refusing to start more than {max_sessions} persistent shell sessions")

    session_id = _session_name(name)
    if session_id in _CONPTY_SHELL_SESSIONS:
        raise RuntimeError(f"Persistent shell session already exists: {session_id}")

    initial = command or get_settings().shell_executable
    if check_command_policy is not None:
        check_command_policy(initial)
    process = await asyncio.to_thread(_spawn_pty, _persistent_shell_args(command), resolved_cwd)
    session = ConPtyShellSession(
        session_id=session_id,
        process=process,
        cwd=resolved_cwd,
        command=initial,
        created=int(time.time()),
        output=TailBuffer(CONPTY_BUFFER_BYTES, bytearray()),
        reader=None,
        lock=asyncio.Lock(),
    )
    session.reader = asyncio.create_task(_read_conpty_shell(session))
    _CONPTY_SHELL_SESSIONS[session_id] = session
    audit("shell_start", session=session_id, cwd=str(resolved_cwd), command=initial, backend="conpty")
    return {
        "session_id": session_id,
        "cwd": relative_display(resolved_cwd),
        "command": initial,
        "backend": "conpty",
    }


async def send_shell(session_id: str, input_text: str, enter: bool = True) -> dict:
    session = _get_session(session_id)
    data = input_text + ("\r" if enter else "")
    async with session.lock:
        await asyncio.to_thread(session.process.write, data)
    audit("shell_send", session=session_id, bytes=len(input_text.encode()), enter=enter, backend="conpty")
    return {"session_id": session_id, "sent_bytes": len(input_text.encode()), "enter": enter}


async def read_shell(session_id: str, lines: int = 200) -> dict:
    session = _CONPTY_SHELL_SESSIONS.get(session_id)
    if session is None:
        raise RuntimeError(f"Persistent shell session not found: {session_id}")
    output = bytes(session.output.data).decode(errors="replace")
    if lines > 0:
        split = output.splitlines()
        if split:
            output = "\n".join(split[-max(1, lines):])
            if bytes(session.output.data).endswith((b"\n", b"\r")):
                output += "\n"
        else:
            output = ""
    audit("shell_read", session=session_id, lines=lines, backend="conpty")
    return {"session_id": session_id, "output": output}


async def kill_shell(session_id: str) -> dict:
    session = _CONPTY_SHELL_SESSIONS.pop(session_id, None)
    if session is None:
        return {"session_id": session_id, "killed": False, "stderr": "Persistent shell session not found"}

    stderr = ""
    try:
        try:
            await asyncio.to_thread(session.process.terminate, force=True)
        except TypeError:
            await asyncio.to_thread(session.process.terminate)
    except Exception as exc:
        stderr = repr(exc)

    if session.reader is not None:
        session.reader.cancel()
        await asyncio.gather(session.reader, return_exceptions=True)
    audit("shell_kill", session=session_id, ok=not stderr, backend="conpty")
    return {"session_id": session_id, "killed": not stderr, "stderr": stderr}


async def list_shells() -> dict:
    sessions = []
    for session_id, session in list(_CONPTY_SHELL_SESSIONS.items()):
        if not _pty_is_alive(session.process):
            _CONPTY_SHELL_SESSIONS.pop(session_id, None)
            continue
        sessions.append(
            {
                "session_id": session_id,
                "created": str(session.created),
                "attached": "0",
                "backend": "conpty",
            }
        )
    return {"sessions": sessions}
