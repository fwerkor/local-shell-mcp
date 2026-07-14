import json

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from local_shell_mcp.auth import _CURRENT_PRINCIPAL, Principal, _is_mcp_discovery_request
from local_shell_mcp.oauth import (
    _CLIENTS,
    _CODES,
    _authorize_form,
    issue_access_token,
    oauth_authorize_get,
    oauth_register,
    validate_bearer_token,
)
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp


def test_mcp_discovery_methods_are_unauthenticated():
    scope = {"type": "http", "path": "/mcp", "method": "POST"}
    initialize = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}).encode()
    tools_list = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    tools_call = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call"}).encode()

    assert _is_mcp_discovery_request(scope, initialize)
    assert _is_mcp_discovery_request(scope, tools_list)
    assert not _is_mcp_discovery_request(scope, tools_call)


@pytest.mark.asyncio
async def test_mcp_metadata_for_chatgpt_developer_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.com")
    get_settings.cache_clear()

    mcp = build_mcp()
    assert "local-shell-mcp.example.com" in mcp.settings.transport_security.allowed_hosts

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert tools["search"].meta["securitySchemes"][0]["type"] == "noauth"
    assert tools["environment_info"].meta["securitySchemes"][0]["type"] == "oauth2"

    def scopes(tool_name: str, scheme_index: int = 0) -> list[str]:
        return tools[tool_name].meta["securitySchemes"][scheme_index]["scopes"]

    search_fallback_scopes = scopes("search", scheme_index=1)
    assert search_fallback_scopes[0] == "shell:read"
    assert "shell:read" in scopes("audit_tail")
    assert "shell:read" in scopes("apply_patch")
    assert scopes("browser_get_text_tool")
    assert scopes("browser_screenshot_tool")
    assert all(tool.outputSchema is not None for tool in tools.values())
    assert tools["run_shell_tool"].outputSchema["title"] == "ToolResult"
    assert set(tools["run_shell_tool"].outputSchema["properties"]) == {"ok", "message", "data"}
    assert tools["search"].outputSchema["properties"]["result"]["type"] == "string"

    content, structured = await mcp.call_tool("environment_info", {})
    assert content
    assert structured["ok"] is True



@pytest.mark.asyncio
async def test_mcp_tool_execution_enforces_advertised_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    (tmp_path / "readable.txt").write_text("content", encoding="utf-8")
    mcp = build_mcp()
    principal_token = _CURRENT_PRINCIPAL.set(
        Principal(email=None, subject="read-only", claims={"scope": "shell:read"})
    )
    try:
        content, structured = await mcp.call_tool("read_file", {"path": "readable.txt"})
        assert content
        assert structured["ok"] is True
        with pytest.raises(Exception, match="shell:write"):
            await mcp.call_tool("write_file", {"path": "blocked.txt", "content": "no"})
    finally:
        _CURRENT_PRINCIPAL.reset(principal_token)

    assert not (tmp_path / "blocked.txt").exists()

@pytest.mark.asyncio
async def test_tool_annotations_are_conservative_and_mode_independent(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    command = tools["run_shell_tool"].annotations
    assert command.readOnlyHint is False
    assert command.destructiveHint is True
    assert command.idempotentHint is False
    assert command.openWorldHint is True

    assert tools["delete_file_or_dir"].annotations.destructiveHint is True
    assert tools["git_reset_tool"].annotations.destructiveHint is True
    assert tools["write_file"].annotations.openWorldHint is False
    assert tools["create_file_link"].annotations.destructiveHint is False
    assert tools["create_file_link"].annotations.openWorldHint is True
    assert tools["browser_get_text_tool"].annotations.readOnlyHint is True
    assert tools["browser_get_text_tool"].annotations.openWorldHint is True
    assert tools["remote_read_file"].annotations.readOnlyHint is True
    assert tools["remote_read_file"].annotations.openWorldHint is True
    assert tools["search"].annotations.readOnlyHint is True
    assert tools["search"].annotations.openWorldHint is False
    assert all(tool.annotations is not None for tool in tools.values())

    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    get_settings.cache_clear()
    restricted = {tool.name: tool for tool in await build_mcp().list_tools()}
    assert restricted["run_shell_tool"].annotations == command


def test_oauth_access_tokens_do_not_expire_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "test-secret-that-is-at-least-32-bytes")
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


def _oauth_test_client() -> TestClient:
    return TestClient(
        Starlette(
            routes=[
                Route("/oauth/register", oauth_register, methods=["POST"]),
                Route("/oauth/authorize", oauth_authorize_get, methods=["GET"]),
            ]
        )
    )


def test_oauth_registration_validates_redirects_and_authorize_requires_registered_s256_client(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    _CLIENTS.clear()
    _CODES.clear()
    client = _oauth_test_client()

    invalid = client.post("/oauth/register", json={"redirect_uris": ["relative/callback"]})
    assert invalid.status_code == 400

    unknown = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "unknown",
            "redirect_uri": "https://example.test/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
        },
    )
    assert unknown.status_code == 200
    assert "Unknown client_id" in unknown.text

    registered = client.post(
        "/oauth/register",
        json={"client_name": "test", "redirect_uris": ["https://example.test/callback"]},
    )
    assert registered.status_code == 201
    client_id = registered.json()["client_id"]

    no_pkce = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://example.test/callback",
        },
    )
    assert "Missing code_challenge" in no_pkce.text

    valid = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://example.test/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
        },
    )
    assert valid.status_code == 200
    assert "Approve" in valid.text
    assert "Unknown client_id" not in valid.text

    unsupported_scope = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://example.test/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "scope": "shell:read unknown:scope",
        },
    )
    assert "Unsupported OAuth scope" in unsupported_scope.text


def test_oauth_authorize_form_escapes_reflected_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    marker = chr(60) + "unsafe" + chr(62)
    response = _authorize_form(
        {
            "client_id": "client",
            "redirect_uri": f"https://example.test/cb?x={marker}",
            "resource": f"https://resource.test/{marker}",
            "scope": f"shell:read {marker}",
        },
        error=f"bad {marker}",
    )
    body = response.body.decode("utf-8")

    assert marker not in body
    assert "&lt;unsafe&gt;" in body


@pytest.mark.asyncio
async def test_read_only_tools_have_read_only_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    names = {
        "environment_info", "version_info",
        "shell_read", "shell_list", "job_list", "job_tail",
        "list_files", "tree_view", "glob_search", "grep_search", "read_file", "read_many_files",
        "list_file_links",
        "git_status_tool", "git_diff_tool", "git_log_tool", "git_show_tool",
        "secret_scan", "todo_read_tool", "audit_tail",
        "remote_list_machines", "remote_environment_info", "remote_shell_read", "remote_shell_list",
        "remote_job_list", "remote_job_tail",
        "remote_list_files", "remote_tree_view", "remote_glob_search", "remote_grep_search",
        "remote_read_file", "remote_read_many_files",
        "remote_git_status_tool", "remote_git_diff_tool", "remote_git_log_tool", "remote_git_show_tool",
    }

    for name in names:
        assert tools[name].annotations is not None, name
        assert tools[name].annotations.readOnlyHint is True, name
