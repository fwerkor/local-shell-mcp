"""Nested MCP dynamic transport regression: SSE support remains optional."""

import pytest

from local_shell_mcp.dynamic_mcp import DynamicMCPManager, DynamicMCPServer


def test_sse_is_accepted_for_existing_mcp_servers(tmp_path):
    server = DynamicMCPServer(name="external", transport="sse", url="https://mcp.example.test/sse")
    DynamicMCPManager(tmp_path)._validate_config(server)
    assert server.to_json()["url"] == "https://mcp.example.test/sse"
    with pytest.raises(ValueError, match="absolute HTTP"):
        DynamicMCPManager(tmp_path)._validate_config(
            DynamicMCPServer(name="external", transport="sse", url="file:///etc/passwd"),
        )
    with pytest.raises(ValueError, match="only valid for stdio"):
        DynamicMCPManager(tmp_path)._validate_config(
            DynamicMCPServer(name="external", transport="sse", url="https://mcp.example.test/sse", command="bash"),
        )
