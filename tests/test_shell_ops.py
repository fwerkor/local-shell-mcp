import asyncio
import json
import time

import pytest
from conftest import python_shell_command
from fastapi.testclient import TestClient

import local_shell_mcp.http_app as http_app_module
import local_shell_mcp.tools as tools_module
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import (
    PUBLIC_RUN_SHELL_TIMEOUT_CAP_S,
    PUBLIC_TOOL_WATCHDOG_TIMEOUT_S,
    _close_process_transport,
    public_run_shell_timeout,
    run_shell,
    send_shell,
)
from local_shell_mcp.tmux_helper import TmuxSelection
from local_shell_mcp.tools import build_mcp


def test_public_tool_watchdog_allows_shell_timeout_cleanup():
    assert PUBLIC_RUN_SHELL_TIMEOUT_CAP_S == 120
    assert PUBLIC_TOOL_WATCHDOG_TIMEOUT_S == 130
    assert tools_module.PUBLIC_TOOL_TIMEOUT_S == 130
    assert http_app_module.PUBLIC_TOOL_TIMEOUT_S == 130


@pytest.mark.asyncio
async def test_run_shell_tool_returns_output_after_command_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "run_shell_tool",
        {
            "command": python_shell_command(
                'import sys, time; print("partial-out", flush=True); '
                'print("partial-err", file=sys.stderr, flush=True); time.sleep(5)'
            ),
            "timeout_s": 1,
        },
    )
    payload = json.loads(response[0][0].text)
    result = payload["data"]

    assert result["timed_out"] is True
    assert "partial-out" in result["stdout"]
    assert "partial-err" in result["stderr"]


@pytest.mark.asyncio
async def test_run_shell_tool_rejects_timeout_above_public_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "run_shell_tool", {"command": "echo ok", "timeout_s": 3600}
    )
    payload = response[0][0].text

    assert "timeout_s must be <= 120 seconds for public run_shell" in payload


