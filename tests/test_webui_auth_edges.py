"""Native WebUI login has no second user database or unsafe fallback."""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import auth


def test_ticket_expiration_tampering_and_session_limits(tmp_path, monkeypatch):
    now = int(time.time())
    store = auth.WebAuthStore(tmp_path)
    with pytest.raises(ValueError):
        store.issue_ticket("", "shell:read", now + 900)
    with pytest.raises(ValueError):
        store.issue_ticket("alice", "shell:read", now)
    for token in ("short", "a" * 400):
        with pytest.raises(ValueError):
            store.redeem(token)
    ticket = store.issue_ticket("alice", "shell:read", now + 120)
    raw, result = store.redeem(ticket)
    assert result.owner == "alice"
    assert store.session("invalid") is None
    assert store.session("a" * 400) is None
    assert store.session(raw) == result
    monkeypatch.setattr(auth.time, "time", lambda: now + 121)
    assert store.session(raw) is None
    monkeypatch.setattr(auth.time, "time", lambda: now)
    assert store.session(raw) is not None
    store.revoke(raw)
    assert store.session(raw) is None


@pytest.mark.asyncio
async def test_auth_routes_reject_unauthorized_and_expire_oauth_grants(tmp_path, monkeypatch):
    now = int(time.time())
    settings = SimpleNamespace(auth_mode="oauth", state_dir=tmp_path,
                               public_base_url="https://lsm.example.test", oauth_jwt_secret="s" * 48)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    app = Starlette(routes=auth.auth_routes())

    async def authenticated(scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/api/ui/webui-ticket":
            if not any(k == b"x-auth" for k, _ in scope.get("headers", [])):
                await app(scope, receive, send)
                return
            scope.setdefault("state", {})["principal"] = SimpleNamespace(
                subject="alice", claims={"scope": "shell:read", "auth": "oauth", "exp": now + 100},
            )
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated),
                                base_url="https://lsm.example.test", follow_redirects=False) as client:
        assert (await client.post("/api/ui/webui-ticket")).status_code == 401
        assert (await client.get("/api/user")).status_code == 401
        assert (await client.post("/api/auth/refresh")).status_code == 401
        assert (await client.post("/api/auth/lsm", data={})).status_code == 400
        assert (await client.post("/api/auth/lsm", data={"ticket": "a" * 40})).status_code == 401
        issued = (await client.post("/api/ui/webui-ticket", headers={"x-auth": "yes"})).json()
        assert issued["url"] == "https://lsm.example.test"
        forbidden = await client.post("/api/auth/lsm", data={"ticket": issued["ticket"]},
                                      headers={"Origin": "https://attacker.example"})
        assert forbidden.status_code == 403
        good = await client.post("/api/auth/lsm", data={"ticket": issued["ticket"]},
                                 headers={"Origin": "https://lsm.example.test"})
        assert good.status_code == 303
        access = await client.post("/api/auth/refresh")
        assert access.status_code == 200, access.text
        token = access.json()["token"]
        claims = jwt.decode(token, options={"verify_signature": False})
        assert claims["exp"] <= now + 100
        assert access.json()["user"]["role"] == "USER"
        assert (await client.post("/api/auth/logout", headers={"Origin": "https://other.example"})).status_code == 403
        assert (await client.post("/api/auth/logout")).status_code == 200
        assert (await client.post("/api/auth/refresh")).status_code == 401
