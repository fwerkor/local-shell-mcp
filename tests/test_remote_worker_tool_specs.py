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

        async def act(self, window_id, state_id, actions):
            calls.append(("act", window_id, state_id, actions))
            return {"state_consumed": True}

    manager = FakeGuiManager()
    monkeypatch.setattr(remote, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(remote.sys, "platform", "linux")
    dependency_calls = []

    def dependencies():
        dependency_calls.append(True)
        return {"available": True, "missing": []}

    monkeypatch.setattr(installer, "ensure_gui_dependencies", dependencies)

    listed = await remote._execute_gui_worker_tool("gui_list", {})
    assert listed["windows"][0]["id"] == "w"
    assert dependency_calls == []

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
    assert dependency_calls == []

    acted = await remote._execute_gui_worker_tool(
        "gui_action",
        {"window_id": "w", "state_id": "s", "actions": [{"type": "wait"}]},
    )
    assert acted["state_consumed"] is True
    assert len(dependency_calls) == 1
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
        lambda: {
            "available": False,
            "missing": ["uiautomation"],
            "error": "offline",
        },
    )
    with pytest.raises(RuntimeError, match="uiautomation unavailable"):
        await remote._execute_gui_worker_tool("gui_list", {})
