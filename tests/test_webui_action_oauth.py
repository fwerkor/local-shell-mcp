"""Action OAuth provider emulation, binding, CSRF, durable tokens, and refresh.

The real browser routes are exercised over ASGI HTTP; the remote HTTPS IdP's
network exchange is mocked while the database, cookies and token lifecycle are real.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import action_oauth, action_routes, agent_routes, routes
from local_shell_mcp.webui.actions import ActionRepository
from local_shell_mcp.webui.agents import AgentRepository

_REAL_BASE_URL = action_oauth._base_url


@pytest.fixture
def oauth_env(tmp_path, monkeypatch):
    from local_shell_mcp.webui import auth

    db = SQLiteDatabase(tmp_path)
    agent = AgentRepository(db).create("alice", {"provider": "openAI", "model": "gpt-test", "name": "OAuth"})
    repo = ActionRepository(db)
    spec = {"openapi": "3.0.0", "servers": [{"url": "https://api.example.org"}],
            "paths": {"/data": {"get": {"operationId": "readData", "responses": {"200": {}}}}}}
    body = {"metadata": {"domain": "https://api.example.org", "raw_spec": json.dumps(spec),
            "auth": {"type": "oauth", "authorization_url": "https://identity.example.org/authorize",
                     "client_url": "https://identity.example.org/token", "scope": "read write",
                     "token_exchange_method": "default_post"},
            "oauth_client_id": "public-client-id", "oauth_client_secret": "private-client-secret"},
            "functions": [{"type": "function", "function": {"name": "readData"}}]}
    _, action = repo.save("alice", agent["id"], body)
    action_id = action["action_id"]
    conf = SimpleNamespace(auth_mode="oauth", public_base_url="https://chat.example.org")
    monkeypatch.setattr(action_oauth, "_base_url", lambda: "https://chat.example.org")
    monkeypatch.setattr(routes, "get_settings", lambda: conf)
    monkeypatch.setattr(auth, "get_settings", lambda: conf)
    monkeypatch.setattr(action_routes, "_repository", lambda: repo)

    app = Starlette(routes=agent_routes.agent_routes())

    async def wrapper(scope, receive, send):
        if scope["type"] == "http":
            subject = dict(scope.get("headers", [])).get(b"x-owner")
            if subject:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=subject.decode())
        await app(scope, receive, send)

    return repo, agent, action_id, body, wrapper


def test_oauth_flow_persists_only_hash_and_sealed_secrets(oauth_env):
    repo, _, action_id, _, _ = oauth_env
    url, state = action_oauth.begin_flow(repo, "alice", action_id, "run1", "call1")
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.hostname == "identity.example.org"
    assert params["client_id"] == ["public-client-id"]
    assert params["redirect_uri"] == [f"https://chat.example.org/api/actions/{action_id}/oauth/callback"]
    assert params["state"] == [state] and len(state) >= 32
    assert params["scope"] == ["read write"]
    content = repo.database.path.read_bytes()
    for secret in (state, "private-client-secret", "oauth_access_token"):
        assert secret.encode() not in content
    with repo.database.connect() as db:
        flow = db.execute("SELECT * FROM action_oauth_flows WHERE action_id=?", (action_id,)).fetchone()
    assert flow["state_hash"] == hashlib.sha256(state.encode()).hexdigest()
    assert flow["run_id"] == "run1" and flow["call_id"] == "call1"
    assert not action_oauth._check_cookie(repo, "bad", "alice", action_id)
    assert not action_oauth._check_cookie(repo, None, "alice", action_id)
    token = action_oauth.bind_cookie(repo, "alice", action_id)
    assert action_oauth._check_cookie(repo, token, "alice", action_id)
    assert not action_oauth._check_cookie(repo, token, "bob", action_id)
    assert not action_oauth._check_cookie(repo, token, "alice", "other-action")
    with pytest.raises(PermissionError, match="CSRF"):
        action_oauth.claim_callback(repo, action_id, state, None)
    result = action_oauth.claim_callback(repo, action_id, state, token)
    assert result[0] == "alice" and result[-1] == 1
    assert result[4:6] == ("run1", "call1")
    with pytest.raises(PermissionError, match="state"):
        action_oauth.claim_callback(repo, action_id, state, token)


@pytest.mark.asyncio
async def test_oauth_browser_http_bind_callback_and_token_isolation(oauth_env, monkeypatch):
    repo, agent, action_id, _, app = oauth_env
    observed = []

    async def fake_token(endpoint, body, credentials, method):
        observed.append((endpoint, dict(body), dict(credentials), method))
        return {"access_token": "PRIVATE-ACCESS", "refresh_token": "PRIVATE-REFRESH", "expires_in": 900}

    monkeypatch.setattr(action_oauth, "_exchange", fake_token)
    url, state = action_oauth.begin_flow(repo, "alice", action_id, "run2", "tool2")
    assert url.startswith("https://identity.example.org/authorize?")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        path = f"/api/actions/{action_id}/oauth"
        assert (await client.post(path + "/bind")).status_code == 401
        assert (await client.post(path + "/bind", headers={"x-owner": "bob"})).status_code == 404
        assert (await client.post(path + "/bind", headers={"x-owner": "alice",
                                  "origin": "https://attacker.invalid"})).status_code == 403
        invalid = await client.get(path + "/callback", params={"state": state, "code": "idp-auth-code"})
        assert invalid.status_code == 302 and "invalid_state" in invalid.headers["location"]
        bound = await client.post(path + "/bind", headers={"x-owner": "alice",
                                        "origin": "https://chat.example.org"})
        assert bound.status_code == 200 and bound.json() == {"success": True}
        assert "httponly" in bound.headers["set-cookie"].lower()
        assert "secure" in bound.headers["set-cookie"].lower()
        assert "samesite=lax" in bound.headers["set-cookie"].lower()
        mismatch = await client.get(path + "/callback", headers={"x-owner": "bob"},
                                    params={"state": state, "code": "idp-auth-code"})
        assert "invalid_state" in mismatch.headers["location"]
        assert observed == []
        # Mismatched browser identity used the one-shot state. A fresh flow succeeds.
        _, state = action_oauth.begin_flow(repo, "alice", action_id, "run2", "tool2")
        result = await client.get(path + "/callback", params={"state": state, "code": "idp-auth-code"})
        assert result.status_code == 302 and result.headers["location"].startswith("/oauth/success")
        assert observed[0][0] == "https://identity.example.org/token"
        assert observed[0][1] == {"grant_type": "authorization_code", "code": "idp-auth-code",
                                  "redirect_uri": f"https://chat.example.org{path}/callback"}
        assert observed[0][2]["oauth_client_secret"] == "private-client-secret"
        assert await action_oauth.access_token(repo, "alice", action_id) == "PRIVATE-ACCESS"
        replay = await client.get(path + "/callback", params={"state": state, "code": "idp-auth-code"})
        assert replay.status_code == 302 and "invalid_state" in replay.headers["location"]
        assert len(observed) == 1
    assert "PRIVATE-ACCESS" not in repo.database.path.read_text(errors="ignore")
    assert "PRIVATE-REFRESH" not in repo.database.path.read_text(errors="ignore")
    assert "PRIVATE-ACCESS" not in str(repo.list("alice"))
    assert repo.list("bob") == []
    assert action_oauth._token(repo, "bob", action_id, "access") is None
    assert AgentRepository(repo.database).get("alice", agent["id"])["actions"]


@pytest.mark.asyncio
async def test_oauth_refresh_and_action_retarget_revokes_tokens(oauth_env, monkeypatch):
    repo, agent, action_id, body, _ = oauth_env
    action_oauth._store_tokens(repo, "alice", action_id, {
        "access_token": "old", "refresh_token": "ROTATING-REFRESH", "expires_in": 0,
    })
    recorded = []

    async def refresh(endpoint, data, credentials, method):
        recorded.append((endpoint, data, credentials, method))
        return {"access_token": "renewed", "refresh_token": "new-refresh", "expires_in": 400}

    monkeypatch.setattr(action_oauth, "_exchange", refresh)
    concurrent = await asyncio.gather(*(action_oauth.access_token(repo, "alice", action_id) for _ in range(6)))
    assert concurrent == ["renewed"] * 6
    assert recorded[0][1] == {"grant_type": "refresh_token", "refresh_token": "ROTATING-REFRESH"}
    assert recorded[0][3] == "default_post"
    assert action_oauth._token(repo, "alice", action_id, "refresh") == "new-refresh"
    assert await action_oauth.access_token(repo, "alice", action_id) == "renewed"
    assert len(recorded) == 1
    # On changes to target, authorization, or OpenAPI server the old grant must be invalid.
    changed = json.loads(json.dumps(body))
    changed["action_id"] = action_id
    changed["metadata"]["auth"]["scope"] = "different-scope"
    repo.save("alice", agent["id"], changed)
    assert action_oauth._token(repo, "alice", action_id, "access") is None
    assert action_oauth._token(repo, "alice", action_id, "refresh") is None


def test_oauth_state_stale_after_edit_delete_and_expiry(oauth_env):
    repo, agent, action_id, body, _ = oauth_env
    _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    cookie = action_oauth.bind_cookie(repo, "alice", action_id)
    with repo.database.connect() as db:
        db.execute("UPDATE action_oauth_flows SET expires_at=? WHERE state_hash=?",
                   (int(time.time()) - 100, hashlib.sha256(state.encode()).hexdigest()))
    with pytest.raises(PermissionError):
        action_oauth.claim_callback(repo, action_id, state, cookie)
    _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    updated = json.loads(json.dumps(body))
    updated["action_id"] = action_id
    repo.save("alice", agent["id"], updated)
    with pytest.raises(PermissionError):
        action_oauth.claim_callback(repo, action_id, state, cookie)
    assert repo.delete("alice", agent["id"], action_id)
    with pytest.raises(KeyError):
        action_oauth.bind_cookie(repo, "alice", action_id)


@pytest.mark.asyncio
async def test_oauth_wait_cancel_and_refresh_failure(oauth_env, monkeypatch):
    repo, _, action_id, _, _ = oauth_env
    _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    pending = asyncio.create_task(action_oauth.await_login(repo, "alice", action_id, state))
    await asyncio.sleep(.03)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    action_oauth._store_tokens(repo, "alice", action_id, {
        "access_token": "old", "refresh_token": "NOPE", "expires_in": 0,
    })

    async def failed(*args, **kwargs):
        raise PermissionError("provider denied refresh")

    monkeypatch.setattr(action_oauth, "_exchange", failed)
    assert await action_oauth.access_token(repo, "alice", action_id) is None
    assert action_oauth._token(repo, "alice", action_id, "access") is None
    assert not action_oauth._check_cookie(repo, "invalid-cookie", "alice", action_id)


@pytest.mark.asyncio
async def test_oauth_exchange_validates_data_and_pinned_target(monkeypatch):
    import httpx as real_httpx

    from local_shell_mcp.webui import action_runtime

    monkeypatch.setattr(action_runtime, "_resolve_address", lambda host, port: "93.184.215.14")
    captured = []
    client_class = real_httpx.AsyncClient

    def client_factory(*args, **kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        transport = real_httpx.MockTransport(lambda request: (
            captured.append(request) or real_httpx.Response(200, json={
                "access_token": "access", "refresh_token": "refresh", "expires_in": 120,
            })
        ))
        return client_class(*args, transport=transport, **kwargs)

    monkeypatch.setattr(real_httpx, "AsyncClient", client_factory)
    credentials = {"oauth_client_id": "client", "oauth_client_secret": "secret"}
    token = await action_oauth._exchange("https://identity.example.org/token",
                                         {"grant_type": "authorization_code", "code": "code"},
                                         credentials, "default_post")
    assert token["access_token"] == "access"
    assert captured[0].headers["host"] == "identity.example.org"
    assert captured[0].url.host == "93.184.215.14"
    assert b"client_secret=secret" in captured[0].content
    assert captured[0].extensions["sni_hostname"] == "identity.example.org"
    captured.clear()
    await action_oauth._exchange("https://identity.example.org/token", {"grant_type": "refresh_token"},
                                 credentials, "basic_auth_header")
    assert captured[0].headers["authorization"] == "Basic " + __import__("base64").b64encode(b"client:secret").decode()
    assert b"client_secret" not in captured[0].content
    with pytest.raises(ValueError):
        await action_oauth._exchange("http://identity.example.org/token", {}, credentials, "default_post")


@pytest.mark.asyncio
async def test_oauth_callback_bypasses_global_bearer_only_with_state_cookie(oauth_env, monkeypatch):
    """End-to-end through LSM's real outer AuthMiddleware and OAuth bind route."""
    from fastapi import HTTPException

    from local_shell_mcp import auth as server_auth

    repo, _, action_id, _, app = oauth_env
    conf = SimpleNamespace(auth_mode="oauth", ui_path="ui", public_base_url="https://chat.example.org",
                           require_auth_for_mcp_discovery=True)
    monkeypatch.setattr(server_auth, "get_settings", lambda: conf)

    def verify(request):
        if request.headers.get("Authorization") == "Bearer alice":
            return server_auth.Principal(None, "alice", {"scope": "shell:read"})
        raise HTTPException(401, detail="Bearer token required")

    monkeypatch.setattr(server_auth, "verify_request", verify)
    from local_shell_mcp.webui.agent_routes import agent_routes

    async def mock_exchange(*args):
        return {"access_token": "AUTHENTICATED-ACCESS", "expires_in": 500}

    monkeypatch.setattr(action_oauth, "_exchange", mock_exchange)
    wrapped = server_auth.AuthMiddleware(Starlette(routes=agent_routes()))
    _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    base = f"/api/actions/{action_id}/oauth"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        assert (await client.post(base + "/bind")).status_code == 401
        assert (await client.post(base + "/callback")).status_code == 401
        bound = await client.post(base + "/bind", headers={"Authorization": "Bearer alice"})
        assert bound.status_code == 200
        # OAuth providers redirect browsers without bearer; a narrow callback
        # exemption must reach the CSRF validator without weakening /bind.
        callback = await client.get(base + "/callback", params={"state": state, "code": "auth-code"})
        assert callback.status_code == 302 and "/oauth/success" in callback.headers["location"]
        assert await action_oauth.access_token(repo, "alice", action_id) == "AUTHENTICATED-ACCESS"
        assert (await client.get(base + "/callback", params={"state": state, "code": "auth-code"})).status_code == 302
        assert (await client.get(base + "/callback/extra")).status_code == 401


