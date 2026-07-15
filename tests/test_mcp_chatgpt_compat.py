import json

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from local_shell_mcp.auth import (
    _CURRENT_PRINCIPAL,
    Principal,
    RequestBodyLimitMiddleware,
    _is_mcp_discovery_request,
)
from local_shell_mcp.main import _build_mcp_http_app
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


def test_mcp_discovery_request_classification():
    scope = {"type": "http", "path": "/mcp", "method": "POST"}
    initialize = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}).encode()
    tools_list = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    tools_call = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call"}).encode()

    assert _is_mcp_discovery_request(scope, initialize)
    assert _is_mcp_discovery_request(scope, tools_list)
    assert not _is_mcp_discovery_request(scope, tools_call)
    assert not _is_mcp_discovery_request({**scope, "method": "GET"}, None)
    assert not _is_mcp_discovery_request({**scope, "method": "DELETE"}, None)
    assert _is_mcp_discovery_request({**scope, "method": "OPTIONS"}, None)


@pytest.mark.asyncio
async def test_request_body_limit_counts_chunked_payloads(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", "8")
    get_settings.cache_clear()
    called = False

    async def inner(scope, receive, send):  # noqa: ANN001, ARG001
        nonlocal called
        called = True

    app = RequestBodyLimitMiddleware(inner)
    messages = iter(
        [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"6789", "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):  # noqa: ANN001
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "POST",
            "path": "/mcp",
            "headers": [],
        },
        receive,
        send,
    )

    assert called is False
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


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
    assert scopes("browser_capture_tool")
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
async def test_machine_argument_requires_remote_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()
    mcp = build_mcp()
    principal_token = _CURRENT_PRINCIPAL.set(
        Principal(email=None, subject="local-only", claims={"scope": "shell:read"})
    )
    try:
        with pytest.raises(Exception, match="remote:use"):
            await mcp.call_tool("environment_info", {"machine": "worker"})
    finally:
        _CURRENT_PRINCIPAL.reset(principal_token)

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
    assert tools["transfer_path"].annotations.destructiveHint is True
    assert tools["write_file"].annotations.openWorldHint is True
    assert tools["create_file_link"].annotations.destructiveHint is False
    assert tools["create_file_link"].annotations.openWorldHint is True
    assert tools["browser_get_text_tool"].annotations.readOnlyHint is True
    assert tools["browser_get_text_tool"].annotations.openWorldHint is True
    assert tools["read_file"].annotations.readOnlyHint is True
    assert tools["read_file"].annotations.openWorldHint is True
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
        "environment_info",
        "shell_read",
        "shell_list",
        "job_list",
        "job_tail",
        "list_files",
        "tree_view",
        "glob_search",
        "grep_search",
        "read_file",
        "list_file_links",
        "secret_scan",
        "todo_read_tool",
        "audit_tail",
        "browser_get_text_tool",
        "remote_list_machines",
    }

    for name in names:
        assert tools[name].annotations is not None, name
        assert tools[name].annotations.readOnlyHint is True, name



def _mcp_initialize_payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    }


def _mcp_headers(**extra: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        **extra,
    }


def test_mcp_requires_auth_for_initialize_and_delete_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_OAUTH_JWT_SECRET",
        "test-secret-that-is-definitely-at-least-32-bytes",
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.delenv("LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY", raising=False)
    get_settings.cache_clear()

    token = issue_access_token(
        client_id="test-client",
        scope="shell:read",
        resource="http://testserver",
        issuer="http://testserver",
    )
    mcp = build_mcp()
    with TestClient(_build_mcp_http_app(mcp), base_url="http://testserver") as client:
        anonymous = client.post("/mcp", json=_mcp_initialize_payload(), headers=_mcp_headers())
        assert anonymous.status_code == 401

        initialized = client.post(
            "/mcp",
            json=_mcp_initialize_payload(),
            headers=_mcp_headers(authorization=f"Bearer {token}"),
        )
        assert initialized.status_code == 200
        session_id = initialized.headers["mcp-session-id"]

        unauthenticated_delete = client.delete(
            "/mcp",
            headers={
                "accept": "application/json",
                "mcp-session-id": session_id,
                "mcp-protocol-version": "2025-06-18",
            },
        )
        assert unauthenticated_delete.status_code == 401

        ping = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers=_mcp_headers(
                authorization=f"Bearer {token}",
                **{
                    "mcp-session-id": session_id,
                    "mcp-protocol-version": "2025-06-18",
                },
            ),
        )
        assert ping.status_code == 200


def test_mcp_sessions_have_idle_timeout_and_hard_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S", "7")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MCP_MAX_SESSIONS", "2")
    get_settings.cache_clear()

    mcp = build_mcp()
    app = _build_mcp_http_app(mcp)
    assert mcp._session_manager.session_idle_timeout == 7

    with TestClient(app, base_url="http://testserver") as client:
        first = client.post("/mcp", json=_mcp_initialize_payload(), headers=_mcp_headers())
        second = client.post("/mcp", json=_mcp_initialize_payload(), headers=_mcp_headers())
        rejected = client.post("/mcp", json=_mcp_initialize_payload(), headers=_mcp_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert rejected.status_code == 429
    assert rejected.json()["error"] == "mcp_session_limit"
