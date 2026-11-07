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
