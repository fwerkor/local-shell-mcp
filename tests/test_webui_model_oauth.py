"""Tests for local and remote OAuth callback delivery without contacting OpenAI."""
import asyncio
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from test_webui_provider_profiles import _ADMIN, setup_profiles  # noqa: F401

from local_shell_mcp.webui import model_oauth

# ruff: noqa: F811

PATH = "/api/lsm/providers/oauth"


@pytest.fixture(autouse=True)
def isolated_flows(monkeypatch):
    monkeypatch.setattr(model_oauth, "_FLOWS", {})


@pytest.fixture
def exchange(monkeypatch):
    calls = []
    saved = []

    async def receive(self, query, redirect, nonce, verifier, previous):
        calls.append((query, redirect, nonce, verifier))
        return {}

    async def save(database, method, name, credentials, *, original=None):
        saved.append((method, name))

    monkeypatch.setattr(model_oauth.ChatGPTAuthorization, "exchange", receive)
    monkeypatch.setattr(model_oauth, "save_account", save)
    return calls, saved


def callback(result):
    params = parse_qs(urlsplit(result["authorization_url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["client_id"] == ["dynamic_agent_client"]
    return params["redirect_uri"][0] + "?" + urlencode({"state": params["state"][0], "code": "mock-code"})


async def complete(client, path):
    for _ in range(100):
        response = await client.get(path)
        assert response.status_code == 200, response.text
        if response.json()["status"] != "pending":
            return response.json()
        await asyncio.sleep(.01)
    pytest.fail("Authorization did not complete")


@pytest.mark.asyncio
async def test_remote_explicit_callback(setup_profiles, exchange):
    _, app = setup_profiles
    calls, saved = exchange
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        result = await client.post(PATH + "/start", json={"method": "chatgpt", "name": "Codex"})
        assert result.status_code == 200, result.text
        assert result.json()["manual"] is True
        path = PATH + "/status?flow=" + result.json()["flow"]
        raw = callback(result.json())
        for invalid in [raw.replace("127.0.0.1", "wrong.invalid"), raw.replace("/auth/callback", "/wrong"),
                        raw + "&state=duplicate", raw.replace("state=", "other="),
                        raw.replace("state=", "state=%E4%B8%AD"), None]:
            assert (await client.post(path, json={"callback_url": invalid})).status_code == 400
        assert calls == []
        assert (await client.post(path, json={"callback_url": raw})).status_code == 200
        assert (await client.post(path, json={"callback_url": raw})).status_code in {400, 409}
        assert await complete(client, path) == {"status": "complete", "name": "Codex"}
        assert len(calls) == 1 and calls[0][1] == raw.split("?")[0]
        assert saved == [("chatgpt", "Codex")]


@pytest.mark.asyncio
async def test_loopback_uses_listener(setup_profiles, exchange):
    _, app = setup_profiles
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=_ADMIN) as client:
        result = (await client.post(PATH + "/start", json={"method": "chatgpt", "name": "Local"})).json()
        assert result["manual"] is False
        path = PATH + "/status?flow=" + result["flow"]
        raw = callback(result)
        assert (await client.post(path, json={"callback_url": raw.replace("state=", "other=")})).status_code == 400
        async with httpx.AsyncClient(trust_env=False) as browser:
            assert (await browser.get(raw)).status_code == 200
        assert (await complete(client, path))["status"] == "complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [False, True])
async def test_loopback_manual_fallback(setup_profiles, exchange, manual):
    _, app = setup_profiles
    calls, saved = exchange
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers=_ADMIN) as client:
        response = await client.post(PATH + "/start", json={"method": "chatgpt", "name": "Container", "manual": manual})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["manual"] is manual
        path = PATH + "/status?flow=" + result["flow"]
        raw = callback(result)
        assert (await client.post(path, json={"callback_url": raw.replace("state=", "other=")})).status_code == 400
        assert (await client.post(path, json={"callback_url": raw})).status_code == 200
        assert (await client.post(path, json={"callback_url": raw})).status_code in {400, 409}
        assert await complete(client, path) == {"status": "complete", "name": "Container"}
        assert len(calls) == 1
        assert saved == [("chatgpt", "Container")]


@pytest.mark.asyncio
async def test_admin_and_cancel(setup_profiles, exchange):
    _, app = setup_profiles
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lsm.invalid", headers=_ADMIN) as client:
        assert (await client.post(PATH + "/start", json={"method": "chatgpt", "name": "Codex"})).status_code == 400
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        body = {"method": "chatgpt", "name": "Codex"}
        assert (await client.post(PATH + "/start", json=body, headers={"x-test-scope": "files:read"})).status_code == 403
        result = (await client.post(PATH + "/start", json=body)).json()
        path = PATH + "/status?flow=" + result["flow"]
        assert (await client.post(PATH + "/start", json=body)).status_code == 400
        assert (await client.delete(path)).json()["status"] == "cancelled"
        assert (await client.post(path, json={"callback_url": callback(result)})).status_code == 404
        assert exchange == ([], [])


@pytest.mark.asyncio
async def test_account_storage_model_refresh_and_rename(setup_profiles, monkeypatch):
    import time
    import uuid

    from local_shell_mcp.webui import model_discovery, routes
    from local_shell_mcp.webui.provider_profiles import profile
    from local_shell_mcp.webui.providers import provider_config

    _, app = setup_profiles
    db = routes._repo().database
    catalog = {"models": ["sample-model"], "model_contexts": {"sample-model": 32768}}
    values = {name: uuid.uuid4().hex for name in ("access_token", "refresh_token", "id_token")}
    credentials = {**values, "client_id": "oaiapp_mock", "subject": "mock-subject",
                   "scope": model_oauth.SCOPE, "expires_at": time.time() - 1}
    refreshed = {**credentials, "access_token": uuid.uuid4().hex, "refresh_token": uuid.uuid4().hex,
                 "expires_at": time.time() + 3600}
    refresh_calls = []

    async def mock_catalog(self, value):
        return catalog

    async def mock_refresh(self, previous):
        refresh_calls.append(previous)
        await asyncio.sleep(.02)
        return refreshed

    monkeypatch.setattr(model_oauth.ChatGPTAuthorization, "catalog", mock_catalog)
    monkeypatch.setattr(model_oauth.ChatGPTAuthorization, "refresh", mock_refresh)
    await model_oauth.save_account(db, "chatgpt", "Codex", credentials)
    stored = profile("Codex")
    assert not any(v in stored["oauth_credentials"] for v in values.values())
    assert model_oauth.unseal(db, stored) == credentials
    results = await asyncio.gather(*(model_oauth.access_token(db, "Codex", stored["oauth_id"]) for _ in range(3)))
    assert results == [refreshed["access_token"]] * 3
    assert len(refresh_calls) == 1
    assert model_oauth.unseal(db, profile("Codex")) == refreshed

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        public = (await client.get("/api/lsm/providers")).json()
        entry = next(item for item in public["providers"] if item.get("name") == "Codex")
        assert entry["provider"] == "openai-responses"
        assert entry["configured"] and entry["auth_method"] == "chatgpt"
        assert "oauth_credentials" not in entry and "api_key" not in entry
        assert (await client.get("/api/models")).json()["Codex"] == ["sample-model"]
        body = {"name": "Renamed", "previous_name": "Codex", "provider": "openai-responses",
                "base_url": model_oauth.RESOURCE, "models": catalog["models"], "auto_discover": True}
        assert (await client.put("/api/lsm/providers", json={**body, "base_url": "https://other.invalid/v1"})).status_code == 400
        response = await client.put("/api/lsm/providers", json=body)
        assert response.status_code == 200, response.text
        assert profile("Renamed")["oauth_id"] == stored["oauth_id"]
        assert provider_config("Renamed").account_id == stored["oauth_id"]
        assert await model_oauth.access_token(db, "Codex", stored["oauth_id"]) == refreshed["access_token"]
        await model_discovery.refresh_model_channels(db)
        assert model_oauth.unseal(db, profile("Renamed")) == refreshed


def token_result(**changes):
    return {"scope": model_oauth.SCOPE, "expires_in": 3600, "token_type": "Bearer",
            "access_token": "mock-access", "refresh_token": "mock-refresh", "id_token": "mock-id", **changes}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,error", [
    (200, token_result(), None),
    (200, [], ValueError),
    (400, {"error": "invalid_grant"}, model_oauth.ReauthorizationRequired),
    (401, {"error": "refresh_token_reused"}, model_oauth.ReauthorizationRequired),
    (400, [], ValueError),
    (503, {"error": "unavailable"}, ValueError),
])
async def test_token_exchange_http_contract(monkeypatch, status, payload, error):
    client_type = httpx.AsyncClient
    def respond(request):
        assert str(request.url) == model_oauth.TOKEN_URL
        assert request.method == "POST"
        assert parse_qs(request.content.decode()) == {"grant_type": ["refresh_token"]}
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(model_oauth.httpx, "AsyncClient", lambda **kwargs:
                        client_type(transport=httpx.MockTransport(respond), **kwargs))
    if error:
        with pytest.raises(error):
            await model_oauth._token({"grant_type": "refresh_token"})
    else:
        assert await model_oauth._token({"grant_type": "refresh_token"}) == payload


