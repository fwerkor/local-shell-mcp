from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from local_shell_mcp import hosted_chat, human_ui
from local_shell_mcp import hosted_chat_store as module
from local_shell_mcp.hosted_chat_store import HostedChatRunner, HostedChatStore
from local_shell_mcp.settings import get_settings


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED", "true")
    get_settings.cache_clear()
    store = HostedChatStore(prefix="hosted-chat-api-edge")
    runner = HostedChatRunner()
    monkeypatch.setattr(module, "hosted_chat_store", store)
    monkeypatch.setattr(module, "hosted_chat_runner", runner)
    fake_session = Mock()
    fake_session.get.return_value = {"session_id": "s_existing"}
    monkeypatch.setattr(human_ui, "get_session_runtime_manager", lambda: fake_session)
    with TestClient(Starlette(routes=human_ui.ui_routes())) as client:
        yield client, store, runner, fake_session
    get_settings.cache_clear()


def create_profile(client, name="Test"):
    response = client.post("/api/ui/hosted-chat/profile-save", json={
        "name": name, "model": "model", "endpoint": "https://example.org/v1", "api_key": "secret",
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def create_chat(client, pid, **additional):
    response = client.post("/api/ui/hosted-chat/conversation-create", json={"profile_id": pid, **additional})
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def test_http_profile_lifecycle_and_unsupported_requests(api):
    client, store, runner, _ = api
    pid = create_profile(client)
    for method, url, body, status in (
        ("GET", "/api/ui/hosted-chat/unknown", None, 404),
        ("POST", "/api/ui/hosted-chat/unknown", {}, 404),
        ("POST", "/api/ui/hosted-chat/profile-save", ["bad"], 400),
        ("POST", "/api/ui/hosted-chat/profile-delete", {}, 400),
        ("POST", "/api/ui/hosted-chat/profile-save", {"name": "bad"}, 400),
        ("GET", "/api/ui/hosted-chat/conversation?id=c_missing", None, 400),
    ):
        response = client.request(method, url, json=body) if body is not None else client.request(method, url)
        assert response.status_code == status, (method, url, response.text)
    assert client.post("/api/ui/hosted-chat/profile-delete", json={"id": pid}).status_code == 200
    assert pid not in [
        profile["id"] for profile in client.get("/api/ui/hosted-chat/profiles").json()["data"]
    ]


def test_http_conversation_update_validates_attached_session_and_profile(api):
    client, store, runner, fake_session = api
    pid = create_profile(client)
    pid2 = create_profile(client, "Alternative")
    cid = create_chat(client, pid, session_id="s_existing")
    fake_session.get.assert_called()
    response = client.post("/api/ui/hosted-chat/conversation-update", json={
        "id": cid, "title": " ", "profile_id": pid2, "session_id": "s_existing",
    })
    assert response.status_code == 200, response.text
    value = response.json()["data"]
    assert value["title"] == "New chat"
    assert value["profile_id"] == pid2
    assert value["session_id"] == "s_existing"
    response = client.post("/api/ui/hosted-chat/conversation-update", json={
        "id": cid, "session_id": "",
    })
    assert response.json()["data"]["session_id"] is None
    response = client.post("/api/ui/hosted-chat/conversation-update", json={
        "id": cid, "profile_id": "p_nonexistent",
    })
    assert response.status_code == 400
    fake_session.get.side_effect = ValueError("Unknown LSM Session")
    response = client.post("/api/ui/hosted-chat/conversation-create", json={
        "profile_id": pid, "session_id": "s_unknown",
    })
    assert response.status_code == 400
    original_reconcile = runner.reconcile
    runner.reconcile = Mock(return_value={"status": "running"})
    assert client.post("/api/ui/hosted-chat/conversation-delete", json={"id": cid}).status_code == 400
    runner.reconcile = original_reconcile
    assert client.post("/api/ui/hosted-chat/conversation-delete", json={"id": cid}).status_code == 200


def test_http_send_stop_and_app_bridge_are_allowlisted(api, monkeypatch):
    client, store, runner, _ = api
    pid = create_profile(client)
    cid = create_chat(client, pid)
    start = AsyncMock(return_value={"status": "running"})
    stop = Mock()
    monkeypatch.setattr(runner, "start", start)
    monkeypatch.setattr(runner, "stop", stop)
    response = client.post("/api/ui/hosted-chat/send", json={"id": cid, "text": "hello"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "running"
    assert start.await_args.args[0] and start.await_args.args[1] == cid
    assert start.await_args.args[-2].startswith("http://")
    assert client.post("/api/ui/hosted-chat/stop", json={"id": cid}).status_code == 200
    stop.assert_called_once()
    mcp_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})
    mcp_resource = AsyncMock(return_value={"contents": [{"mimeType": "text/html", "text": "demo"}]})
    monkeypatch.setattr(hosted_chat, "call_mcp", mcp_tool)
    monkeypatch.setattr(hosted_chat, "read_mcp_resource", mcp_resource)
    for payload, expected in (
        ({"name": "run_shell", "arguments": {}}, 403),
        ({"name": "workspace_open", "arguments": "wrong"}, 400),
        ({"name": "live_workspace_reconnect", "arguments": {}}, 200),
        ({"name": "workspace_open", "arguments": {"session_id": "s_existing"}}, 200),
    ):
        response = client.post("/api/ui/hosted-chat/tool", json=payload)
        assert response.status_code == expected, response.text
    assert mcp_tool.await_count == 2
    for payload, expected in (
        ({"uri": "file:///etc/passwd"}, 403),
        ({"uri": "ui://local-shell-mcp/live-workspace"}, 200),
    ):
        response = client.post("/api/ui/hosted-chat/resource", json=payload)
        assert response.status_code == expected, response.text
    mcp_resource.assert_awaited_once()


def test_http_unexpected_storage_errors_are_private(api, monkeypatch):
    client, store, _, _ = api
    def fail(_subject):
        raise RuntimeError("sensitive internal database token")
    monkeypatch.setattr(store, "profiles", fail)
    response = client.get("/api/ui/hosted-chat/profiles")
    assert response.status_code == 502
    assert "sensitive internal database token" not in response.text


def test_http_rejects_edits_to_running_conversation(api, monkeypatch):
    client, store, _, _ = api
    monkeypatch.setattr(human_ui, "_logical_session_subject", lambda *_, **__: "running-user")
    pid = create_profile(client)
    cid = create_chat(client, pid)
    store.update_conversation("running-user", cid, updater=lambda r: {**r, "status": "running"})
    response = client.post("/api/ui/hosted-chat/conversation-update", json={
        "id": cid, "title": "changed",
    })
    assert response.status_code == 400
    assert "running" in response.text


def test_http_requires_bearer_for_send_and_app_actions(api, monkeypatch):
    client, store, runner, _ = api
    monkeypatch.setattr(human_ui, "_require_ui_scopes", lambda *_: None)
    monkeypatch.setattr(human_ui, "_logical_session_subject", lambda *_, **__: "secured-user")
    settings = get_settings().model_copy(update={"auth_mode": "oauth", "host": "::"})
    monkeypatch.setattr(human_ui, "get_settings", lambda: settings)
    pid = create_profile(client)
    cid = create_chat(client, pid)
    for action, payload in (
        ("send", {"id": cid, "text": "hi"}),
        ("tool", {"name": "workspace_open", "arguments": {}}),
        ("resource", {"uri": "ui://local-shell-mcp/live-workspace"}),
    ):
        response = client.post(f"/api/ui/hosted-chat/{action}", json=payload)
        assert response.status_code == 401, (action, response.text)

    start = AsyncMock(return_value={"status": "running"})
    monkeypatch.setattr(runner, "start", start)
    response = client.post(
        "/api/ui/hosted-chat/send", json={"id": cid, "text": "hi"},
        headers={"Authorization": "Bearer example"},
    )
    assert response.status_code == 200, response.text
    assert start.await_args.args[-2].startswith("http://127.0.0.1:")
    settings = settings.model_copy(update={"host": "2001:db8::1"})
    monkeypatch.setattr(human_ui, "get_settings", lambda: settings)
    response = client.post(
        "/api/ui/hosted-chat/send", json={"id": cid, "text": "hi again"},
        headers={"Authorization": "Bearer example"},
    )
    assert response.status_code == 200
    assert start.await_args.args[-2].startswith("http://[2001:db8::1]:")


def test_http_rejects_session_update_when_session_unknown(api, monkeypatch):
    client, store, _, fake_session = api
    pid = create_profile(client)
    cid = create_chat(client, pid)
    fake_session.get.side_effect = ValueError("Unknown LSM Session")
    response = client.post("/api/ui/hosted-chat/conversation-update", json={
        "id": cid, "session_id": "s_nonexistent",
    })
    assert response.status_code == 400
    assert "Unknown LSM Session" in response.text


def test_hosted_chat_disabled_in_http_only_mode(api, monkeypatch):
    client, *_ = api
    settings = get_settings().model_copy(update={"mode": "http"})
    monkeypatch.setattr(human_ui, "get_settings", lambda: settings)
    response = client.get("/api/ui/bootstrap")
    assert response.status_code == 200
    assert response.json()["data"]["features"]["hosted_chat"] is False
    assert client.get("/api/ui/hosted-chat/profiles").status_code == 404


def test_workspace_actions_disabled_when_workspace_feature_off(api, monkeypatch):
    client, *_ = api
    settings = get_settings().model_copy(update={"live_workspace_enabled": False})
    monkeypatch.setattr(human_ui, "get_settings", lambda: settings)
    response = client.get("/api/ui/bootstrap")
    assert response.json()["data"]["features"]["live_workspace"] is False
    assert client.post("/api/ui/hosted-chat/tool", json={
        "name": "workspace_open", "arguments": {},
    }).status_code == 404
    assert client.post("/api/ui/hosted-chat/resource", json={
        "uri": "ui://local-shell-mcp/live-workspace.html",
    }).status_code == 404
