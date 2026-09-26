from pathlib import Path

import pytest

from local_shell_mcp.remote import (
    REMOTE_WORKER_TOOL_NAMES,
    execute_worker_tool,
    worker_capabilities,
)
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_remote_worker_rejects_tools_outside_allowlist():
    with pytest.raises(ValueError, match="unsupported remote worker tool"):
        await execute_worker_tool("not_a_worker_tool", {})


def test_remote_worker_allowlist_covers_core_capabilities():
    assert {
        "run_shell_tool",
        "run_python_tool",
        "read_file",
        "write_file",
        "job_start",
        "job_list",
        "transfer_read_chunk",
        "transfer_write_chunk",
        "browser_run_script",
        "gui_list",
        "gui_state",
        "gui_state_refresh",
        "gui_frame",
        "gui_human_action",
        "gui_action",
    } <= REMOTE_WORKER_TOOL_NAMES


    assert {
        "git_status_tool",
        "read_many_files",
        "multi_edit_file",
        "browser_screenshot_tool",
        "browser_pdf_tool",
        "browser_capture_tool",
        "browser_get_text_tool",
        "playwright_run_script_tool",
    }.isdisjoint(REMOTE_WORKER_TOOL_NAMES)

    capabilities = set(worker_capabilities())
    assert {"shell", "jobs", "files", "file_transfer", "python", "playwright", "gui"} <= capabilities


@pytest.mark.asyncio
async def test_remote_worker_python_tool_respects_local_size_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES", "16")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="Refusing Python script"):
        await execute_worker_tool("run_python_tool", {"code": "x" * 17})


@pytest.mark.asyncio
async def test_remote_worker_apply_patch_respects_local_size_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES", "16")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="Refusing patch"):
        await execute_worker_tool("apply_patch", {"patch": "x" * 17})


@pytest.mark.asyncio
async def test_remote_gui_worker_dispatch_and_lazy_dependencies(monkeypatch):
    import local_shell_mcp.remote as remote
    import local_shell_mcp.remote_worker_installer as installer

    calls = []

    class FakeGuiManager:
        async def list_windows(self):
            calls.append(("list",))
            return {"windows": [{"id": "w"}]}

        async def snapshot(self, window_id, **kwargs):
            calls.append(("snapshot", window_id, kwargs))
            return {"window": {"id": window_id}, "state_id": "s"}

        async def refresh_state(self, window_id, state_id):
            calls.append(("refresh", window_id, state_id))
            return {"state_id": state_id, "state_ttl_s": 30}

        async def frame(self, window_id):
            calls.append(("frame", window_id))
            return {"window": {"id": window_id}, "screenshot_path": "/tmp/frame.png"}

        async def human_act(self, window_id, bounds, actions):
            calls.append(("human_act", window_id, bounds, actions))
            return {"human_control": True}

        async def act(self, window_id, state_id, actions):
            calls.append(("act", window_id, state_id, actions))
            return {"state_consumed": True}

    manager = FakeGuiManager()
    import local_shell_mcp.gui as gui

    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(remote.sys, "platform", "linux")
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"DISPLAY": ":0"})
    monkeypatch.setattr(linux, "_session_type", lambda _env: "x11")
    dependency_calls = []

    def dependencies(session_type=None):
        dependency_calls.append(session_type)
        return {"available": True, "missing": []}

    monkeypatch.setattr(installer, "ensure_gui_dependencies", dependencies)

    listed = await remote._execute_gui_worker_tool("gui_list", {})
    assert listed["windows"][0]["id"] == "w"
    assert dependency_calls == ["x11"]

    state = await remote._execute_gui_worker_tool(
        "gui_state",
        {
            "window_id": "w",
            "screenshot": False,
            "include_elements": False,
            "max_elements": 9,
            "max_depth": 3,
        },
    )
    assert state["state_id"] == "s"
    assert dependency_calls == ["x11", "x11"]

    refreshed = await remote._execute_gui_worker_tool(
        "gui_state_refresh",
        {"window_id": "w", "state_id": "s"},
    )
    assert refreshed["state_ttl_s"] == 30
    assert dependency_calls == ["x11", "x11", "x11"]

    frame = await remote._execute_gui_worker_tool(
        "gui_frame",
        {"window_id": "w"},
    )
    assert frame["screenshot_path"] == "/tmp/frame.png"
    assert dependency_calls == ["x11", "x11", "x11", "x11"]

    human = await remote._execute_gui_worker_tool(
        "gui_human_action",
        {
            "window_id": "w",
            "bounds": {"x": 0, "y": 0, "width": 10, "height": 10},
            "actions": [{"type": "click", "x": 1, "y": 1}],
        },
    )
    assert human["human_control"] is True
    assert dependency_calls == ["x11", "x11", "x11", "x11", "x11"]

    acted = await remote._execute_gui_worker_tool(
        "gui_action",
        {"window_id": "w", "state_id": "s", "actions": [{"type": "wait"}]},
    )
    assert acted["state_consumed"] is True
    assert dependency_calls == ["x11", "x11", "x11", "x11", "x11", "x11"]
    assert calls[-1][0] == "act"

    with pytest.raises(ValueError, match="unsupported remote GUI worker tool"):
        await remote._execute_gui_worker_tool("gui_unknown", {})