@pytest.mark.parametrize("url", [
    None, "http://example.org", "https://example.org/path", "https://example.org/?q=x",
    "https://u:pass@example.org", "https://example.org/#fragment", "ftp://example.org",
])
def test_action_oauth_rejects_unsafe_callback_origin(oauth_env, monkeypatch, url):
    from local_shell_mcp import settings
    conf = SimpleNamespace(public_base_url=url)
    monkeypatch.setattr(settings, "get_settings", lambda: conf)
    monkeypatch.setattr(action_oauth, "_base_url", _REAL_BASE_URL)
    # The real implementation must fail before producing a provider redirect URL.
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        action_oauth._base_url()


def test_action_oauth_state_validation_and_scope(oauth_env, monkeypatch):
    repo, agent, action_id, body, _ = oauth_env
    with pytest.raises(PermissionError):
        action_oauth.claim_callback(repo, action_id, "!", None)
    with pytest.raises(KeyError):
        action_oauth.begin_flow(repo, "bob", action_id, "run", "call")
    monkeypatch.setenv("LSM_ACTION_ALLOWED_DOMAINS", "api.example.org")
    with pytest.raises(PermissionError, match="domain"):
        action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    monkeypatch.delenv("LSM_ACTION_ALLOWED_DOMAINS", raising=False)
    _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    cookie = action_oauth.bind_cookie(repo, "alice", action_id)
    assert action_oauth._check_cookie(repo, cookie, "alice", action_id)
    # Different valid state cannot consume a legitimate OAuth attempt.
    with pytest.raises(PermissionError, match="state"):
        action_oauth.claim_callback(repo, action_id, "X" * 48, cookie)
    _, metadata, creds, _, run_id, call_id, version = action_oauth.claim_callback(repo, action_id, state, cookie)
    assert (run_id, call_id) == ("run", "call")
    assert metadata["auth"]["type"] == "oauth"
    with pytest.raises(PermissionError, match="changed"):
        action_oauth._store_tokens(repo, "alice", action_id, {"access_token": "secret"}, expected_version=version + 1)
    with pytest.raises(PermissionError, match="changed"):
        action_oauth._store_tokens(repo, "bob", action_id, {"access_token": "secret"})
    assert creds["oauth_client_id"] == "public-client-id"


