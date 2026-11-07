"""The LibreChat MCP manager is backed exclusively by LSM's nested MCP registry."""
import json

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from local_shell_mcp.auth import AuthMiddleware
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.librechat_integration import (
    issue_chat_ticket,
    may_chat_call_lsm,
    register_identity,
    set_chat_tool_policy,
)
from local_shell_mcp.settings import get_settings


@pytest.fixture
def nested_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_URL", "https://chat.example.test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "z" * 48)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    user = "a" * 24
    register_identity(user, issue_chat_ticket("owner", auth_mode="none")["ticket"])
    headers = {
        "Authorization": "Bearer " + "z" * 48,
        "X-LSM-Chat-User-Id": user,
        "X-LSM-Conversation-Id": "chat-one",
    }
    yield TestClient(build_http_app()), user, headers
    get_settings.cache_clear()


def test_nested_mcp_ui_manages_controller_registry_and_redacts_credentials(nested_client):
    client, _, headers = nested_client
    url = "/api/ui/nested-mcp"
    assert client.get(url, headers=headers).json()["data"]["servers"] == []
    registered = client.post(url, json={
        "action": "register", "name": "example", "transport": "streamable_http",
        "url": "https://example.org/mcp", "refresh": False,
    }, headers=headers)
    assert registered.status_code == 200, registered.text
    assert registered.json()["data"]["server"]["name"] == "example"
    assert client.post(url, json={
        "action": "header_set", "name": "example", "key": "Authorization", "value": "Bearer private",
    }, headers=headers).status_code == 200
    listed = client.get(url, headers=headers).json()["data"]["servers"]
    assert len(listed) == 1
    assert listed[0]["name"] == "example"
    assert listed[0]["header_keys"] == ["Authorization"]
    assert "private" not in json.dumps(listed)
    updated = client.post(url, json={
        "action": "update", "name": "example", "transport": "streamable_http",
        "url": "https://example.org/changed",
    }, headers=headers)
    assert updated.status_code == 200, updated.text
    updated_server = updated.json()["data"]["server"]
    assert updated_server["url"] == "https://example.org/changed"
    assert updated_server["header_keys"] == ["Authorization"]
    assert updated_server["refreshed_at"] is None
    assert client.post(url, json={
        "action": "disable", "name": "example",
    }, headers=headers).json()["data"]["server"]["enabled"] is False
    assert client.post(url, json={
        "action": "enable", "name": "example",
    }, headers=headers).json()["data"]["server"]["enabled"] is True
    assert client.post(url, json={"action": "remove", "name": "example"}, headers=headers).json()["data"]["removed"]
    assert client.get(url, headers=headers).json()["data"]["servers"] == []


def test_nested_mcp_ui_does_not_accept_arbitrary_controller_calls(nested_client):
    client, _, headers = nested_client
    url = "/api/ui/nested-mcp"
    assert client.post(url, json={"action": "shell_start"}, headers=headers).status_code == 400
    assert client.post(url, json={"action": "list", "extra": 1}, headers=headers).status_code == 400
    assert client.post(url, json=[], headers=headers).status_code == 400
    assert client.post(url, json={"action": "register", "name": "../bad"}, headers=headers).status_code == 400


def test_external_mcp_independent_of_lsm_and_no_manage(nested_client):
    _, user, headers = nested_client
    set_chat_tool_policy(user, "chat-one", lsm_enabled=False, mcp_enabled=True)

    async def reply(_request):
        return JSONResponse({"ok": True})

    client = TestClient(AuthMiddleware(Starlette(routes=[Route("/mcp", reply, methods=["POST"])])))

    def call(name, conversation_id="chat-one"):
        return client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "tools/call", "id": 1,
            "params": {"name": name, "arguments": {}},
        }, headers={**headers, "X-LSM-Conversation-Id": conversation_id})

    for tool in ("mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call"):
        assert may_chat_call_lsm(user, "chat-one", tool)
        assert call(tool).status_code == 200
    for tool in ("mcp_manage", "run_shell", "file_read", "gui_action"):
        assert not may_chat_call_lsm(user, "chat-one", tool)
        assert call(tool).status_code == 403

    # Mixing allowed and denied tools within one RPC batch fails closed.
    mixed = [{
        "jsonrpc": "2.0", "method": "tools/call", "id": index + 1,
        "params": {"name": name, "arguments": {}},
    } for index, name in enumerate(("mcp_tool_search", "mcp_manage"))]
    assert client.post("/mcp", json=mixed, headers=headers).status_code == 403

    set_chat_tool_policy(user, "chat-one", lsm_enabled=True, mcp_enabled=False)
    assert call("run_shell").status_code == 200
    assert call("mcp_tool_search").status_code == 403
    assert call("mcp_tool_call").status_code == 403


