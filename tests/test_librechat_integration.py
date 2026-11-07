from pathlib import Path

import jwt
import pytest

from local_shell_mcp.librechat_integration import (
    TICKET_AUDIENCE,
    TICKET_ISSUER,
    bridge_url,
    issue_chat_ticket,
)


@pytest.fixture(autouse=True)
def bridge(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_URL", "https://chat.example.test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "z" * 48)


def test_ticket_subject_audience_and_short_lifetime():
    first = issue_chat_ticket("user-1")
    second = issue_chat_ticket("user-2")
    assert first["url"] == "https://chat.example.test"
    assert "user-1" not in first["ticket"]
    one = jwt.decode(first["ticket"], "z" * 48, algorithms=["HS256"],
                     audience=TICKET_AUDIENCE, issuer=TICKET_ISSUER)
    two = jwt.decode(second["ticket"], "z" * 48, algorithms=["HS256"],
                     audience=TICKET_AUDIENCE, issuer=TICKET_ISSUER)
    assert one["sub"] == "user-1" and two["sub"] == "user-2"
    assert one["jti"] != two["jti"]
    assert 0 < one["exp"] - one["iat"] <= 60


@pytest.mark.parametrize("url", [
    "http://chat.example.test", "https://user:pass@chat.example.test",
    "https://chat.example.test/path", "https://chat.example.test?a=1",
    "javascript:alert(1)", "https://chat.example.test/#foo",
])
def test_reject_untrusted_chat_origins(monkeypatch, url):
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_URL", url)
    with pytest.raises(ValueError):
        bridge_url()


def test_localhost_permitted(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_URL", "http://localhost:3080")
    assert bridge_url() == "http://localhost:3080"


def test_not_configured(monkeypatch):
    monkeypatch.delenv("LOCAL_SHELL_MCP_LIBRECHAT_URL")
    assert bridge_url() is None
    with pytest.raises(ValueError):
        issue_chat_ticket("u")


def test_invalid_secret_and_subject(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "short")
    with pytest.raises(ValueError):
        issue_chat_ticket("u")
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "z" * 48)
    with pytest.raises(PermissionError):
        issue_chat_ticket("")


def test_server_registration_and_scope_mapping(tmp_path, monkeypatch):
    from local_shell_mcp.librechat_integration import principal_for_chat_user, register_identity
    from local_shell_mcp.state_store import FileStateStore

    # Isolate this test from inherited controller configuration (CI uses a
    # workspace with no write permission).
    monkeypatch.setattr(
        "local_shell_mcp.state_store.get_state_store",
        lambda: FileStateStore(tmp_path),
    )
    first = issue_chat_ticket("user-a", scopes="shell:read")
    assert register_identity("a" * 24, first["ticket"])["subject"] == "user-a"
    registered = principal_for_chat_user("a" * 24)
    assert registered["subject"] == "user-a"
    assert registered["scopes"] == "shell:read"
    assert registered["auth_mode"] == "oauth"
    assert registered["grant_until"] > 0
    # LSM is single-user: a fresh signed login renews the same internal chat
    # identity rather than creating another LibreChat account.
    second = issue_chat_ticket("user-b", scopes="shell:execute")
    register_identity("a" * 24, second["ticket"])
    assert principal_for_chat_user("a" * 24)["subject"] == "user-b"
    assert principal_for_chat_user("a" * 24)["scopes"] == "shell:execute"
    with pytest.raises(ValueError):
        principal_for_chat_user("../../etc")
    with pytest.raises(PermissionError):
        principal_for_chat_user("b" * 24)

def test_chat_upload_path_user_isolated_and_cannot_traverse(tmp_path):
    from local_shell_mcp.librechat_integration import local_upload_path

    first = local_upload_path("owner-a", "../photo.png", tmp_path)
    second = local_upload_path("owner-b", "../photo.png", tmp_path)
    assert first.parent != second.parent
    assert tmp_path.resolve() in first.resolve().parents
    assert first.name.endswith("-photo.png")
    assert second.name.endswith("-photo.png")
    for unsafe in ("", "..", "\x00", "\n"):
        with pytest.raises(ValueError):
            local_upload_path("owner", unsafe, tmp_path)


def test_librechat_apis_require_auth_and_store_local_upload(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from local_shell_mcp.http_app import build_http_app
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(build_http_app())
        token = client.post("/api/ui/librechat/ticket", json={})
        assert token.status_code == 200, token.text
        jwt_value = token.json()["data"]["ticket"]
        unauth = client.post(
            "/api/ui/librechat/identity", json={"user_id": "a" * 24, "ticket": jwt_value}
        )
        assert unauth.status_code in (401, 403)
        registered = client.post(
            "/api/ui/librechat/identity",
            json={"user_id": "a" * 24, "ticket": jwt_value},
            headers={"Authorization": "Bearer " + "z" * 48},
        )
        assert registered.status_code == 200, registered.text
        response = client.post(
            "/api/ui/librechat/upload?name=../../notes.txt",
            content=b"hello from chat",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text
        result = response.json()["data"]
        assert result["machine"] == "local"
        assert result["size"] == 15
        assert Path(result["path"]).read_bytes() == b"hello from chat"
        assert str(tmp_path) in result["path"]
        assert Path(result["path"]).name.endswith("-notes.txt")
        wrong = client.post(
            "/api/ui/librechat/upload?name=invalid.txt",
            content=b"short",
            headers={"Content-Length": "8"},
        )
        assert wrong.status_code >= 400
        monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
        get_settings.cache_clear()
        blocked = client.post(
            "/api/ui/librechat/upload?name=denied.txt",
            content=b"restricted",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert blocked.status_code >= 400
        assert "denied.txt" not in str(list(tmp_path.rglob("*.txt")))
    finally:
        get_settings.cache_clear()


def test_chat_tool_policy_isolated_per_conversation(tmp_path, monkeypatch):
    from local_shell_mcp.librechat_integration import (
        may_chat_call_lsm,
        register_identity,
        set_chat_tool_policy,
    )
    from local_shell_mcp.state_store import FileStateStore

    # Isolate this test from inherited controller configuration (CI uses a
    # workspace with no write permission).
    monkeypatch.setattr(
        "local_shell_mcp.state_store.get_state_store",
        lambda: FileStateStore(tmp_path),
    )
    register_identity("a" * 24, issue_chat_ticket("owner-a")["ticket"])
    register_identity("b" * 24, issue_chat_ticket("owner-b")["ticket"])
    assert may_chat_call_lsm("a" * 24, "conversation-a")
    set_chat_tool_policy("a" * 24, "conversation-a", False)
    assert not may_chat_call_lsm("a" * 24, "conversation-a")
    assert may_chat_call_lsm("a" * 24, "conversation-b")
    assert may_chat_call_lsm("b" * 24, "conversation-a")
    set_chat_tool_policy("a" * 24, "conversation-a", True)
    assert may_chat_call_lsm("a" * 24, "conversation-a")
    with pytest.raises(ValueError):
        set_chat_tool_policy("a" * 24, "../not-allowed", False)
    with pytest.raises(ValueError):
        set_chat_tool_policy("a" * 24, "conversation-a", "false")
    with pytest.raises(PermissionError):
        set_chat_tool_policy("c" * 24, "conversation-a", True)

def test_mcp_tool_calls_are_blocked_when_conversation_disables_lsm(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from local_shell_mcp.librechat_integration import register_identity, set_chat_tool_policy
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        user_id = "a" * 24
        register_identity(user_id, issue_chat_ticket("test-user")["ticket"])
        set_chat_tool_policy(user_id, "c_123", False)
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        from local_shell_mcp.auth import AuthMiddleware

        async def mcp_handler(_request):
            return JSONResponse({"ok": True})

        client = TestClient(AuthMiddleware(Starlette(routes=[Route("/mcp", mcp_handler, methods=["POST"])])))
        invocation = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "run_shell", "arguments": {"command": "echo should-not-run"}},
        }
        headers = {
            "Authorization": "Bearer " + "z" * 48,
            "X-LSM-Chat-User-Id": user_id,
            "X-LSM-Conversation-Id": "c_123",
        }
        denied = client.post("/mcp", json=invocation, headers=headers)
        assert denied.status_code == 403
        assert "not authorized" in denied.json()["detail"]
        headers["X-LSM-Conversation-Id"] = "other"
        # Unknown chat policies default to enabled; authorization is still subject
        # to the normal LSM MCP tool ACL and session requirements.
        from local_shell_mcp.librechat_integration import may_chat_call_lsm
        assert may_chat_call_lsm(user_id, "other")
        assert client.post("/mcp", json=invocation, headers=headers).status_code == 200
        headers.pop("X-LSM-Conversation-Id")
        assert client.post("/mcp", json=invocation, headers=headers).status_code == 403
    finally:
        get_settings.cache_clear()


def test_noauth_mcp_installs_bridge_auth_when_librechat_is_enabled(tmp_path, monkeypatch):
    from starlette.applications import Starlette

    from local_shell_mcp.auth import AuthMiddleware
    from local_shell_mcp.main import _build_mcp_http_app
    from local_shell_mcp.settings import get_settings

    class FakeMcp:
        def streamable_http_app(self):
            return Starlette()

    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        app = _build_mcp_http_app(FakeMcp())
        assert any(item.cls is AuthMiddleware for item in app.user_middleware)
        monkeypatch.delenv("LOCAL_SHELL_MCP_LIBRECHAT_URL")
        app = _build_mcp_http_app(FakeMcp())
        assert not any(item.cls is AuthMiddleware for item in app.user_middleware)
    finally:
        get_settings.cache_clear()

def test_versioned_chat_policy_rejects_out_of_order_updates(tmp_path, monkeypatch):
    from local_shell_mcp.librechat_integration import (
        issue_chat_ticket, register_identity, set_chat_tool_policy, may_chat_call_lsm,
    )
    from local_shell_mcp.state_store import FileStateStore
    monkeypatch.setattr("local_shell_mcp.state_store.get_state_store",
                        lambda: FileStateStore(tmp_path))
    user = "f" * 24
    register_identity(user, issue_chat_ticket("version-test")["ticket"])
    assert set_chat_tool_policy(user, "conv-race", True, revision=2)
    assert set_chat_tool_policy(user, "conv-race", False, revision=3)
    assert not set_chat_tool_policy(user, "conv-race", True, revision=2)
    assert not set_chat_tool_policy(user, "conv-race", True, revision=3)
    assert not set_chat_tool_policy(user, "conv-race", True)
    assert not may_chat_call_lsm(user, "conv-race")
    assert set_chat_tool_policy(user, "conv-race", True, revision=4)
    assert may_chat_call_lsm(user, "conv-race")
