"""Run bounded shell commands and tmux-backed sessions with policy checks, timeout handling, and output truncation."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import time
import uuid
from dataclasses import dataclass

from .audit import audit
from .fs_ops import relative_display, resolve_path
from .models import CommandResult
from .settings import get_settings

PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S = 10
PUBLIC_RUN_SHELL_TIMEOUT_CAP_S = 60
GRACEFUL_TERMINATION_TIMEOUT_S = 5
KILL_TERMINATION_TIMEOUT_S = 2
READER_DRAIN_TIMEOUT_S = 2
_COMMAND_SEMAPHORE: asyncio.Semaphore | None = None
_COMMAND_SEMAPHORE_SIZE: int | None = None


@dataclass
class TailBuffer:
    """Accumulate bounded process output while tracking how many bytes were dropped from the head."""

    keep_bytes: int
    data: bytearray
    total_bytes: int = 0

    def append(self, chunk: bytes) -> None:
        """Append bytes to the tail buffer and discard the oldest data beyond the configured limit."""
        if not chunk:
            return
        self.total_bytes += len(chunk)
        self.data.extend(chunk)
        overflow = len(self.data) - self.keep_bytes
        if overflow > 0:
            del self.data[:overflow]

    @property
    def truncated(self) -> bool:
        """Report whether any output was dropped while enforcing the buffer limit."""
        return self.total_bytes > len(self.data)


def check_command_policy(command: str) -> None:
    """Reject shell commands matching configured denylist entries before execution."""
    settings = get_settings()
    for denied in settings.command_denylist:
        if denied and denied in command:
            raise PermissionError(f"Command contains denylisted fragment: {denied!r}")


def clamp_timeout(timeout_s: int | None) -> int:
    """Clamp requested command timeouts to configured server bounds."""
    settings = get_settings()
    timeout = timeout_s or settings.default_timeout_s
    return max(1, min(timeout, settings.max_timeout_s))


def public_run_shell_timeout(timeout_s: int | None) -> int:
    """Apply stricter public shell defaults while still respecting the global maximum timeout."""
    if timeout_s is not None and timeout_s > PUBLIC_RUN_SHELL_TIMEOUT_CAP_S:
        raise ValueError(
            f"timeout_s must be <= {PUBLIC_RUN_SHELL_TIMEOUT_CAP_S} seconds for public run_shell"
        )
    return max(
        1, min(timeout_s or PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S, PUBLIC_RUN_SHELL_TIMEOUT_CAP_S)
    )


def clamp_output(
    stdout: str, stderr: str, max_output_bytes: int | None = None
) -> tuple[str, str, bool]:
    """Trim stdout and stderr to a shared byte budget while reporting which streams were truncated."""
    limit = _effective_output_limit(max_output_bytes)
    encoded_len = len(stdout.encode()) + len(stderr.encode())
    if encoded_len <= limit:
        return stdout, stderr, False
    half = max(1, limit // 2)
    return stdout[-half:], stderr[-half:], True


def _effective_output_limit(max_output_bytes: int | None = None) -> int:
    """Resolve the output byte limit requested by a caller against server-wide maximums."""
    settings = get_settings()
    configured = max(1, settings.max_output_bytes)
    if max_output_bytes is None:
        return configured
    return max(1, min(max_output_bytes, configured))


def _command_semaphore() -> asyncio.Semaphore:
    """Return the process-wide semaphore that limits concurrent shell commands."""
    global _COMMAND_SEMAPHORE, _COMMAND_SEMAPHORE_SIZE
    size = max(1, get_settings().max_concurrent_commands)
    if _COMMAND_SEMAPHORE is None or size != _COMMAND_SEMAPHORE_SIZE:
        _COMMAND_SEMAPHORE = asyncio.Semaphore(size)
        _COMMAND_SEMAPHORE_SIZE = size
    return _COMMAND_SEMAPHORE


async def _spawn_process(command: str, cwd: str) -> asyncio.subprocess.Process:
    """Start a shell command in its own process group with workspace-aware cwd resolution."""
    settings = get_settings()
    return await asyncio.create_subprocess_exec(
        settings.shell_executable,
        "-lc",
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


async def _read_stream_tail(stream: asyncio.StreamReader | None, tail: TailBuffer) -> None:
    """Continuously read a process stream into a bounded tail buffer."""
    if stream is None:
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return
        tail.append(chunk)


async def _wait_for_process_exit(proc: asyncio.subprocess.Process, timeout_s: int) -> bool:
    """Wait for process completion while converting timeout into structured result state."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        return True
    except TimeoutError:
        return False


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> str:
    """Terminate an entire shell process group, escalating to kill when graceful shutdown times out."""
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
    """Let stream-reader tasks drain briefly before cancelling unfinished readers."""
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_s)
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_shell(
    command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None
) -> CommandResult:
    """Execute a shell command with policy enforcement, concurrency limits, timeout handling, and bounded output capture."""
    check_command_policy(command)
    resolved_cwd = resolve_path(cwd, must_exist=True)
    start = time.time()
    audit("run_shell_start", command=command, cwd=str(resolved_cwd))
    timeout = clamp_timeout(timeout_s)

    proc: asyncio.subprocess.Process | None = None
    timed_out = False
    termination_error = ""
    output_limit = _effective_output_limit(max_output_bytes)
    per_stream_limit = max(1, output_limit // 2)
    stdout_tail = TailBuffer(per_stream_limit, bytearray())
    stderr_tail = TailBuffer(per_stream_limit, bytearray())
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

    if reader_tasks:
        await _finish_reader_tasks(reader_tasks)

    if termination_error:
        stderr_tail.append(termination_error.encode())

    stdout_b = bytes(stdout_tail.data)
    stderr_b = bytes(stderr_tail.data)
    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    truncated = stdout_tail.truncated or stderr_tail.truncated
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
    """Execute a shell command through the public API using stricter timeout defaults."""
    return await run_shell(command, cwd, public_run_shell_timeout(timeout_s), max_output_bytes)


def _tmux_session_name(name: str | None = None) -> str:
    """Normalize user-facing shell session names into the tmux naming scheme used by the server."""
    base = name or f"mcp-{uuid.uuid4().hex[:8]}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", base)[:64]