@pytest.mark.parametrize("changes,error", [
    ({"scope": "openid"}, model_oauth.ReauthorizationRequired),
    ({"scope": None}, model_oauth.ReauthorizationRequired),
    ({"expires_in": True}, ValueError),
    ({"expires_in": 0}, ValueError),
    ({"expires_in": 86401}, ValueError),
    ({"token_type": "Basic"}, ValueError),
    ({"access_token": ""}, ValueError),
    ({"refresh_token": "has whitespace"}, ValueError),
    ({"refresh_token": None}, ValueError),
])
def test_credentials_reject_invalid_response(changes, error):
    with pytest.raises(error):
        model_oauth._credentials(token_result(**changes), {})


def test_credentials_preserve_scope_and_normalize_refresh_time():
    payload = token_result(earliest_refresh_at="invalid")
    payload.pop("scope")
    payload.pop("id_token")
    previous = {"scope": model_oauth.SCOPE, "id_token": "retained"}
    value = model_oauth._credentials(payload, previous)
    assert value["scope"] == model_oauth.SCOPE
    assert value["id_token"] == "retained"
    assert value["earliest_refresh_at"] == 0


@pytest.mark.parametrize("claims,nonce,valid", [
    ({"sub": "account", "aud": "oaiapp_mock", "nonce": "nonce"}, "nonce", True),
    ({"sub": "", "aud": "oaiapp_mock"}, None, False),
    ({"sub": "account", "aud": "oaiapp_mock", "nonce": "other"}, "nonce", False),
    ({"sub": "account", "aud": ["oaiapp_mock", "other"]}, None, False),
    ({"sub": "account", "aud": ["oaiapp_mock", "other"], "azp": "oaiapp_mock"}, None, True),
])
def test_identity_claim_validation(monkeypatch, claims, nonce, valid):
    from types import SimpleNamespace
    monkeypatch.setattr(model_oauth.jwt, "PyJWKClient", lambda url, timeout:
                        SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key="mock-key")))
    def decode(token, key, **kwargs):
        assert key == "mock-key"
        assert kwargs["algorithms"] == ["RS256"]
        assert kwargs["audience"] == "oaiapp_mock"
        assert kwargs["issuer"] == model_oauth.ISSUER
        assert set(kwargs["options"]["require"]) == {"exp", "sub", "iss", "aud"}
        return claims
    monkeypatch.setattr(model_oauth.jwt, "decode", decode)
    if valid:
        assert model_oauth._verify_id("mock-id", "oaiapp_mock", nonce) == claims
    else:
        with pytest.raises(ValueError, match="verify ChatGPT identity"):
            model_oauth._verify_id("mock-id", "oaiapp_mock", nonce)


