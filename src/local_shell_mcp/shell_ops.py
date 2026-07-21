from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
import weakref
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from . import conpty_ops
from .audit import audit
from .fs_ops import relative_display, resolve_path
from .models import CommandResult
from .settings import get_settings
from .shell_environment import (
    persistent_shell_args,
    shell_command_args,
    subprocess_env,
)
from .shell_environment import (
    shell_program_name as _shell_program_name,
)
from .tmux_helper import resolve_tmux, tmux_socket_name

PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S = 10
PUBLIC_RUN_SHELL_TIMEOUT_CAP_S = 120
PUBLIC_TOOL_WATCHDOG_TIMEOUT_S = 130
GRACEFUL_TERMINATION_TIMEOUT_S = 5
KILL_TERMINATION_TIMEOUT_S = 2
READER_DRAIN_TIMEOUT_S = 2
_COMMAND_SEMAPHORE: asyncio.Semaphore | None = None
_COMMAND_SEMAPHORE_SIZE: int | None = None
_NATIVE_SHELL_SESSIONS = {}
_SHELL_START_LOCKS_GUARD = threading.Lock()
_SHELL_START_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
NATIVE_SHELL_BUFFER_BYTES = 1_000_000
PERSISTENT_SHELL_MIN_COLUMNS = 20
PERSISTENT_SHELL_MAX_COLUMNS = 1_600
PERSISTENT_SHELL_MIN_ROWS = 3
PERSISTENT_SHELL_MAX_ROWS = 500


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

    @property
    def truncated(self) -> bool:
        return self.total_bytes > len(self.data)


@dataclass
class NativeShellSession:
    session_id: str
    process: object
    cwd: Path
    command: str
    created: int
    output: TailBuffer
    readers: list
    lock: object


def check_command_policy(command: str) -> None:
    settings = get_settings()
    normalized = command.casefold()
    for denied in settings.command_denylist:
        if denied and denied.casefold() in normalized:
            raise PermissionError(f"Command contains denylisted fragment: {denied!r}")


def clamp_timeout(timeout_s: int | None) -> int:
    settings = get_settings()
    timeout = timeout_s or settings.default_timeout_s
    return max(1, min(timeout, settings.max_timeout_s))


def public_run_shell_timeout(timeout_s: int | None) -> int:
    if timeout_s is not None and timeout_s > PUBLIC_RUN_SHELL_TIMEOUT_CAP_S:
        raise ValueError(
            f"timeout_s must be <= {PUBLIC_RUN_SHELL_TIMEOUT_CAP_S} seconds for public run_shell"
        )
    return max(
        1, min(timeout_s or PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S, PUBLIC_RUN_SHELL_TIMEOUT_CAP_S)
    )


