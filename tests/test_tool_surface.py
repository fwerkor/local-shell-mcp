import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp

LOCAL_TOOL_NAMES = {
    "search",
    "fetch",
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
    "read_many_files",
    "create_file_link",
    "list_file_links",
    "revoke_file_link",
    "write_file",
    "edit_file",
    "multi_edit_file",
    "delete_file_or_dir",
    "apply_patch",
    "git_clone_tool",
    "git_status_tool",
    "git_diff_tool",
    "git_log_tool",
    "git_checkout_tool",
    "git_fetch_tool",
    "git_pull_tool",
    "git_add_tool",
    "git_commit_tool",
    "git_push_tool",
    "git_show_tool",
    "git_reset_tool",
    "secret_scan",
    "todo_read_tool",
    "todo_write_tool",
    "playwright_install_tool",
    "browser_screenshot_tool",
    "browser_get_text_tool",
    "browser_eval_tool",
    "browser_pdf_tool",
    "playwright_run_script_tool",
    "audit_tail",
}

REMOTE_TOOL_NAMES = {
    "remote_invite",
    "remote_list_machines",
    "remote_revoke_machine",
    "remote_rename_machine",
    "remote_environment_info",
    "remote_run_shell_tool",
    "remote_run_python_tool",
    "remote_shell_start",
    "remote_shell_send",
    "remote_shell_read",
    "remote_shell_kill",
    "remote_shell_list",
    "remote_job_start",
    "remote_job_list",
    "remote_job_tail",
    "remote_job_stop",
    "remote_job_retry",
    "remote_list_files",
    "remote_tree_view",
    "remote_glob_search",
    "remote_grep_search",
    "remote_read_file",
    "remote_read_many_files",
    "remote_write_file",
    "remote_edit_file",
    "remote_multi_edit_file",
    "remote_delete_file_or_dir",
    "remote_copy_file",
    "remote_copy_dir",
    "remote_pull_file",
    "remote_push_file",
    "remote_pull_dir",
    "remote_push_dir",
    "remote_apply_patch",
    "remote_git_clone_tool",
    "remote_git_status_tool",
    "remote_git_diff_tool",
    "remote_git_log_tool",
    "remote_git_checkout_tool",
    "remote_git_fetch_tool",
    "remote_git_pull_tool",
    "remote_git_add_tool",
    "remote_git_commit_tool",
    "remote_git_push_tool",
    "remote_git_show_tool",
    "remote_git_reset_tool",
    "remote_playwright_install_tool",
    "remote_browser_screenshot_tool",
    "remote_browser_get_text_tool",
    "remote_browser_eval_tool",
    "remote_browser_pdf_tool",
    "remote_playwright_run_script_tool",
}


@pytest.mark.asyncio
async def test_mcp_tool_surface_is_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert set(tools) == LOCAL_TOOL_NAMES | REMOTE_TOOL_NAMES
    assert all(tool.outputSchema is not None for tool in tools.values())


@pytest.mark.asyncio
async def test_remote_tools_can_be_disabled_from_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    tools = {tool.name for tool in await build_mcp().list_tools()}

    assert tools == LOCAL_TOOL_NAMES
    assert tools.isdisjoint(REMOTE_TOOL_NAMES)


@pytest.mark.asyncio
async def test_key_tool_descriptions_guide_tool_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert "For long-running" in tools["run_shell_tool"].description
    assert "purpose/explanation" in tools["run_shell_tool"].description
    assert "old must match exactly" in tools["edit_file"].description
    assert "recursive=true is required" in tools["delete_file_or_dir"].description
    assert "high-entropy token" in tools["create_file_link"].description


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
        "multi_edit_file",
        "delete_file_or_dir",
        "apply_patch",
        "git_commit_tool",
        "git_push_tool",
        "remote_run_shell_tool",
        "remote_run_python_tool",
        "remote_shell_start",
        "remote_job_start",
        "remote_job_retry",
        "remote_apply_patch",
        "remote_git_commit_tool",
        "remote_git_push_tool",
    }

    for name in names:
        properties = tools[name].inputSchema["properties"]
        assert "purpose" in properties, name
        assert "explanation" in properties, name
