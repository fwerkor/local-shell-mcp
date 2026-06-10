import json

import pytest

import local_shell_mcp.tools as tools_module
from local_shell_mcp.agent_mcp import AgentMcpTool
from local_shell_mcp.auth import _is_mcp_discovery_request
from local_shell_mcp.config.settings import get_settings
from local_shell_mcp.oauth import issue_access_token, validate_bearer_token
from local_shell_mcp.tools import build_mcp


def test_mcp_discovery_methods_are_unauthenticated():
    scope = {"type": "http", "path": "/mcp", "method": "POST"}
    initialize = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    ).encode()
    tools_list = json.dumps(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    ).encode()
    tools_call = json.dumps(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call"}
    ).encode()

    assert _is_mcp_discovery_request(scope, initialize)
    assert _is_mcp_discovery_request(scope, tools_list)
    assert not _is_mcp_discovery_request(scope, tools_call)


@pytest.mark.asyncio
async def test_mcp_metadata_for_chatgpt_developer_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.com"
    )
    get_settings.cache_clear()

    mcp = build_mcp()
    assert (
        "local-shell-mcp.example.com"
        in mcp.settings.transport_security.allowed_hosts
    )

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert tools["search"].meta["securitySchemes"][0]["type"] == "noauth"
    assert (
        tools["environment_info"].meta["securitySchemes"][0]["type"] == "oauth2"
    )


@pytest.mark.asyncio
async def test_full_container_mode_marks_command_tools_for_auto_approval(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    annotations = tools["run_shell_tool"].annotations
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False

    assert tools["search"].annotations.readOnlyHint is True


@pytest.mark.asyncio
async def test_full_container_mode_does_not_auto_approve_agent_mcp_proxies(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://docs.example/mcp"}
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object"},
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            return {"ok": True}

    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert tools["run_shell_tool"].annotations.openWorldHint is False
    assert tools["call_agent_mcp_tool"].annotations is None
    assert tools["agent_mcp__docs__search"].annotations is None


@pytest.mark.asyncio
async def test_default_mode_does_not_mark_command_tools_for_auto_approval(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert tools["run_shell_tool"].annotations is None


def test_oauth_access_tokens_do_not_expire_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "test-secret")
    monkeypatch.delenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_ISSUER", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_RESOURCE", raising=False)
    get_settings.cache_clear()

    token = issue_access_token(
        client_id="test-client",
        scope="shell:execute",
        resource="http://127.0.0.1:8765",
    )
    claims = validate_bearer_token(token)

    assert "exp" not in claims
    assert claims["client_id"] == "test-client"