def _shared_tail_bytes(stdout: bytes, stderr: bytes, limit: int) -> tuple[bytes, bytes, bool]:
    total = len(stdout) + len(stderr)
    if total <= limit:
        return stdout, stderr, False

    stdout_keep = min(len(stdout), limit // 2)
    stderr_keep = min(len(stderr), limit // 2)
    remaining = limit - stdout_keep - stderr_keep
    if remaining > 0:
        stdout_extra = min(remaining, len(stdout) - stdout_keep)
        stdout_keep += stdout_extra
        remaining -= stdout_extra
    if remaining > 0:
        stderr_keep += min(remaining, len(stderr) - stderr_keep)

    return (
        stdout[-stdout_keep:] if stdout_keep else b"",
        stderr[-stderr_keep:] if stderr_keep else b"",
        True,
    )


def clamp_output(
    stdout: str, stderr: str, max_output_bytes: int | None = None
) -> tuple[str, str, bool]:
    limit = _effective_output_limit(max_output_bytes)
    stdout_bytes, stderr_bytes, truncated = _shared_tail_bytes(
        stdout.encode(), stderr.encode(), limit
    )
    return (
        stdout_bytes.decode(errors="replace"),
        stderr_bytes.decode(errors="replace"),
        truncated,
    )


def _effective_output_limit(max_output_bytes: int | None = None) -> int:
    settings = get_settings()
    configured = max(1, settings.max_output_bytes)
    if max_output_bytes is None:
        return configured
    return max(1, min(max_output_bytes, configured))


def _command_semaphore() -> asyncio.Semaphore:
    global _COMMAND_SEMAPHORE, _COMMAND_SEMAPHORE_SIZE
    size = max(1, get_settings().max_concurrent_commands)
    if _COMMAND_SEMAPHORE is None or size != _COMMAND_SEMAPHORE_SIZE:
        _COMMAND_SEMAPHORE = asyncio.Semaphore(size)
        _COMMAND_SEMAPHORE_SIZE = size
    return _COMMAND_SEMAPHORE


def _shell_start_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    with _SHELL_START_LOCKS_GUARD:
        lock = _SHELL_START_LOCKS.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _SHELL_START_LOCKS[loop] = lock
        return lock


def quote_shell_argument(value: str) -> str:
    name = _shell_program_name(get_settings().shell_executable)
    powershell = "power" + "shell"
    if name in {powershell + ".exe", powershell, "pwsh.exe", "pwsh"}:
        return "'" + value.replace("'", "''") + "'"
    if name in {"cmd.exe", "cmd"}:
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def quote_shell_executable(value: str) -> str:
    quoted = quote_shell_argument(value)
    name = _shell_program_name(get_settings().shell_executable)
    powershell = "power" + "shell"
    if name in {powershell + ".exe", powershell, "pwsh.exe", "pwsh"}:
        return f"& {quoted}"
    return quoted


def _shell_command_args(command: str) -> list[str]:
    return shell_command_args(get_settings().shell_executable, command)


def _persistent_shell_args(command: str | None = None) -> list[str]:
    return persistent_shell_args(get_settings().shell_executable, command)


def _use_native_persistent_shell_backend() -> bool:
    return sys.platform == "win32"


def _use_windows_persistent_shell_backend() -> bool:
    return _use_native_persistent_shell_backend()


async def _spawn_process(command: str, cwd: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *_shell_command_args(command),
        cwd=cwd,
        env=subprocess_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=(sys.platform != "win32"),
    )


async def _read_stream_tail(stream: asyncio.StreamReader | None, tail: TailBuffer) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return
        tail.append(chunk)


async def _wait_for_process_exit(proc: asyncio.subprocess.Process, timeout_s: int) -> bool:
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        return True
    except TimeoutError:
        return False


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> str:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        proc.terminate()

    output = await _wait_for_process_exit(proc, GRACEFUL_TERMINATION_TIMEOUT_S)
    if output:
        return ""

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        proc.kill()

    output = await _wait_for_process_exit(proc, KILL_TERMINATION_TIMEOUT_S)
    if output:
        return ""
    return "Process did not exit after SIGKILL"


async def _finish_reader_tasks(
    tasks: list[asyncio.Task[None]], timeout_s: float = READER_DRAIN_TIMEOUT_S
) -> None:
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_s)
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _close_process_transport(proc: asyncio.subprocess.Process) -> None:
    """Close subprocess pipes before the owning event loop shuts down.

    Windows Proactor transports can otherwise survive until garbage collection and emit an
    unraisable ``Event loop is closed`` exception after an otherwise successful call. The
    private transport fallback is isolated here because asyncio Process has no public close.
    """

    if proc.stdin is not None:
        proc.stdin.close()
        with suppress(OSError, TimeoutError):
            await asyncio.wait_for(proc.stdin.wait_closed(), timeout=1)
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        transport.close()
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def run_shell(
    command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None
) -> CommandResult:
    check_command_policy(command)
    resolved_cwd = resolve_path(cwd, must_exist=True)
    start = time.time()
    audit("run_shell_start", command=command, cwd=str(resolved_cwd))
    timeout = clamp_timeout(timeout_s)

    proc: asyncio.subprocess.Process | None = None
    timed_out = False
    termination_error = ""
    output_limit = _effective_output_limit(max_output_bytes)
    stdout_tail = TailBuffer(output_limit, bytearray())
    stderr_tail = TailBuffer(output_limit, bytearray())
    reader_tasks: list[asyncio.Task[None]] = []

    async def spawn_and_wait() -> None:
        nonlocal proc
        proc = await _spawn_process(command, str(resolved_cwd))
        reader_tasks.extend(
            [
                asyncio.create_task(_read_stream_tail(proc.stdout, stdout_tail)),
                asyncio.create_task(_read_stream_tail(proc.stderr, stderr_tail)),
            ]
        )
        await proc.wait()

    semaphore = _command_semaphore()
    acquired = False
    try:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
            acquired = True
            elapsed = max(0.0, time.time() - start)
            remaining_timeout = max(0.001, timeout - elapsed)
            await asyncio.wait_for(spawn_and_wait(), timeout=remaining_timeout)
        except TimeoutError:
            timed_out = True
            if proc is None:
                reader_tasks = []
                termination_error = "Timed out while starting subprocess"
            else:
                termination_error = await _terminate_process_group(proc)
        except asyncio.CancelledError:
            if proc is not None:
                await asyncio.shield(_terminate_process_group(proc))
            raise
    finally:
        if acquired:
            semaphore.release()

    try:
        if reader_tasks:
            await _finish_reader_tasks(reader_tasks)
    finally:
        if proc is not None:
            await _close_process_transport(proc)

    if termination_error:
        stderr_tail.append(termination_error.encode())

    stdout_b, stderr_b, total_truncated = _shared_tail_bytes(
        bytes(stdout_tail.data), bytes(stderr_tail.data), output_limit
    )
    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    truncated = stdout_tail.truncated or stderr_tail.truncated or total_truncated
    duration_ms = int((time.time() - start) * 1000)
    result = CommandResult(
        ok=(proc is not None and proc.returncode == 0 and not timed_out),
        exit_code=proc.returncode if proc is not None else None,
        timed_out=timed_out,
        duration_ms=duration_ms,
        cwd=relative_display(resolved_cwd),
        command=command,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated,
    )
    audit(
        "run_shell_end",
        command=command,
        cwd=str(resolved_cwd),
        exit_code=proc.returncode if proc is not None else None,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated=truncated,
    )
    return result


async def public_run_shell(
    command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None
) -> CommandResult:
    return await run_shell(command, cwd, public_run_shell_timeout(timeout_s), max_output_bytes)


def _tmux_session_name(name: str | None = None) -> str:
    base = name or f"mcp-{uuid.uuid4().hex[:8]}"
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", base.strip())[:64].strip(".-")
    return cleaned or f"mcp-{uuid.uuid4().hex[:8]}"


async def tmux(args: list[str], timeout_s: int = 10) -> CommandResult:
    selection = resolve_tmux()
    if selection.path is None:
        raise RuntimeError("tmux is unavailable and no bundled helper matches this platform")
    cmd = " ".join(shlex.quote(x) for x in [selection.path, "-L", tmux_socket_name(), *args])
    return await run_shell(cmd, cwd=".", timeout_s=timeout_s)


async def _read_native_shell_stream(
    session: NativeShellSession, stream: asyncio.StreamReader | None
) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                return
            session.output.append(chunk)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        session.output.append(f"\n<native shell reader stopped: {exc!r}>\n".encode())


def _get_native_session(session_id: str) -> NativeShellSession:
    session = _NATIVE_SHELL_SESSIONS.get(session_id)
    if session is None:
        raise RuntimeError(f"Persistent shell session not found: {session_id}")
    if session.process.returncode is not None:
        _NATIVE_SHELL_SESSIONS.pop(session_id, None)
        raise RuntimeError(
            f"Persistent shell session exited with code {session.process.returncode}: {session_id}"
        )
    return session


async def _native_start_shell(
    cwd: str = ".", name: str | None = None, command: str | None = None
) -> dict:
    resolved_cwd = resolve_path(cwd, must_exist=True)
    max_sessions = max(1, get_settings().max_tmux_sessions)
    active = [
        session_id
        for session_id, session in list(_NATIVE_SHELL_SESSIONS.items())
        if session.process.returncode is None
    ]
    for session_id in list(_NATIVE_SHELL_SESSIONS):
        if session_id not in active:
            _NATIVE_SHELL_SESSIONS.pop(session_id, None)
    if len(active) >= max_sessions:
        raise RuntimeError(f"Refusing to start more than {max_sessions} persistent shell sessions")

    session_id = _tmux_session_name(name)
    if session_id in _NATIVE_SHELL_SESSIONS:
        raise RuntimeError(f"Persistent shell session already exists: {session_id}")

    initial = command or get_settings().shell_executable
    check_command_policy(initial)
    proc = await asyncio.create_subprocess_exec(
        *_persistent_shell_args(command),
        cwd=str(resolved_cwd),
        env=subprocess_env(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=(sys.platform != "win32"),
    )
    session = NativeShellSession(
        session_id=session_id,
        process=proc,
        cwd=resolved_cwd,
        command=initial,
        created=int(time.time()),
        output=TailBuffer(NATIVE_SHELL_BUFFER_BYTES, bytearray()),
        readers=[],
        lock=asyncio.Lock(),
    )
    session.readers.append(asyncio.create_task(_read_native_shell_stream(session, proc.stdout)))
    _NATIVE_SHELL_SESSIONS[session_id] = session
    audit(
        "shell_start", session=session_id, cwd=str(resolved_cwd), command=initial, backend="native"
    )
    return {
        "session_id": session_id,
        "cwd": relative_display(resolved_cwd),
        "command": initial,
        "backend": "native",
    }


async def _native_send_shell(session_id: str, input_text: str, enter: bool = True) -> dict:
    session = _get_native_session(session_id)
    if session.process.stdin is None:
        raise RuntimeError(f"Persistent shell session has no stdin: {session_id}")
    newline = "\r\n" if sys.platform == "win32" else "\n"
    data = input_text + (newline if enter else "")
    async with session.lock:
        session.process.stdin.write(data.encode())
        await session.process.stdin.drain()
    audit(
        "shell_send",
        session=session_id,
        bytes=len(input_text.encode()),
        enter=enter,
        backend="native",
    )
    return {"session_id": session_id, "sent_bytes": len(input_text.encode()), "enter": enter}


async def _native_read_shell(session_id: str, lines: int = 200) -> dict:
    session = _NATIVE_SHELL_SESSIONS.get(session_id)
    if session is None:
        raise RuntimeError(f"Persistent shell session not found: {session_id}")
    output = bytes(session.output.data).decode(errors="replace")
    if lines > 0:
        split = output.splitlines()
        if split:
            output = "\n".join(split[-max(1, lines) :])
            if bytes(session.output.data).endswith((b"\n", b"\r")):
                output += "\n"
        else:
            output = ""
    audit("shell_read", session=session_id, lines=lines, backend="native")
    return {"session_id": session_id, "output": output}


async def _native_stop_process(proc: asyncio.subprocess.Process) -> str:
    if proc.returncode is not None:
        return ""
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except Exception:
        proc.terminate()

    if await _wait_for_process_exit(proc, GRACEFUL_TERMINATION_TIMEOUT_S):
        return ""

    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        proc.kill()

    if await _wait_for_process_exit(proc, KILL_TERMINATION_TIMEOUT_S):
        return ""
    return "Process did not exit after termination"


async def _native_kill_shell(session_id: str) -> dict:
    session = _NATIVE_SHELL_SESSIONS.pop(session_id, None)
    if session is None:
        return {
            "session_id": session_id,
            "killed": False,
            "stderr": "Persistent shell session not found",
        }
    stderr = await _native_stop_process(session.process)
    for reader in session.readers:
        reader.cancel()
    if session.readers:
        await asyncio.gather(*session.readers, return_exceptions=True)
    await _close_process_transport(session.process)
    audit("shell_kill", session=session_id, ok=not stderr, backend="native")
    return {"session_id": session_id, "killed": not stderr, "stderr": stderr}


async def _native_list_shells() -> dict:
    sessions = []
    for session_id, session in list(_NATIVE_SHELL_SESSIONS.items()):
        if session.process.returncode is not None:
            _NATIVE_SHELL_SESSIONS.pop(session_id, None)
            continue
        sessions.append(
            {
                "session_id": session_id,
                "created": str(session.created),
                "attached": "0",
                "backend": "native",
            }
        )
    return {"sessions": sessions}


async def _start_shell_unlocked(
    cwd: str = ".", name: str | None = None, command: str | None = None
) -> dict:
    if _use_windows_persistent_shell_backend():
        if conpty_ops.is_available():
            return await conpty_ops.start_shell(cwd, name, command, check_command_policy)
        return await _native_start_shell(cwd, name, command)

    selection = resolve_tmux()
    if selection.path is None:
        return await _native_start_shell(cwd, name, command)

    resolved_cwd = resolve_path(cwd, must_exist=True)
    sessions = await list_shells()
    max_sessions = max(1, get_settings().max_tmux_sessions)
    if len(sessions.get("sessions", [])) >= max_sessions:
        raise RuntimeError(f"Refusing to start more than {max_sessions} persistent shell sessions")
    session = _tmux_session_name(name)
    initial = command or get_settings().shell_executable
    check_command_policy(initial)
    cmd = [
        "new-session",
        "-d",
        "-s",
        session,
        "-c",
        str(resolved_cwd),
        initial,
    ]
    result = await tmux(cmd)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    backend = f"tmux-{selection.source}"
    audit("shell_start", session=session, cwd=str(resolved_cwd), command=initial, backend=backend)
    return {
        "session_id": session,
        "cwd": relative_display(resolved_cwd),
        "command": initial,
        "backend": backend,
    }


async def start_shell(cwd: str = ".", name: str | None = None, command: str | None = None) -> dict:
    async with _shell_start_lock():
        return await _start_shell_unlocked(cwd, name, command)


def _validate_persistent_shell_size(cols: int, rows: int) -> tuple[int, int]:
    columns = int(cols)
    lines = int(rows)
    if not PERSISTENT_SHELL_MIN_COLUMNS <= columns <= PERSISTENT_SHELL_MAX_COLUMNS:
        raise ValueError(
            f"cols must be between {PERSISTENT_SHELL_MIN_COLUMNS} and "
            f"{PERSISTENT_SHELL_MAX_COLUMNS}"
        )
    if not PERSISTENT_SHELL_MIN_ROWS <= lines <= PERSISTENT_SHELL_MAX_ROWS:
        raise ValueError(
            f"rows must be between {PERSISTENT_SHELL_MIN_ROWS} and "
            f"{PERSISTENT_SHELL_MAX_ROWS}"
        )
    return columns, lines


async def _native_resize_shell(session_id: str, cols: int, rows: int) -> dict:
    _get_native_session(session_id)
    return {
        "session_id": session_id,
        "cols": cols,
        "rows": rows,
        "resized": False,
        "backend": "native",
    }


async def resize_shell(session_id: str, cols: int, rows: int) -> dict:
    columns, lines = _validate_persistent_shell_size(cols, rows)
    if _use_windows_persistent_shell_backend():
        if conpty_ops.has_session(session_id):
            return await conpty_ops.resize_shell(session_id, columns, lines)
        return await _native_resize_shell(session_id, columns, lines)
    if session_id in _NATIVE_SHELL_SESSIONS or resolve_tmux().path is None:
        return await _native_resize_shell(session_id, columns, lines)

    result = await tmux(
        [
            "resize-window",
            "-t",
            session_id,
            "-x",
            str(columns),
            "-y",
            str(lines),
        ]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    return {
        "session_id": session_id,
        "cols": columns,
        "rows": lines,
        "resized": True,
        "backend": "tmux",
    }


async def send_shell(session_id: str, input_text: str, enter: bool = True) -> dict:
    if _use_windows_persistent_shell_backend():
        if conpty_ops.has_session(session_id):
            return await conpty_ops.send_shell(session_id, input_text, enter)
        return await _native_send_shell(session_id, input_text, enter)
    if session_id in _NATIVE_SHELL_SESSIONS or resolve_tmux().path is None:
        return await _native_send_shell(session_id, input_text, enter)

    result = await tmux(["send-keys", "-t", session_id, "-l", input_text])
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    if enter:
        result = await tmux(["send-keys", "-t", session_id, "Enter"])
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout)
    audit(
        "shell_send",
        session=session_id,
        bytes=len(input_text.encode()),
        enter=enter,
        backend="tmux",
    )
    return {"session_id": session_id, "sent_bytes": len(input_text.encode()), "enter": enter}


async def read_shell(session_id: str, lines: int = 200) -> dict:
    if _use_windows_persistent_shell_backend():
        if conpty_ops.has_session(session_id):
            return await conpty_ops.read_shell(session_id, lines)
        return await _native_read_shell(session_id, lines)
    if session_id in _NATIVE_SHELL_SESSIONS or resolve_tmux().path is None:
        return await _native_read_shell(session_id, lines)

    result = await tmux(["capture-pane", "-p", "-t", session_id, "-S", f"-{max(1, lines)}"])
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit("shell_read", session=session_id, lines=lines, backend="tmux")
    return {"session_id": session_id, "output": result.stdout}


async def kill_shell(session_id: str) -> dict:
    if _use_windows_persistent_shell_backend():
        if conpty_ops.has_session(session_id):
            return await conpty_ops.kill_shell(session_id)
        return await _native_kill_shell(session_id)
    if session_id in _NATIVE_SHELL_SESSIONS or resolve_tmux().path is None:
        return await _native_kill_shell(session_id)

    result = await tmux(["kill-session", "-t", session_id])
    audit("shell_kill", session=session_id, ok=result.ok, backend="tmux")
    return {"session_id": session_id, "killed": result.ok, "stderr": result.stderr}


async def _tmux_list_shells() -> list[dict]:
    if resolve_tmux().path is None:
        return []
    result = await tmux(
        [
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_created}\t#{session_attached}",
        ],
        timeout_s=5,
    )
    if not result.ok:
        # tmux exits nonzero when no server or sessions exist.
        return []
    sessions = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            sessions.append(
                {
                    "session_id": parts[0],
                    "created": parts[1] if len(parts) > 1 else None,
                    "attached": parts[2] if len(parts) > 2 else None,
                    "backend": f"tmux-{resolve_tmux().source}",
                }
            )
    return sessions


async def list_shells() -> dict:
    native_sessions = await _native_list_shells()
    sessions = list(native_sessions.get("sessions", []))
    if _use_windows_persistent_shell_backend():
        conpty_sessions = await conpty_ops.list_shells()
        sessions[0:0] = conpty_sessions.get("sessions", [])
    else:
        sessions[0:0] = await _tmux_list_shells()
    return {"sessions": sessions}
