from __future__ import annotations

from mcp.server import fastmcp as fastmcp_module

from local_shell_mcp.deprecated_tools import (
    DEPRECATED_TOOL_HELP_URL,
    DeprecatedToolFastMCP,
    install_deprecated_tool_tombstones,
)


async def test_deprecated_tools_are_tombstones_not_listed_tools() -> None:
    original = fastmcp_module.FastMCP
    try:
        install_deprecated_tool_tombstones()
        assert fastmcp_module.FastMCP is DeprecatedToolFastMCP

        install_deprecated_tool_tombstones()
        assert fastmcp_module.FastMCP is DeprecatedToolFastMCP

        mcp = fastmcp_module.FastMCP("test")

        @mcp.tool()
        def current_tool() -> str:
            return "current"

        listed = {tool.name for tool in await mcp.list_tools()}
        assert listed == {"current_tool"}
        assert "version_info" not in listed

        result = await mcp.call_tool("version_info", {})
        assert result["ok"] is False
        assert result["data"] == {
            "status": "stale_tool_snapshot",
            "deprecated_tool": "version_info",
            "replacement": "environment_get",
            "removed_in": "3.0.0",
            "help_url": DEPRECATED_TOOL_HELP_URL,
            "assistant_instruction": (
                "Do not retry this deprecated tool. Explain to the user that ChatGPT is using "
                "a stale local-shell-mcp tool snapshot and ask them to refresh the LSM App's "
                "tools, or remove and re-add the App if refresh is unavailable. Refer them to "
                f"{DEPRECATED_TOOL_HELP_URL}. After the cache is updated, use the replacement "
                "tool 'environment_get'."
            ),
        }

        current = await mcp.call_tool("current_tool", {})
        assert current
    finally:
        fastmcp_module.FastMCP = original


async def test_remote_tombstone_points_to_unified_machine_tool() -> None:
    mcp = DeprecatedToolFastMCP("test")
    result = await mcp.call_tool("remote_run_shell_tool", {"machine": "worker"})

    assert result["data"]["status"] == "stale_tool_snapshot"
    assert result["data"]["replacement"] == "run_shell"
    assert "refresh the LSM App's tools" in result["data"]["assistant_instruction"]


async def test_browser_tombstones_point_to_browser_run_script() -> None:
    mcp = DeprecatedToolFastMCP("test")

    for name in (
        "browser_screenshot_tool",
        "browser_eval_tool",
        "browser_pdf_tool",
        "browser_capture_tool",
        "browser_get_text_tool",
        "playwright_run_script_tool",
        "remote_browser_screenshot_tool",
        "remote_browser_get_text_tool",
        "remote_browser_eval_tool",
        "remote_browser_pdf_tool",
        "remote_playwright_run_script_tool",
    ):
        result = await mcp.call_tool(name, {})
        assert result["data"]["status"] == "stale_tool_snapshot"
        assert result["data"]["replacement"] == "browser_run_script"

    renamed = await mcp.call_tool("playwright_run_script_tool", {})
    assert renamed["data"]["removed_in"] == "3.3.0"


async def test_removed_remote_surface_points_to_consolidated_tools() -> None:
    mcp = DeprecatedToolFastMCP("test")

    for name in (
        "remote_invite",
        "remote_list_machines",
        "remote_revoke_machine",
        "remote_rename_machine",
    ):
        result = await mcp.call_tool(name, {})
        assert result["data"]["replacement"] == ("remote_list" if name == "remote_list_machines" else "remote_manage")
        assert result["data"]["removed_in"] == "3.3.0"

    transfer = await mcp.call_tool("transfer_path", {})
    assert transfer["data"]["replacement"] == "remote_transfer"
    assert transfer["data"]["removed_in"] == "3.3.0"


async def test_todo_tombstones_point_to_plan_manage() -> None:
    mcp = DeprecatedToolFastMCP("test")
    for name in ("todo_read_tool", "todo_write_tool"):
        result = await mcp.call_tool(name, {})
        assert result["data"]["replacement"] == "plan_manage"
        assert result["data"]["removed_in"] == "4.0.0"


async def test_v4_tool_rename_tombstones_point_to_canonical_surface() -> None:
    mcp = DeprecatedToolFastMCP("test")
    replacements = {
        "search": "file_grep",
        "fetch": "file_read",
        "open_live_workspace": "workspace_open",
        "environment_info": "environment_get",
        "skills_list": "skill_list",
        "skill_read_file": "skill_read",
        "run_shell_tool": "run_shell",
        "run_python_tool": "run_python",
        "shell_kill": "shell_stop",
        "list_files": "file_list",
        "tree_view": "file_tree",
        "glob_search": "file_glob",
        "grep_search": "file_grep",
        "read_file": "file_read",
        "view_image": "image_view",
        "create_file_link": "link_create",
        "list_file_links": "link_list",
        "revoke_file_link": "link_revoke",
        "write_file": "file_write",
        "edit_file": "file_edit",
        "delete_file_or_dir": "file_delete",
        "apply_patch": "file_patch",
    }

    for old_name, replacement in replacements.items():
        result = await mcp.call_tool(old_name, {})
        assert result["data"]["status"] == "stale_tool_snapshot"
        assert result["data"]["replacement"] == replacement
        assert result["data"]["removed_in"] == "4.0.0"


async def test_registered_compatibility_alias_wins_over_tombstone() -> None:
    mcp = DeprecatedToolFastMCP("test")

    @mcp.tool(name="open_live_workspace")
    async def compatibility_alias() -> dict[str, bool]:
        return {"opened": True}

    _content, structured = await mcp.call_tool("open_live_workspace", {})

    assert structured == {"opened": True}
    assert "open_live_workspace" not in {tool.name for tool in await mcp.list_tools()}


async def test_other_registered_deprecated_names_remain_tombstones() -> None:
    mcp = DeprecatedToolFastMCP("test")

    @mcp.tool(name="search")
    async def accidentally_registered_deprecated_tool() -> dict[str, bool]:
        return {"called": True}

    result = await mcp.call_tool("search", {})

    assert result["data"]["status"] == "stale_tool_snapshot"
    assert result["data"]["replacement"] == "file_grep"