@pytest.mark.asyncio
async def test_mcp_tool_watchdog_returns_handled_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(tools_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    get_settings.cache_clear()

    async def hanging_tree(cwd: str = ".", depth: int = 3, max_entries: int = 500):  # noqa: ARG001
        await asyncio.sleep(5)

    monkeypatch.setattr(tools_module, "tree", hanging_tree)

    response = await build_mcp().call_tool("tree_view", {"cwd": "."})
    payload = response[0][0].text

    assert "tree_view exceeded 0.01 second public tool timeout" in payload


def test_rest_tool_watchdog_returns_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    get_settings.cache_clear()

    async def hanging_tree(cwd: str = ".", depth: int = 3, max_entries: int = 500):  # noqa: ARG001
        await asyncio.sleep(5)

    monkeypatch.setattr(http_app_module, "tree", hanging_tree)

    response = TestClient(build_http_app()).post("/tools/tree", json={"cwd": "."})

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


def test_rest_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    get_settings.cache_clear()

    def blocking_list_dir(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        time.sleep(0.2)
        return []

    monkeypatch.setattr(http_app_module, "list_dir", blocking_list_dir)

    response = TestClient(build_http_app()).post("/tools/list_files", json={"path": "."})

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


@pytest.mark.asyncio
async def test_mcp_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(tools_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    get_settings.cache_clear()

    def blocking_list_dir(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        time.sleep(0.2)
        return []

    monkeypatch.setattr(tools_module, "list_dir", blocking_list_dir)

    response = await build_mcp().call_tool("list_files", {"path": "."})
    payload = response[0][0].text

    assert "list_files exceeded 0.01 second public tool timeout" in payload


def test_public_run_shell_timeout_uses_ten_second_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S", "3600")
    get_settings.cache_clear()

    assert public_run_shell_timeout(None) == 10


def test_public_run_shell_timeout_allows_explicit_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    assert public_run_shell_timeout(120) == 120


@pytest.mark.asyncio
async def test_close_process_transport_closes_stdin_and_transport():
    events = []

    class FakeStdin:
        def close(self):
            events.append("stdin-close")

        async def wait_closed(self):
            events.append("stdin-wait-closed")

    class FakeTransport:
        def close(self):
            events.append("transport-close")

    class FakeProcess:
        stdin = FakeStdin()
        _transport = FakeTransport()

    await _close_process_transport(FakeProcess())  # type: ignore[arg-type]

    assert events == ["stdin-close", "stdin-wait-closed", "transport-close"]


@pytest.mark.asyncio
async def test_run_shell_timeout_includes_subprocess_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    async def hanging_spawn(command: str, cwd: str):  # noqa: ARG001
        await asyncio.sleep(5)

    monkeypatch.setattr("local_shell_mcp.shell_ops._spawn_process", hanging_spawn)

    result = await run_shell("echo never", timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert "Timed out while starting subprocess" in result.stderr


@pytest.mark.asyncio
async def test_run_shell_fast_command_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    result = await run_shell("echo ok", timeout_s=5)

    assert result.ok is True
    assert result.timed_out is False
    assert "ok" in result.stdout


@pytest.mark.asyncio
async def test_run_shell_streams_and_bounds_large_output(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    result = await run_shell(
        python_shell_command('import sys; sys.stdout.write("x" * 200000)'),
        timeout_s=5,
        max_output_bytes=1000,
    )

    assert result.ok is True
    assert result.truncated is True
    assert len(result.stdout.encode()) == 1000
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_run_shell_timeout_marks_result_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    result = await run_shell(python_shell_command("import time; time.sleep(30)"), timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True


@pytest.mark.asyncio
async def test_send_shell_invokes_tmux_promptly(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "local_shell_mcp.shell_ops._use_windows_persistent_shell_backend", lambda: False
    )
    monkeypatch.setattr(
        "local_shell_mcp.shell_ops.resolve_tmux",
        lambda: TmuxSelection("tmux", "system"),
    )

    async def fake_tmux(args: list[str], timeout_s: int = 10):
        calls.append((args, timeout_s))
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=".",
            command="tmux",
        )

    monkeypatch.setattr("local_shell_mcp.shell_ops.tmux", fake_tmux)

    result = await asyncio.wait_for(
        send_shell("session-1", "echo $HOME && Enter", enter=True), timeout=1
    )

    assert result == {"session_id": "session-1", "sent_bytes": 19, "enter": True}
    assert calls == [
        (["send-keys", "-t", "session-1", "-l", "echo $HOME && Enter"], 10),
        (["send-keys", "-t", "session-1", "Enter"], 10),
    ]


@pytest.mark.asyncio
async def test_run_shell_uses_unused_stderr_budget_for_stdout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    result = await run_shell(
        python_shell_command('import sys; sys.stdout.write("x" * 1500)'),
        timeout_s=5,
        max_output_bytes=2000,
    )

    assert result.ok is True
    assert result.truncated is False
    assert len(result.stdout.encode()) == 1500
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_run_shell_shares_total_budget_between_streams(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    result = await run_shell(
        python_shell_command(
            'import sys; sys.stdout.write("o" * 900); sys.stderr.write("e" * 900)'
        ),
        timeout_s=5,
        max_output_bytes=1000,
    )

    assert result.ok is True
    assert result.truncated is True
    assert len(result.stdout.encode()) == 500
    assert len(result.stderr.encode()) == 500
    assert len(result.stdout.encode()) + len(result.stderr.encode()) == 1000


@pytest.mark.asyncio
async def test_tmux_command_uses_selected_binary_and_private_socket(monkeypatch):
    from local_shell_mcp import shell_ops
    from local_shell_mcp.tmux_helper import TmuxSelection

    calls = []

    async def fake_run_shell(command, cwd=".", timeout_s=None, max_output_bytes=None):
        calls.append((command, cwd, timeout_s, max_output_bytes))
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=cwd,
            command=command,
        )

    monkeypatch.setattr(shell_ops, "resolve_tmux", lambda: TmuxSelection("/opt/lsm/tmux", "bundled"))
    monkeypatch.setattr(shell_ops, "tmux_socket_name", lambda: "lsm-test")
    monkeypatch.setattr(shell_ops, "run_shell", fake_run_shell)

    result = await shell_ops.tmux(["list-sessions"], timeout_s=5)

    assert result.ok is True
    assert calls == [("/opt/lsm/tmux -L lsm-test list-sessions", ".", 5, None)]


@pytest.mark.asyncio
async def test_unix_persistent_shell_falls_back_when_tmux_is_missing(tmp_path, monkeypatch):
    import os

    if os.name == "nt":
        pytest.skip("Unix fallback test")

    from local_shell_mcp import shell_ops
    from local_shell_mcp.tmux_helper import TmuxSelection

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    monkeypatch.setattr(shell_ops, "resolve_tmux", lambda: TmuxSelection(None, "native"))

    session = await shell_ops.start_shell(cwd=".", name="native-fallback")
    try:
        assert session["backend"] == "native"
        await shell_ops.send_shell(session["session_id"], "printf 'fallback-ready\\n'")
        deadline = time.monotonic() + 2
        output = ""
        while time.monotonic() < deadline:
            output = (await shell_ops.read_shell(session["session_id"], 20))["output"]
            if "fallback-ready" in output:
                break
            await asyncio.sleep(0.05)
        assert "fallback-ready" in output
        listed = await shell_ops.list_shells()
        assert any(row["session_id"] == session["session_id"] for row in listed["sessions"])
    finally:
        await shell_ops.kill_shell(session["session_id"])