async def tmux(args: list[str], timeout_s: int = 10) -> CommandResult:
    """Run a tmux command with a bounded timeout and normalized command result payload."""
    cmd = " ".join(shlex.quote(x) for x in [get_settings().tmux_bin, *args])
    return await run_shell(cmd, cwd=".", timeout_s=timeout_s)


async def start_shell(cwd: str = ".", name: str | None = None, command: str | None = None) -> dict:
    """Start or replace a tmux-backed persistent shell session in a resolved working directory."""
    resolved_cwd = resolve_path(cwd, must_exist=True)
    sessions = await list_shells()
    max_sessions = max(1, get_settings().max_tmux_sessions)
    if len(sessions.get("sessions", [])) >= max_sessions:
        raise RuntimeError(f"Refusing to start more than {max_sessions} tmux sessions")
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
    audit("shell_start", session=session, cwd=str(resolved_cwd), command=initial)
    return {"session_id": session, "cwd": relative_display(resolved_cwd), "command": initial}


async def send_shell(session_id: str, input_text: str, enter: bool = True) -> dict:
    """Send input to a persistent shell session, optionally appending Enter."""
    args = ["send-keys", "-t", session_id, input_text]
    if enter:
        args.append("Enter")
    result = await tmux(args)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit("shell_send", session=session_id, bytes=len(input_text.encode()), enter=enter)
    return {"session_id": session_id, "sent_bytes": len(input_text.encode()), "enter": enter}


async def read_shell(session_id: str, lines: int = 200) -> dict:
    """Read recent output from a persistent shell session through tmux capture-pane."""
    result = await tmux(["capture-pane", "-p", "-t", session_id, "-S", f"-{max(1, lines)}"])
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit("shell_read", session=session_id, lines=lines)
    return {"session_id": session_id, "output": result.stdout}


async def kill_shell(session_id: str) -> dict:
    """Terminate a persistent shell session by its normalized tmux session id."""
    result = await tmux(["kill-session", "-t", session_id])
    audit("shell_kill", session=session_id, ok=result.ok)
    return {"session_id": session_id, "killed": result.ok, "stderr": result.stderr}


async def list_shells() -> dict:
    """List active tmux-backed shell sessions managed by local-shell-mcp."""
    result = await tmux(
        ["list-sessions", "-F", "#{session_name}\t#{session_created}\t#{session_attached}"],
        timeout_s=5,
    )
    if not result.ok:
        # tmux exits nonzero when no server/sessions exist.
        return {"sessions": []}
    sessions = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            sessions.append(
                {
                    "session_id": parts[0],
                    "created": parts[1] if len(parts) > 1 else None,
                    "attached": parts[2] if len(parts) > 2 else None,
                }
            )
    return {"sessions": sessions}