@pytest.mark.asyncio
async def test_action_oauth_exchange_errors_and_limits(monkeypatch):
    from local_shell_mcp.webui import action_runtime

    monkeypatch.setattr(action_runtime, "_resolve_address", lambda host, port: "93.184.215.14")
    creds = {"oauth_client_id": "client", "oauth_client_secret": "secret"}
    import httpx as real_httpx
    underlying = real_httpx.AsyncClient

    def set_mock(handler):
        monkeypatch.setattr(real_httpx, "AsyncClient", lambda **kw: underlying(
            transport=real_httpx.MockTransport(handler), **kw))

    def response(data, status=200):
        return lambda req: real_httpx.Response(status, json=data)

    url = "https://identity.example.org:443/token"
    with pytest.raises(ValueError, match="method"):
        await action_oauth._exchange(url, {}, creds, "invalid")
    with pytest.raises(ValueError, match="URL"):
        await action_oauth._exchange("https://u:p@id.example.org/token", {}, creds, "default_post")
    set_mock(response({"access_token": "bad"}, status=403))
    with pytest.raises(PermissionError, match="rejected"):
        await action_oauth._exchange(url, {}, creds, "default_post")
    set_mock(response({"error": "invalid_grant"}))
    with pytest.raises(ValueError, match="access token"):
        await action_oauth._exchange(url, {}, creds, "default_post")
    for item in (
        {"access_token": "A" * 16385},
        {"access_token": "ok", "refresh_token": []},
        {"access_token": "ok", "expires_in": "not-an-integer"},
        {"access_token": "ok", "expires_in": -3},
        {"access_token": "ok", "refresh_token_expires_in": 10 * 365 * 86400 + 1},
    ):
        set_mock(response(item))
        with pytest.raises(ValueError):
            await action_oauth._exchange(url, {}, creds, "default_post")
    set_mock(lambda req: real_httpx.Response(200, content=b"{" + b"a" * (32 * 1024 + 1) + b"}"))
    with pytest.raises(ValueError, match="too large"):
        await action_oauth._exchange(url, {}, creds, "default_post")

    def network_error(req):
        raise real_httpx.ConnectError("cannot reach IdP", request=req)

    set_mock(network_error)
    with pytest.raises(ConnectionError, match="unreachable"):
        await action_oauth._exchange(url, {}, creds, "default_post")