@pytest.mark.asyncio
async def test_adapter_exchange_and_refresh_validate_registered_identity(monkeypatch):
    auth = model_oauth.adapter("chatgpt")
    calls = []
    async def token(data):
        calls.append(data)
        return token_result()
    monkeypatch.setattr(model_oauth, "_token", token)
    monkeypatch.setattr(model_oauth, "_verify_id", lambda *args: {"sub": "account"})
    query = {"client_id": "oaiapp_mock", "code": "mock-code"}
    for invalid in ({"error": "access_denied"}, {"client_id": "other", "code": "x"},
                    {"client_id": "oaiapp_mock"}):
        with pytest.raises(ValueError):
            await auth.exchange(invalid, "redirect", "nonce", "verifier", {})
    assert not calls
    credential = await auth.exchange(query, "redirect", "nonce", "verifier", {})
    assert credential["subject"] == "account"
    assert calls[-1] == {"grant_type": "authorization_code", "client_id": "oaiapp_mock",
                         "code": "mock-code", "code_verifier": "verifier", "redirect_uri": "redirect",
                         "resource": model_oauth.RESOURCE}
    assert (await auth.refresh(credential))["subject"] == "account"
    assert calls[-1]["refresh_token"] == credential["refresh_token"]
    with pytest.raises(ValueError, match="registration"):
        await auth.exchange({**query, "client_id": "oaiapp_other"}, "redirect", "nonce", "verifier", credential)
    monkeypatch.setattr(model_oauth, "_verify_id", lambda *args: {"sub": "other-account"})
    with pytest.raises(ValueError, match="original ChatGPT account"):
        await auth.exchange(query, "redirect", "nonce", "verifier", credential)
    with pytest.raises(model_oauth.ReauthorizationRequired, match="identity changed"):
        await auth.refresh(credential)


