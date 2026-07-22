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
            "replacement": "environment_info",
            "removed_in": "3.0.0",
            "help_url": DEPRECATED_TOOL_HELP_URL,
            "assistant_instruction": (
                "Do not retry this deprecated tool. Explain to the user that ChatGPT is using "
                "a stale local-shell-mcp tool snapshot and ask them to refresh the LSM App's "
                "tools, or remove and re-add the App if refresh is unavailable. Refer them to "
                f"{DEPRECATED_TOOL_HELP_URL}. After the cache is updated, use the replacement "
                "tool 'environment_info'."
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
    assert result["data"]["replacement"] == "run_shell_tool"
    assert "refresh the LSM App's tools" in result["data"]["assistant_instruction"]
