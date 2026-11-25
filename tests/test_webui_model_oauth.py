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
        assert (await client.post(path, json={"callback_url": raw})).status_code == 409
        async with httpx.AsyncClient(trust_env=False) as browser:
            assert (await browser.get(raw)).status_code == 200
        assert (await complete(client, path))["status"] == "complete"


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