@pytest.mark.asyncio
async def test_catalog_uses_account_capability_and_retries_unauthorized(monkeypatch):
    from local_shell_mcp.webui import model_discovery
    tokens = []
    async def fetch(protocol, base, token, **kwargs):
        assert (protocol, base) == ("openai-responses", model_oauth.RESOURCE)
        assert kwargs == {"allow_empty": True, "account": True}
        tokens.append(token)
        if token == "old":
            response = httpx.Response(401, request=httpx.Request("GET", base))
            response.raise_for_status()
        return {"models": ["mock"], "model_contexts": {}}
    async def access(db, name, identity, *, rejected=None):
        assert (name, identity) == ("Codex", "id")
        return "new" if rejected == "old" else "old"
    monkeypatch.setattr(model_discovery, "_fetch_models", fetch)
    monkeypatch.setattr(model_oauth, "access_token", access)
    value = {"name": "Codex", "oauth_id": "id", "auth_method": "chatgpt",
             "provider": "openai-responses", "base_url": model_oauth.RESOURCE}
    assert await model_oauth.catalog_for(None, value) == {"models": ["mock"], "model_contexts": {}}
    assert tokens == ["old", "new"]
    with pytest.raises(ValueError, match="original API endpoint"):
        await model_oauth.catalog_for(None, {**value, "base_url": "https://other.invalid"})
    with pytest.raises(ValueError, match="Unsupported"):
        model_oauth.adapter("other")


@pytest.mark.asyncio
async def test_account_reauthorization_and_expiry_storage(setup_profiles, monkeypatch):
    import time

    from local_shell_mcp.webui import routes
    from local_shell_mcp.webui.provider_profiles import profile

    db = routes._repo().database
    auth = model_oauth.ChatGPTAuthorization
    async def catalog(self, token):
        return {"models": ["mock"], "model_contexts": {}}
    monkeypatch.setattr(auth, "catalog", catalog)
    credential = model_oauth._credentials(token_result(), {"client_id": "oaiapp_mock", "subject": "account"})
    await model_oauth.save_account(db, "chatgpt", "Codex", credential)
    saved = profile("Codex")
    assert model_oauth.host_id(db) == model_oauth.host_id(db)
    with pytest.raises(model_oauth.ReauthorizationRequired):
        model_oauth.unseal(db, {"oauth_credentials": "invalid"})
    with pytest.raises(ValueError, match="already exists"):
        await model_oauth.save_account(db, "chatgpt", "Codex", credential)
    with pytest.raises(ValueError, match="registration is already connected"):
        await model_oauth.save_account(db, "chatgpt", "Other", credential)
    with pytest.raises(ValueError, match="original account"):
        await model_oauth.save_account(db, "chatgpt", "Codex", {**credential, "subject": "other"}, original=saved)
    updated = {**credential, "expires_at": time.time() + 30, "earliest_refresh_at": time.time() + 180}
    await model_oauth.save_account(db, "chatgpt", "Codex", updated, original=saved)
    current = profile("Codex")
    with pytest.raises(model_oauth.ReauthorizationRequired):
        await model_oauth.access_token(db, "Codex", saved["oauth_id"])
    assert await model_oauth.access_token(db, "Codex", current["oauth_id"]) == credential["access_token"]
    with pytest.raises(ValueError, match="cannot be refreshed yet"):
        await model_oauth.access_token(db, "Codex", current["oauth_id"], rejected=credential["access_token"])
    await model_oauth.save_account(db, "chatgpt", "Codex", {**credential, "expires_at": 0}, original=current)
    expired = profile("Codex")
    async def refresh(self, value):
        raise model_oauth.ReauthorizationRequired("Sign in again")
    monkeypatch.setattr(auth, "refresh", refresh)
    with pytest.raises(model_oauth.ReauthorizationRequired, match="Sign in again"):
        await model_oauth.access_token(db, "Codex", expired["oauth_id"])
    assert profile("Codex")["oauth_error"] == "Sign in again"
    with pytest.raises(model_oauth.ReauthorizationRequired):
        await model_oauth.access_token(db, "Codex", expired["oauth_id"])