@pytest.mark.asyncio
async def test_action_oauth_login_expiry_invalid_code_and_cookie(oauth_env, monkeypatch):
    repo, _, action_id, _, _ = oauth_env
    with pytest.raises(ValueError, match="code"):
        await action_oauth.exchange_code(repo, "alice", action_id, {}, {}, "https://example.org", "", expected_version=1)
    _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    with repo.database.connect() as db:
        db.execute("DELETE FROM action_oauth_flows WHERE state_hash=?", (hashlib.sha256(state.encode()).hexdigest(),))
    with pytest.raises(PermissionError, match="expired"):
        await action_oauth.await_login(repo, "alice", action_id, state)
    monkeypatch.setattr(action_oauth, "_FLOW_TTL", 0)
    _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
    with pytest.raises(TimeoutError, match="timed out"):
        await action_oauth.await_login(repo, "alice", action_id, state)
    # Bad JSON binding cannot bypass the CSRF flow, even if it decrypts.
    invalid = repo._cipher().encrypt(b"{invalid json").decode()
    assert not action_oauth._check_cookie(repo, invalid, "alice", action_id)


@pytest.mark.asyncio
async def test_oauth_callback_error_pages_hide_provider_errors(oauth_env, monkeypatch):
    repo, _, action_id, _, app = oauth_env
    base = f"/api/actions/{action_id}/oauth"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        for params in ({}, {"state": "valid"}, {"code": "something"}):
            res = await client.get(base + "/callback", params=params)
            assert res.status_code == 302 and res.headers["location"] == "/oauth/error?error=invalid_state"
        _, state = action_oauth.begin_flow(repo, "alice", action_id, "run", "call")
        assert (await client.post(base + "/bind", headers={"x-owner": "alice"})).status_code == 200

        async def unavailable(*args):
            raise RuntimeError("SECRET_PROVIDER_FAILURE")

        monkeypatch.setattr(action_oauth, "_exchange", unavailable)
        res = await client.get(base + "/callback", params={"state": state, "code": "oauth-code"})
        assert res.status_code == 302 and res.headers["location"] == "/oauth/error?error=callback_failed"
        assert "SECRET_PROVIDER_FAILURE" not in str(res.headers)