@pytest.mark.asyncio
async def test_remote_gui_worker_dependency_failure_is_scoped_to_gui(monkeypatch):
    import local_shell_mcp.remote as remote
    import local_shell_mcp.remote_worker_installer as installer

    monkeypatch.setattr(remote.sys, "platform", "win32")
    monkeypatch.setattr(
        installer,
        "ensure_gui_dependencies",
        lambda _session_type=None: {
            "available": False,
            "missing": ["uiautomation"],
            "error": "offline",
        },
    )
    with pytest.raises(RuntimeError, match="uiautomation unavailable"):
        await remote._execute_gui_worker_tool("gui_list", {})



def test_linux_gui_preflight_caches_positive_session(monkeypatch):
    import local_shell_mcp.gui.linux as linux
    import local_shell_mcp.remote as remote

    calls = []

    def discover():
        calls.append("discover")
        return {"DISPLAY": ":0"}

    monkeypatch.setattr(linux, "_desktop_environment", discover)
    monkeypatch.setattr(linux, "_session_type", lambda _env: "x11")
    monkeypatch.setattr(remote, "_GUI_LINUX_PREFLIGHT_SESSION_TYPE", None)
    monkeypatch.setattr(remote, "_GUI_LINUX_PREFLIGHT_ENV_SIGNATURE", None)
    monkeypatch.setattr(remote, "_GUI_LINUX_PREFLIGHT_DISCOVERY_TOKEN", None)

    assert remote._linux_gui_preflight_session_type() == "x11"
    assert remote._linux_gui_preflight_session_type() == "x11"
    assert calls == ["discover"]


@pytest.mark.asyncio
async def test_remote_gui_worker_headless_linux_never_bootstraps_gui_dependencies(monkeypatch):
    import local_shell_mcp.gui.linux as linux
    import local_shell_mcp.remote as remote
    import local_shell_mcp.remote_worker_installer as installer

    monkeypatch.setattr(remote.sys, "platform", "linux")
    monkeypatch.setattr(linux, "_desktop_environment", lambda: {})
    monkeypatch.setattr(linux, "_session_type", lambda _env: "unknown")
    monkeypatch.setattr(
        installer,
        "ensure_gui_dependencies",
        lambda *_args, **_kwargs: pytest.fail(
            "headless GUI dispatch must not invoke dependency installation"
        ),
    )

    with pytest.raises(RuntimeError, match="No graphical Linux session"):
        await remote._execute_gui_worker_tool("gui_list", {})




def test_remote_module_does_not_import_gui_before_dispatch(tmp_path):
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import local_shell_mcp.remote; "
                "assert 'local_shell_mcp.gui' not in sys.modules"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
