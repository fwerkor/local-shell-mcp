"""Authorization and error-path regression tests for embedded LibreChat."""

import json
import time

import pytest
from starlette.testclient import TestClient

from local_shell_mcp.librechat_integration import (
    is_bridge_service,
    issue_chat_ticket,
    local_upload_path,
    may_chat_call_lsm,
    principal_for_chat_user,
    register_identity,
)
from local_shell_mcp.state_store import FileStateStore


@pytest.fixture(autouse=True)
def bridge_config(monkeypatch, tmp_path):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_URL", "https://chat.example.test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "x" * 48)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_bridge_grant_expiration_and_noauth(tmp_path, monkeypatch):
    from local_shell_mcp import librechat_integration as bridge

    store = FileStateStore(tmp_path)
    monkeypatch.setattr("local_shell_mcp.state_store.get_state_store", lambda: store)
    user_id = "a" * 24
    with pytest.raises(PermissionError, match="expired"):
        issue_chat_ticket("subject", grant_expires_at=int(time.time()) - 10)
    register_identity(user_id, issue_chat_ticket("subject", auth_mode="none")["ticket"])
    assert principal_for_chat_user(user_id)["auth_mode"] == "none"
    assert may_chat_call_lsm(user_id, "new")
    register_identity(user_id, issue_chat_ticket("subject")["ticket"])
    monkeypatch.setattr(bridge.time, "time", lambda: 4102444800)
    with pytest.raises(PermissionError, match="expired"):
        principal_for_chat_user(user_id)


def test_corrupt_identity_and_invalid_inputs(tmp_path, monkeypatch):
    store = FileStateStore(tmp_path)
    monkeypatch.setattr("local_shell_mcp.state_store.get_state_store", lambda: store)
    user_id = "b" * 24
    key = f"librechat-bridge/identities/{user_id}.json"
    store.write_bytes(key, json.dumps({"subject": None, "auth_mode": "none"}).encode())
    with pytest.raises(PermissionError, match="Invalid LibreChat identity"):
        principal_for_chat_user(user_id)
    for bad in ("", "x" * 1025):
        with pytest.raises(PermissionError):
            local_upload_path(bad, "file.txt", tmp_path)
    with pytest.raises(ValueError):
        local_upload_path("owner", "x" * 201, tmp_path)
    with pytest.raises(ValueError):
        local_upload_path("owner", 1, tmp_path)
    with pytest.raises(ValueError):
        local_upload_path("owner", "foo/..", tmp_path)
    store.write_bytes(key, json.dumps({"subject": "owner", "auth_mode": "none"}).encode())
    with pytest.raises(ValueError):
        may_chat_call_lsm(user_id, "../invalid")


def test_bridge_service_secret_auth(monkeypatch):
    class Request:
        def __init__(self, authorization):
            self.headers = {"authorization": authorization}

    assert is_bridge_service(Request("Bearer " + "x" * 48))
    assert not is_bridge_service(Request("Bearer wrong"))
    assert not is_bridge_service(Request("not bearer"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "short")
    assert not is_bridge_service(Request("Bearer short"))


def test_bridge_api_policy_and_error_paths():
    from local_shell_mcp.http_app import build_http_app

    client = TestClient(build_http_app())
    user_id = "c" * 24
    ticket = client.post("/api/ui/librechat/ticket", json={})
    assert ticket.status_code == 200
    token = ticket.json()["data"]["ticket"]
    headers = {"Authorization": "Bearer " + "x" * 48}
    assert client.post("/api/ui/librechat/identity", json={"user_id": user_id, "ticket": "invalid"}, headers=headers).status_code == 400
    assert client.post("/api/ui/librechat/identity", json={"user_id": user_id, "ticket": token}, headers=headers).status_code == 200
    assert client.post("/api/ui/librechat/identity", json={"user_id": user_id, "ticket": token}, headers=headers).status_code == 200
    session = "/api/ui/librechat/session"
    assert client.post(session, json={"user_id": user_id}, headers=headers).status_code == 200
    assert client.post(session, json={"user_id": user_id}).status_code == 403
    assert client.post(session, json={"user_id": "d" * 24}, headers=headers).status_code == 401
    uri = "/api/ui/librechat/policy"
    body = {"user_id": user_id, "conversation_id": "chat-1", "lsm": False}
    assert client.post(uri, json=body).status_code == 403
    assert client.post(uri, json=body, headers=headers).status_code == 200
    assert not may_chat_call_lsm(user_id, "chat-1")
    assert client.post(uri, json={**body, "lsm": True}, headers=headers).status_code == 200
    assert may_chat_call_lsm(user_id, "chat-1")
    for invalid in ({**body, "lsm": "false"}, {**body, "conversation_id": "../x"}, {**body, "user_id": "d" * 24}):
        assert client.post(uri, json=invalid, headers=headers).status_code == 400
    assert client.post(uri, json=[], headers=headers).status_code == 400
    assert client.post("/api/ui/librechat/identity", json=[], headers=headers).status_code == 400
    assert client.post("/api/ui/librechat/upload?name=bad.txt", content=b"").status_code == 400
    assert client.post("/api/ui/librechat/upload?name=bad.txt", content=b"data", headers={"Content-Length": "0"}).status_code == 400


def test_librechat_private_mcp_host_does_not_disable_rebinding_protection(monkeypatch):
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.tools import _transport_security_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_PORT", "8766")
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_INTERNAL_HOST", "host.docker.internal")
    get_settings.cache_clear()
    security = _transport_security_settings()
    assert security.enable_dns_rebinding_protection
    assert "local-shell-mcp:8766" in security.allowed_hosts
    assert "host.docker.internal:8766" in security.allowed_hosts
    assert "evil.example:8766" not in security.allowed_hosts

    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_INTERNAL_HOST", "evil.example")
    with pytest.raises(ValueError, match="Unsupported LibreChat"):
        _transport_security_settings()
    monkeypatch.delenv("LOCAL_SHELL_MCP_LIBRECHAT_URL")
    monkeypatch.delenv("LOCAL_SHELL_MCP_LIBRECHAT_INTERNAL_HOST")
    security = _transport_security_settings()
    assert "local-shell-mcp:8766" not in security.allowed_hosts
