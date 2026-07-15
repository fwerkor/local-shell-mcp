import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp

CORE_TOOL_NAMES = {
    "search",
    "fetch",
    "environment_info",
    "skills_list",
    "skill_load",
    "skill_read_file",
    "run_shell_tool",
    "run_python_tool",
    "shell_start",
    "shell_send",
    "shell_read",
    "shell_kill",
    "shell_list",
    "job_start",
    "job_list",
    "job_tail",
    "job_stop",
    "job_retry",
    "list_files",
    "tree_view",
    "glob_search",
    "grep_search",
    "read_file",
    "create_file_link",
    "list_file_links",
    "revoke_file_link",
    "write_file",
    "edit_file",
    "delete_file_or_dir",
    "apply_patch",
    "secret_scan",
    "todo_read_tool",
    "todo_write_tool",
    "browser_capture_tool",
    "browser_get_text_tool",
    "playwright_run_script_tool",
    "audit_tail",
}

REMOTE_DEPENDENT_TOOL_NAMES = {
    "transfer_path",
    "remote_invite",
    "remote_list_machines",
    "remote_revoke_machine",
    "remote_rename_machine",
}

REMOVED_TOOL_NAMES = {
    "version_info",
    "read_many_files",
    "multi_edit_file",
    "git_status_tool",
    "git_commit_tool",
    "remote_run_shell_tool",
    "remote_read_file",
    "remote_git_status_tool",
    "remote_copy_file",
    "remote_pull_file",
    "remote_push_file",
    "browser_screenshot_tool",
    "browser_pdf_tool",
    "browser_eval_tool",
    "playwright_install_tool",
}


@pytest.mark.asyncio
async def test_mcp_tool_surface_is_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert set(tools) == CORE_TOOL_NAMES | REMOTE_DEPENDENT_TOOL_NAMES
    assert set(tools).isdisjoint(REMOVED_TOOL_NAMES)
    assert all(tool.outputSchema is not None for tool in tools.values())


@pytest.mark.asyncio
async def test_remote_admin_tools_can_be_disabled_from_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    tools = {tool.name for tool in await build_mcp().list_tools()}

    assert tools == CORE_TOOL_NAMES
    assert tools.isdisjoint(REMOTE_DEPENDENT_TOOL_NAMES)


@pytest.mark.asyncio
async def test_machine_capable_tools_use_optional_machine_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    machine_capable = {
        "environment_info",
        "run_shell_tool",
        "run_python_tool",
        "shell_start",
        "shell_send",
        "shell_read",
        "shell_kill",
        "shell_list",
        "job_start",
        "job_list",
        "job_tail",
        "job_stop",
        "job_retry",
        "list_files",
        "tree_view",
        "glob_search",
        "grep_search",
        "read_file",
        "write_file",
        "edit_file",
        "delete_file_or_dir",
        "apply_patch",
        "browser_capture_tool",
        "browser_get_text_tool",
        "playwright_run_script_tool",
    }

    for name in machine_capable:
        assert "machine" in tools[name].inputSchema["properties"], name
    transfer_properties = tools["transfer_path"].inputSchema["properties"]
    assert {"source_machine", "destination_machine"} <= set(transfer_properties)


@pytest.mark.asyncio
async def test_key_tool_descriptions_guide_tool_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert "For long-running" in tools["run_shell_tool"].description
    assert "purpose/explanation" in tools["run_shell_tool"].description
    assert "Git" in tools["run_shell_tool"].description
    assert "old must match exactly" in tools["edit_file"].description
    assert "recursive=true is required" in tools["delete_file_or_dir"].description
    assert "high-entropy token" in tools["create_file_link"].description
    assert "tool surface stays fixed" in tools["skills_list"].description
    assert "exact name returned from skills_list" in tools["skill_load"].description


@pytest.mark.asyncio
async def test_risky_tools_accept_purpose_and_explanation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    names = {
        "run_shell_tool",
        "run_python_tool",
        "shell_start",
        "job_start",
        "job_retry",
        "write_file",
        "edit_file",
        "delete_file_or_dir",
        "apply_patch",
        }

    for name in names:
        properties = tools[name].inputSchema["properties"]
        assert "purpose" in properties, name
        assert "explanation" in properties, name