def test_nested_mcp_requires_bridge_identity(nested_client):
    client, _, headers = nested_client
    url = "/api/ui/nested-mcp"
    invalid = {**headers, "Authorization": "Bearer wrong"}
    assert client.get(url, headers=invalid).status_code == 401
    assert client.post(url, json={"action": "list"}, headers=invalid).status_code == 401


def test_nested_mcp_connection_edits_cover_transport_variants(nested_client, tmp_path, monkeypatch):
    import asyncio

    from local_shell_mcp.dynamic_mcp import DynamicMCPManager

    _, _, _ = nested_client
    manager = DynamicMCPManager(tmp_path / "state")

    def manage(**kwargs):
        return asyncio.run(manager.manage(**kwargs))

    manage(action="register", name="connection", transport="streamable_http",
           url="https://example.org/mcp", refresh=False,
           env={"TOKEN": "private"}, headers={"Authorization": "Bearer secret"})
    # An unchanged HTTP transport may still accept changes to private settings.
    first = manage(action="update", name="connection", url="https://example.net/mcp",
                   env={"TOKEN": "replacement"}, headers={"X-Custom": "value"})
    assert first["server"]["url"] == "https://example.net/mcp"
    assert first["server"]["env_keys"] == ["TOKEN"]
    assert first["server"]["header_keys"] == ["X-Custom"]
    assert "replacement" not in str(first)
    assert first["server"]["refreshed_at"] is None

    # Migrate HTTP -> stdio, including executable policy, argv and workdir.
    converted = manage(action="update", name="connection", transport="stdio",
                       command="echo", args=["test"], cwd=str(tmp_path))
    assert converted["server"]["transport"] == "stdio"
    assert converted["server"]["command"] == "echo"
    assert converted["server"]["args"] == ["test"]
    assert converted["server"]["cwd"] == str(tmp_path)
    assert converted["server"]["url"] is None
    assert converted["server"]["header_keys"] == ["X-Custom"]

    # Stdio can be updated without spelling out its transport or all fields.
    modified = manage(action="update", name="connection", command="echo",
                      args=["one", "two"], cwd="")
    assert modified["server"]["args"] == ["one", "two"]
    assert modified["server"]["command"] == "echo"

    # Return to HTTP, dropping stdin command fields without losing credentials.
    converted_back = manage(action="update", name="connection", transport="streamable_http",
                            url="https://example.org/replaced")
    assert converted_back["server"]["transport"] == "streamable_http"
    assert converted_back["server"]["command"] is None
    assert converted_back["server"]["args"] == []
    assert converted_back["server"]["header_keys"] == ["X-Custom"]
    assert manage(action="get", name="connection")["server"]["url"] == "https://example.org/replaced"

    # Invalid changes must not replace the persisted last-good configuration.
    with pytest.raises(ValueError, match="absolute HTTP"):
        manage(action="update", name="connection", url="file:///tmp/mcp")
    with pytest.raises(ValueError, match="stdio"):
        manage(action="update", name="connection", transport="stdio")
    with pytest.raises(ValueError, match="transport"):
        manage(action="update", name="connection", transport="bad-protocol")
    with pytest.raises(ValueError, match="values must be strings"):
        manage(action="update", name="connection", env={"BAD": 123})
    with pytest.raises(ValueError, match="values must be strings"):
        manage(action="update", name="connection", headers={"BAD": None})
    assert manage(action="get", name="connection")["server"]["url"] == "https://example.org/replaced"

    # With local process execution forbidden, HTTP editing still works but stdio fails closed.
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="disabled"):
            manage(action="update", name="connection", transport="stdio", command="echo")
        assert manage(action="update", name="connection", url="https://example.org/ok")["server"]["url"] == "https://example.org/ok"
    finally:
        get_settings.cache_clear()


def test_nested_mcp_ui_scope_restrictions(tmp_path, monkeypatch):
    from local_shell_mcp.http_app import build_http_app

    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_URL", "https://chat.example.test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "z" * 48)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    get_settings.cache_clear()
    try:
        user = "b" * 24
        register_identity(user, issue_chat_ticket("limited", scopes="shell:read")["ticket"])
        headers = {"Authorization": "Bearer " + "z" * 48, "X-LSM-Chat-User-Id": user}
        client = TestClient(build_http_app())
        assert client.get("/api/ui/nested-mcp", headers=headers).status_code == 200
        assert client.post("/api/ui/nested-mcp", json={"action": "list"}, headers=headers).status_code == 403
        register_identity(user, issue_chat_ticket("limited", scopes="shell:read shell:execute")["ticket"])
        assert client.post("/api/ui/nested-mcp", json={"action": "list"}, headers=headers).status_code == 200
        assert client.post("/api/ui/nested-mcp", json={"action": None}, headers=headers).status_code == 400
        assert client.post("/api/ui/nested-mcp", json={"action": 7}, headers=headers).status_code == 400
    finally:
        get_settings.cache_clear()
