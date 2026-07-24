from __future__ import annotations

import asyncio
import os
import shutil
import sys

import pytest

import local_shell_mcp.shell_ops as shell
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tmux_helper import TmuxSelection, bundled_tmux_path


def _result(
    *,
    ok: bool = True,
    timed_out: bool = False,
    stdout: str = "",
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        ok=ok,
        exit_code=0 if ok else 1,
        timed_out=timed_out,
        duration_ms=1,
        cwd=".",
        command="tmux",
        stdout=stdout,
        stderr=stderr,
        truncated=False,
    )


def _configure(tmp_path, monkeypatch, *, shell_executable: str = "/usr/bin/bash") -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", shell_executable)
    get_settings.cache_clear()


def test_tmux_normalizes_inherited_shell(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("SHELL", "/usr/sbin/nologin")
    monkeypatch.setattr(shell, "resolve_tmux", lambda: TmuxSelection("/usr/bin/tmux", "system"))
    captured = {}

    async def fake_run_exec(argv, *, cwd, timeout_s, env, bypass_limit):
        captured.update(
            argv=argv,
            cwd=cwd,
            timeout_s=timeout_s,
            env=env,
            bypass_limit=bypass_limit,
        )
        return _result()

    monkeypatch.setattr(shell, "_run_exec", fake_run_exec)

    asyncio.run(shell.tmux(["list-sessions"], timeout_s=5))

    assert captured["timeout_s"] == 5
    assert captured["argv"] == [
        "/usr/bin/tmux",
        "-L",
        shell.tmux_socket_name(),
        "list-sessions",
    ]
    assert captured["env"]["SHELL"] == "/usr/bin/bash"
    assert captured["bypass_limit"] is False


def test_tmux_resolves_relative_configured_shell(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, shell_executable="bash")
    monkeypatch.setattr(shell, "resolve_tmux", lambda: TmuxSelection("/usr/bin/tmux", "system"))
    monkeypatch.setattr(shell.shutil, "which", lambda value: "tools/bash" if value == "bash" else None)
    session_cwd = tmp_path / "session"
    session_cwd.mkdir()
    expected_shell = os.path.abspath(session_cwd / "tools/bash")
    captured = {}

    async def fake_run_exec(argv, *, cwd, timeout_s, env, bypass_limit):
        captured.update(
            argv=argv,
            cwd=cwd,
            timeout_s=timeout_s,
            env=env,
            bypass_limit=bypass_limit,
        )
        return _result()

    monkeypatch.setattr(shell, "_run_exec", fake_run_exec)

    asyncio.run(
        shell.tmux(
            ["new-session", "-d", "-c", str(session_cwd), "bash"]
        )
    )

    assert captured["env"]["SHELL"] == expected_shell


def test_run_exec_restores_shell_command_auditing(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(shell, "audit", lambda event, **fields: events.append((event, fields)))

    result = asyncio.run(
        shell._run_exec([sys.executable, "-c", "print('audit-ok')"], cwd=".")
    )

    assert result.ok is True
    assert [event for event, _ in events] == ["run_shell_start", "run_shell_end"]
    assert "audit-ok" in result.stdout
    assert events[0][1]["command"] == result.command
    assert events[1][1]["exit_code"] == 0


def test_run_exec_enforces_command_policy(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_COMMAND_DENYLIST", "mkfs")
    get_settings.cache_clear()

    with pytest.raises(PermissionError, match="denylisted fragment"):
        asyncio.run(shell._run_exec(["tmux", "send-keys", "mkfs /dev/sda"], cwd="."))


def test_run_exec_respects_command_semaphore(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    blocked = asyncio.Semaphore(0)
    monkeypatch.setattr(shell, "_command_semaphore", lambda: blocked)
    monkeypatch.setattr(shell, "clamp_timeout", lambda timeout_s: 0.01)

    result = asyncio.run(shell._run_exec(["tmux", "list-sessions"], cwd="."))

    assert result.timed_out is True
    assert result.exit_code is None
    assert "Timed out while starting subprocess" in result.stderr


def test_run_exec_reports_timeout_before_process_creation(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def delayed_spawn(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(shell.asyncio, "create_subprocess_exec", delayed_spawn)
    monkeypatch.setattr(shell, "clamp_timeout", lambda timeout_s: 0.01)

    result = asyncio.run(shell._run_exec(["tmux"], cwd="."))

    assert result.timed_out is True
    assert result.exit_code is None
    assert "Timed out while starting subprocess" in result.stderr


def test_run_exec_terminates_process_after_timeout(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(shell, "clamp_timeout", lambda timeout_s: 0.1)

    result = asyncio.run(
        shell._run_exec(
            [
                sys.executable,
                "-c",
                "import time; print('started', flush=True); time.sleep(30)",
            ],
            cwd=".",
        )
    )

    assert result.timed_out is True
    assert result.exit_code is not None
    assert "started" in result.stdout


def test_start_shell_rejects_session_that_exits_during_startup(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(shell, "_use_windows_persistent_shell_backend", lambda: False)
    monkeypatch.setattr(shell, "resolve_tmux", lambda: TmuxSelection("/usr/bin/tmux", "system"))
    monkeypatch.setattr(shell, "list_shells", lambda: asyncio.sleep(0, result={"sessions": []}))
    calls = []
    responses = iter(
        [
            _result(),
            _result(ok=False, timed_out=True, stderr="probe timed out"),
            _result(),
        ]
    )

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        calls.append((args, timeout_s, bypass_limit))
        return next(responses)

    monkeypatch.setattr(shell, "tmux", fake_tmux)

    with pytest.raises(RuntimeError, match="exited during startup.*probe timed out"):
        asyncio.run(shell._start_shell_unlocked(".", "dead-session"))

    assert calls[1] == (["has-session", "-t", "=dead-session"], 5, True)
    assert calls[2] == (["kill-session", "-t", "=dead-session"], 5, True)


def test_start_shell_allows_explicit_command_to_finish_immediately(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(shell, "_use_windows_persistent_shell_backend", lambda: False)
    monkeypatch.setattr(shell, "resolve_tmux", lambda: TmuxSelection("/usr/bin/tmux", "system"))
    monkeypatch.setattr(shell, "list_shells", lambda: asyncio.sleep(0, result={"sessions": []}))
    calls = []

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        calls.append((args, timeout_s, bypass_limit))
        return _result()

    monkeypatch.setattr(shell, "tmux", fake_tmux)

    started = asyncio.run(shell._start_shell_unlocked(".", "quick-command", "exit 0"))

    assert started["session_id"] == "quick-command"
    assert len(calls) == 1


@pytest.mark.skipif(os.name == "nt", reason="tmux backend is Unix-only")
def test_tmux_session_survives_nologin_service_environment(tmp_path, monkeypatch):
    nologin = shutil.which("nologin")
    executable = shutil.which("bash")
    tmux_path = shutil.which("tmux")
    if tmux_path is None:
        bundled = bundled_tmux_path()
        tmux_path = str(bundled) if bundled is not None else None
    if not nologin or not executable or not tmux_path:
        pytest.skip("nologin, bash, and tmux are required for this regression test")

    _configure(tmp_path, monkeypatch, shell_executable=executable)
    monkeypatch.setenv("LOCAL_SHELL_MCP_TMUX_BIN", tmux_path)
    monkeypatch.setenv("SHELL", nologin)
    get_settings.cache_clear()

    async def exercise():
        started = await shell.start_shell(".", "nologin-regression")
        session_id = started["session_id"]
        try:
            await shell.send_shell(session_id, "printf 'issue108-alive\\n'")
            sessions = await shell.list_shells()
            deadline = asyncio.get_running_loop().time() + 5
            while True:
                output = await shell.read_shell(session_id, 20)
                if "issue108-alive" in output["output"]:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    pytest.fail("tmux did not render the marker before the deadline")
                await asyncio.sleep(0.05)
            return session_id, sessions, output
        finally:
            await shell.kill_shell(session_id)

    session_id, sessions, output = asyncio.run(exercise())

    assert session_id in {item["session_id"] for item in sessions["sessions"]}
    assert "issue108-alive" in output["output"]
