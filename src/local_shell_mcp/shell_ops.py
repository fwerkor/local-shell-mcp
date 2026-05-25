from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import time
import uuid

from .audit import audit
from .fs_ops import relative_display, resolve_path
from .models import CommandResult
from .settings import get_settings


def check_command_policy(command: str) -> None:
    settings = get_settings()
    for denied in settings.command_denylist:
        if denied and denied in command:
            raise PermissionError(f"Command contains denylisted fragment: {denied!r}")


def clamp_timeout(timeout_s: int | None) -> int:
    settings = get_settings()
    timeout = timeout_s or settings.default_timeout_s
    return max(1, min(timeout, settings.max_timeout_s))


def clamp_output(stdout: str, stderr: str, max_output_bytes: int | None = None) -> tuple[str, str, bool]:
    settings = get_settings()
    limit = max_output_bytes or settings.max_output_bytes
    encoded_len = len(stdout.encode()) + len(stderr.encode())
    if encoded_len <= limit:
        return stdout, stderr, False
    half = max(1024, limit // 2)
    return stdout[-half:], stderr[-half:], True


async def run_shell(command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None) -> CommandResult:
    settings = get_settings()
    check_command_policy(command)
    resolved_cwd = resolve_path(cwd, must_exist=True)
    start = time.time()
    audit("run_shell_start", command=command, cwd=str(resolved_cwd))

    proc = await asyncio.create_subprocess_exec(
        settings.shell_executable,
        "-lc",
        command,
        cwd=str(resolved_cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=os.setsid if hasattr(os, "setsid") else None,
    )
    timed_out = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=clamp_timeout(timeout_s))
    except TimeoutError:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=5)
        except TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            stdout_b, stderr_b = await proc.communicate()

    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    stdout, stderr, truncated = clamp_output(stdout, stderr, max_output_bytes)
    duration_ms = int((time.time() - start) * 1000)
    result = CommandResult(
        ok=(proc.returncode == 0 and not timed_out),
        exit_code=proc.returncode,
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
        exit_code=proc.returncode,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated=truncated,
    )
    return result


def _tmux_session_name(name: str | None = None) -> str:
    base = name or f"mcp-{uuid.uuid4().hex[:8]}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", base)[:64]


async def tmux(args: list[str], timeout_s: int = 10) -> CommandResult:
    cmd = " ".join(shlex.quote(x) for x in [get_settings().tmux_bin, *args])
    return await run_shell(cmd, cwd=".", timeout_s=timeout_s)


async def start_shell(cwd: str = ".", name: str | None = None, command: str | None = None) -> dict:
    resolved_cwd = resolve_path(cwd, must_exist=True)
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
    args = ["send-keys", "-t", session_id, input_text]
    if enter:
        args.append("Enter")
    result = await tmux(args)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit("shell_send", session=session_id, bytes=len(input_text.encode()), enter=enter)
    return {"session_id": session_id, "sent_bytes": len(input_text.encode()), "enter": enter}


async def read_shell(session_id: str, lines: int = 200) -> dict:
    result = await tmux(["capture-pane", "-p", "-t", session_id, "-S", f"-{max(1, lines)}"])
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit("shell_read", session=session_id, lines=lines)
    return {"session_id": session_id, "output": result.stdout}


async def kill_shell(session_id: str) -> dict:
    result = await tmux(["kill-session", "-t", session_id])
    audit("shell_kill", session=session_id, ok=result.ok)
    return {"session_id": session_id, "killed": result.ok, "stderr": result.stderr}


async def list_shells() -> dict:
    result = await tmux(["list-sessions", "-F", "#{session_name}\t#{session_created}\t#{session_attached}"], timeout_s=5)
    if not result.ok:
        # tmux exits nonzero when no server/sessions exist.
        return {"sessions": []}
    sessions = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            sessions.append({"session_id": parts[0], "created": parts[1] if len(parts) > 1 else None, "attached": parts[2] if len(parts) > 2 else None})
    return {"sessions": sessions}
