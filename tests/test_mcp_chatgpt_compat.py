import json

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from local_shell_mcp import __version__
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
    ALL_OAUTH_SCOPES,
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
    initialization = mcp._mcp_server.create_initialization_options()
    assert initialization.server_version == __version__
    assert initialization.website_url == "https://fwerkor.github.io/local-shell-mcp/"
    assert initialization.icons
    assert initialization.icons[0].src == "https://fwerkor.github.io/local-shell-mcp/assets/logo.svg"
    assert initialization.icons[0].mimeType == "image/svg+xml"

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert tools["environment_get"].meta["securitySchemes"][0]["type"] == "oauth2"

    def scopes(tool_name: str, scheme_index: int = 0) -> list[str]:
        return tools[tool_name].meta["securitySchemes"][scheme_index]["scopes"]

    full_scopes = list(ALL_OAUTH_SCOPES)
    assert scopes("audit_tail") == full_scopes
    assert scopes("file_patch") == full_scopes
    assert scopes("browser_run_script") == full_scopes
    assert scopes("remote_transfer") == full_scopes
    assert all(tool.outputSchema is not None for tool in tools.values())
    assert tools["run_shell"].outputSchema["title"] == "ToolResult"
    assert set(tools["run_shell"].outputSchema["properties"]) == {"ok", "message", "data"}

    content, structured = await mcp.call_tool("environment_get", {})
    assert content
    assert structured["ok"] is True
    assert structured["data"]["settings"]["default_timeout_s"] == 10
    assert structured["data"]["settings"]["max_timeout_s"] == 120



@pytest.mark.asyncio
async def test_mcp_tool_execution_uses_one_full_scope_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    (tmp_path / "readable.txt").write_text("content", encoding="utf-8")
    mcp = build_mcp()
    partial_token = _CURRENT_PRINCIPAL.set(
        Principal(email=None, subject="partial", claims={"scope": "shell:read"})
    )
    try:
        with pytest.raises(Exception, match="shell:write"):
            await mcp.call_tool("file_read", {"path": "readable.txt"})
    finally:
        _CURRENT_PRINCIPAL.reset(partial_token)

    full_token = _CURRENT_PRINCIPAL.set(
        Principal(
            email=None,
            subject="full",
            claims={"scope": " ".join(ALL_OAUTH_SCOPES)},
        )
    )
    try:
        content, structured = await mcp.call_tool("file_read", {"path": "readable.txt"})
        assert content
        assert structured["ok"] is True
        _, written = await mcp.call_tool(
            "file_write", {"path": "written.txt", "content": "yes"}
        )
        assert written["ok"] is True
    finally:
        _CURRENT_PRINCIPAL.reset(full_token)

    assert (tmp_path / "written.txt").read_text(encoding="utf-8") == "yes"


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
            await mcp.call_tool("environment_get", {"machine": "worker"})
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

    command = tools["run_shell"].annotations
    assert command.readOnlyHint is False
    assert command.destructiveHint is True
    assert command.idempotentHint is False
    assert command.openWorldHint is True

    assert tools["file_delete"].annotations.destructiveHint is True
    assert tools["remote_transfer"].annotations.destructiveHint is True
    assert tools["remote_transfer"].annotations.openWorldHint is True
    assert tools["remote_manage"].annotations.destructiveHint is True
    assert tools["remote_manage"].annotations.openWorldHint is True
    assert tools["file_write"].annotations.openWorldHint is True
    assert tools["link_create"].annotations.destructiveHint is False
    assert tools["link_create"].annotations.openWorldHint is True
    assert tools["browser_snapshot"].annotations.readOnlyHint is True
    assert tools["browser_snapshot"].annotations.openWorldHint is True
    assert tools["browser_session"].annotations.destructiveHint is True
    assert tools["browser_session"].annotations.openWorldHint is True
    assert tools["browser_act"].annotations.destructiveHint is True
    assert tools["browser_act"].annotations.openWorldHint is True
    assert tools["mcp_tool_search"].annotations.readOnlyHint is True
    assert tools["mcp_tool_search"].annotations.openWorldHint is False
    assert tools["mcp_tool_inspect"].annotations.readOnlyHint is True
    assert tools["mcp_tool_inspect"].annotations.openWorldHint is False
    assert tools["mcp_manage"].annotations.destructiveHint is True
    assert tools["mcp_manage"].annotations.openWorldHint is True
    assert tools["mcp_tool_call"].annotations.destructiveHint is True
    assert tools["mcp_tool_call"].annotations.openWorldHint is True
    assert tools["plan_manage"].annotations.destructiveHint is True
    assert tools["file_read"].annotations.readOnlyHint is True
    assert tools["file_read"].annotations.openWorldHint is True
    assert tools["image_view"].annotations.readOnlyHint is True
    assert tools["image_view"].annotations.openWorldHint is True
    assert "session_run_id" in tools["run_shell"].inputSchema["properties"]
    assert "session_run_id" in tools["plan_manage"].inputSchema["properties"]
    assert "session_run_id" in tools["session_manage"].inputSchema["properties"]
    assert all(tool.annotations is not None for tool in tools.values())

    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    get_settings.cache_clear()
    restricted = {tool.name: tool for tool in await build_mcp().list_tools()}
    assert restricted["run_shell"].annotations == command


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
    assert claims["scope"] == "shell:execute"


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

    ignored_scope = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://example.test/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "scope": "shell:read git:write unknown:scope",
        },
    )
    assert "Unsupported OAuth scope" not in ignored_scope.text


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
        "environment_get",
        "shell_read",
        "shell_list",
        "job_list",
        "job_tail",
        "file_list",
        "file_tree",
        "file_glob",
        "file_grep",
        "file_read",
        "image_view",
        "link_list",
        "secret_scan",
        "audit_tail",
        "browser_snapshot",
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
