"""Cancellation must retain process ownership and reap the complete native tree."""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from conftest import python_shell_command

from local_shell_mcp import shell_ops
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["already_done", "success", "raced", "failed", "missing", "timeout", "stuck"])
async def test_windows_owned_tree_termination_and_failure_diagnostics(monkeypatch, outcome):
    calls = []
    root = SimpleNamespace(pid=12345, returncode=0 if outcome == "already_done" else None)
    root.kill = lambda: setattr(root, "returncode", -9)

    class Killer:
        returncode = None
        async def wait(self):
            if outcome == "timeout" and self.returncode is None:
                await asyncio.Event().wait()
            self.returncode = 128 if outcome in {"raced", "failed"} else 0
            if outcome in {"success", "raced"}:
                root.returncode = 0
            return self.returncode
        def kill(self):
            self.returncode = -9

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        if outcome == "missing":
            raise FileNotFoundError("OS helper unavailable")
        return Killer()

    async def wait_for_exit(process, timeout):
        assert process is root
        return outcome != "stuck"

    monkeypatch.setattr(shell_ops, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(shell_ops.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(shell_ops, "managed_process_kwargs", lambda: {"creationflags": 8})
    monkeypatch.setattr(shell_ops, "_wait_for_process_exit", wait_for_exit)
    monkeypatch.setattr(shell_ops, "GRACEFUL_TERMINATION_TIMEOUT_S", .01)
    monkeypatch.setattr(shell_ops, "KILL_TERMINATION_TIMEOUT_S", .01)
    result = await shell_ops._terminate_process_group(root)
    if outcome == "already_done":
        assert calls == [] and result == ""
    else:
        assert calls[0][0][1:] == ("/PID", "12345", "/T", "/F")
        assert calls[0][1]["creationflags"] == 8
        assert ("failed" in result) if outcome in {"failed", "missing", "timeout"} else (
            "did not exit" in result if outcome == "stuck" else result == "")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shell", "exec"])
async def test_cancel_during_process_registration_cleans_child_and_pipes(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    marker, leaked = tmp_path / "started", tmp_path / "leaked"
    allow_effect = tmp_path / "allow-effect"
    code = ("from pathlib import Path\nimport time\n"
            f"Path({str(marker)!r}).write_text('ready')\n"
            f"while not Path({str(allow_effect)!r}).exists():\n"
            "    time.sleep(.02)\n"
            f"Path({str(leaked)!r}).write_text('bad')\n")
    compile(code, "owned-child", "exec")
    original = shell_ops.asyncio.create_subprocess_exec
    release = asyncio.Event()
    created = asyncio.Event()
    processes = []

    async def delayed_registration(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        created.set()
        await release.wait()
        return process

    monkeypatch.setattr(shell_ops.asyncio, "create_subprocess_exec", delayed_registration)
    task = asyncio.create_task(shell_ops.run_shell(python_shell_command(code), cwd=str(tmp_path), timeout_s=15)
        if mode == "shell" else shell_ops._run_exec([sys.executable, "-c", code], cwd=str(tmp_path), timeout_s=15))
    try:
        # Target the ownership-registration window, not Python interpreter
        # startup speed. The real OS process exists while its handle is held
        # behind release; user code remains gated until after cleanup.
        await asyncio.wait_for(created.wait(), timeout=10)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done(), "Cancellation must wait until the spawned process has an owner"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10)
        assert processes[0].returncode is not None
        assert processes[0]._transport.is_closing()
        allow_effect.write_text("released", encoding="utf-8")
        await asyncio.sleep(3.1)
        assert not leaked.exists()
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        get_settings.cache_clear()
