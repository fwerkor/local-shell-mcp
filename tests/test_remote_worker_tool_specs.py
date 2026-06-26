import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.remote import (
    REMOTE_WORKER_TOOL_NAMES,
    execute_worker_tool,
    worker_capabilities,
)


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
        "git_status_tool",
        "browser_screenshot_tool",
    } <= REMOTE_WORKER_TOOL_NAMES

    capabilities = set(worker_capabilities())
    assert {"shell", "jobs", "files", "file_transfer", "git", "python", "playwright"} <= capabilities


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
