"""Single-user LSM OAuth handoff without a second authentication service."""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import auth


def test_login_ticket_is_one_use_and_db_backed(tmp_path) -> None:
    first = auth.WebAuthStore(tmp_path)
    ticket = first.issue_ticket("alice", "shell:read", int(time.time()) + 900)
    cookie, session = auth.WebAuthStore(tmp_path).redeem(ticket)
    assert session.owner == "alice"
    assert session.scopes == "shell:read"
    assert first.session(cookie) == session
    with pytest.raises(ValueError, match="Invalid or expired"):
        first.redeem(ticket)
    first.revoke(cookie)
    assert first.session(cookie) is None


def test_expired_login_cannot_be_redeemed(tmp_path, monkeypatch) -> None:
    now = int(time.time())
    store = auth.WebAuthStore(tmp_path)
    ticket = store.issue_ticket("alice", "shell:read", now + 10)
    monkeypatch.setattr(auth.time, "time", lambda: now + 12)
    with pytest.raises(ValueError, match="expired"):
        store.redeem(ticket)
    assert store.session("invalid") is None


@pytest.fixture(autouse=True)
def _isolated_real_oauth_settings(tmp_path, monkeypatch):
    # OAuth token helpers read the actual global settings, independently of
    # these tests' mocked auth settings. Never touch the CI host /workspace.
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cookie_login_csrf_and_refresh(tmp_path, monkeypatch) -> None:
    secret = "x" * 48
    settings = SimpleNamespace(auth_mode="oauth", state_dir=tmp_path, oauth_jwt_secret=secret,
                               public_base_url="https://lsm.example.test")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    app = Starlette(routes=auth.auth_routes())

    async def authenticated(scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/api/ui/webui-ticket":
            scope.setdefault("state", {})["principal"] = SimpleNamespace(
                subject="alice", claims={"auth": "oauth", "scope": "shell:read", "exp": int(time.time()) + 900}
            )
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated),
                                base_url="https://lsm.example.test", follow_redirects=False) as client:
        issued = (await client.post("/api/ui/webui-ticket")).json()
        assert len(issued["ticket"]) >= 32
        forged = await client.post("/api/auth/lsm", data={"ticket": issued["ticket"]},
                                   headers={"Origin": "https://attacker.example"})
        assert forged.status_code == 403
        login = await client.post("/api/auth/lsm", data={"ticket": issued["ticket"]},
                                  headers={"Origin": "https://lsm.example.test"})
        assert login.status_code == 303
        assert login.headers["location"] == "/c/new"
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "Secure" in login.headers["set-cookie"]
        replay = await client.post("/api/auth/lsm", data={"ticket": issued["ticket"]})
        assert replay.status_code == 401
        # Signature, resource and issuer are covered by the same existing LSM OAuth code.
        refreshed = await client.post("/api/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["user"]["role"] == "USER"
        assert refreshed.json()["user"]["id"]
        await client.post("/api/auth/logout")
        assert (await client.post("/api/auth/refresh")).status_code == 401


@pytest.mark.asyncio
async def test_controller_without_auth_opens_react_without_second_login(tmp_path, monkeypatch) -> None:
    settings = SimpleNamespace(auth_mode="none", state_dir=tmp_path,
                               oauth_jwt_secret="a" * 48, public_base_url="http://localhost")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    app = Starlette(routes=auth.auth_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://localhost") as client:
        first = await client.post("/api/auth/refresh")
        assert first.status_code == 200, first.text
        assert first.json()["token"]
        assert first.json()["user"]["role"] == "ADMIN"
        second = await client.post("/api/auth/refresh")
        assert second.status_code == 200
        assert first.json()["user"]["id"] == second.json()["user"]["id"]
        assert "set-cookie" not in first.headers
