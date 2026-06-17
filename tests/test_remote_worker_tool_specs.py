import pytest

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
