import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp

CORE_TOOL_NAMES = {
    "environment_get",
    "skill_list",
    "skill_load",
    "skill_read",
    "run_shell",
    "run_python",
    "shell_start",
    "shell_send",
    "shell_read",
    "shell_stop",
    "shell_list",
    "job_start",
    "job_list",
    "job_tail",
    "job_stop",
    "job_retry",
    "file_list",
    "file_tree",
    "file_glob",
    "file_grep",
    "file_read",
    "image_view",
    "link_create",
    "link_list",
    "link_revoke",
    "file_write",
    "file_edit",
    "file_delete",
    "file_patch",
    "secret_scan",
    "todo_read_tool",
    "todo_write_tool",
    "browser_capture_tool",
    "browser_get_text_tool",
    "browser_run_script",
    "audit_tail",
}

REMOTE_DEPENDENT_TOOL_NAMES = {
    "remote_manage",
    "remote_transfer",
}

REMOVED_TOOL_NAMES = {
    "search",
    "fetch",
    "environment_info",
    "skills_list",
    "skill_read_file",
    "run_shell_tool",
    "run_python_tool",
    "shell_kill",
    "list_files",
    "tree_view",
    "glob_search",
    "grep_search",
    "read_file",
    "view_image",
    "create_file_link",
    "list_file_links",
    "revoke_file_link",
    "write_file",
    "edit_file",
    "delete_file_or_dir",
    "apply_patch",
    "transfer_path",
    "remote_invite",
    "remote_list_machines",
    "remote_revoke_machine",
    "remote_rename_machine",
    "playwright_run_script_tool",
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
        "environment_get",
        "run_shell",
        "run_python",
        "shell_start",
        "shell_send",
        "shell_read",
        "shell_stop",
        "shell_list",
        "job_start",
        "job_list",
        "job_tail",
        "job_stop",
        "job_retry",
        "file_list",
        "file_tree",
        "file_glob",
        "file_grep",
        "file_read",
        "image_view",
        "file_write",
        "file_edit",
        "file_delete",
        "file_patch",
        "browser_capture_tool",
        "browser_get_text_tool",
        "browser_run_script",
    }

    for name in machine_capable:
        assert "machine" in tools[name].inputSchema["properties"], name
    transfer_properties = tools["remote_transfer"].inputSchema["properties"]
    assert {"source_machine", "destination_machine"} <= set(transfer_properties)

    edit_schema = tools["file_edit"].inputSchema
    edit_definition = edit_schema["$defs"]["TextEdit"]
    assert edit_schema["properties"]["edits"]["items"] == {"$ref": "#/$defs/TextEdit"}
    assert edit_definition["additionalProperties"] is False
    assert set(edit_definition["required"]) == {"old", "new"}
    assert edit_definition["properties"]["old"]["minLength"] == 1
    assert edit_definition["properties"]["replace_all"]["type"] == "boolean"


@pytest.mark.asyncio
async def test_key_tool_descriptions_guide_tool_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert "For long-running" in tools["run_shell"].description
    assert "purpose/explanation" in tools["run_shell"].description
    assert "Git" in tools["run_shell"].description
    assert "old must match exactly" in tools["file_edit"].description
    assert "recursive=true is required" in tools["file_delete"].description
    assert "high-entropy token" in tools["link_create"].description
    assert "native MCP image content" in tools["image_view"].description
    assert "existing file-transfer protocol" in tools["image_view"].description
    assert "tool surface stays fixed" in tools["skill_list"].description
    assert "exact name returned from skill_list" in tools["skill_load"].description


@pytest.mark.asyncio
async def test_risky_tools_accept_purpose_and_explanation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    names = {
        "run_shell",
        "run_python",
        "shell_start",
        "job_start",
        "job_retry",
        "file_write",
        "file_edit",
        "file_delete",
        "file_patch",
        }

    for name in names:
        properties = tools[name].inputSchema["properties"]
        assert "purpose" in properties, name
        assert "explanation" in properties, name
