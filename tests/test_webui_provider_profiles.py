"""Provider setup remains server-side, authenticated and durable across restarts."""

import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.auth import Principal
from local_shell_mcp.webui import config_routes, routes
from local_shell_mcp.webui.providers import provider_config


@pytest.fixture
def setup_profiles(tmp_path, monkeypatch):
    from local_shell_mcp import settings as settings_module

    settings = SimpleNamespace(auth_mode="oauth", state_dir=tmp_path, public_base_url=None)
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LOCAL_SHELL_MCP_MODEL_API_KEY",
                 "LOCAL_SHELL_MCP_MODEL_BASE_URL", "LOCAL_SHELL_MCP_MODEL", "ANTHROPIC_API_KEY",
                 "GOOGLE_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    app = Starlette(routes=config_routes.config_routes())

    async def authenticated(scope, receive, send):
        headers = dict(scope.get("headers", []))
        if b"x-test-scope" in headers:
            scope.setdefault("state", {})["principal"] = Principal(None, "owner", {
                "scope": headers[b"x-test-scope"].decode(), "auth": "oauth"})
        await app(scope, receive, send)

    return settings, authenticated


_ADMIN = {"x-test-scope": "admin:config"}


@pytest.mark.asyncio
async def test_profiles_authorization_persistence_catalog_and_runtime(setup_profiles):
    settings, app = setup_profiles
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://lsm.invalid") as client:
        assert (await client.get("/api/lsm/providers")).status_code == 401
        assert (await client.put("/api/lsm/providers", json={})).status_code == 401
        assert (await client.get("/api/lsm/providers", headers={"x-test-scope": "files:read"})).status_code == 403
        assert (await client.put("/api/lsm/providers", headers={"x-test-scope": "files:read"}, json={})).status_code == 403
        initial = await client.get("/api/lsm/providers", headers=_ADMIN)
        assert initial.headers["cache-control"] == "no-store"
        assert all(not value["configured"] for value in initial.json()["providers"])
        for kind, base, expected in (("openai", "https://models.invalid/v1", "/chat/completions"),
                                     ("anthropic", "https://claude.invalid/v1", "/messages"),
                                     ("google", "https://gemini.invalid/v1beta", "/models/model-a:streamGenerateContent?alt=sse")):
            response = await client.put("/api/lsm/providers", headers=_ADMIN,
                                        json={"provider": kind, "base_url": base, "models": ["model-a", "model-b", "model-a"],
                                              "api_key": "private-secret"})
            assert response.status_code == 200, response.text
            assert "private-secret" not in response.text and "api_key" not in response.text
            assert provider_config(kind).url == base + expected
            assert provider_config(kind).token == "private-secret"
            # Recreate the repository object: no process-local credential cache.
            assert routes._repo().setting("__lsm_controller__", "model.provider." + kind)["models"] == ["model-a", "model-b"]
            for key in (None, "", "   "):
                body = {"provider": kind, "base_url": base, "models": ["replacement"]}
                if key is not None:
                    body["api_key"] = key
                assert (await client.put("/api/lsm/providers", headers=_ADMIN, json=body)).status_code == 200
                assert provider_config(kind).token == "private-secret"
        assert (await client.get("/api/models", headers=_ADMIN)).json() == {
            "openAI": ["replacement"], "anthropic": ["replacement"], "google": ["replacement"], "agents": []}
        endpoints = (await client.get("/api/endpoints", headers=_ADMIN)).json()
        assert {"openAI", "anthropic", "google", "agents"} == set(endpoints)
        assert "private-secret" not in (await client.get("/api/lsm/providers", headers=_ADMIN)).text
        restarted = subprocess.run([sys.executable, "-c", "from local_shell_mcp.webui.providers import provider_config; import json; p=provider_config('openai'); print(json.dumps([p.model,p.url,p.token]))"],
                                   env={**os.environ, "LOCAL_SHELL_MCP_STATE_DIR": str(settings.state_dir),
                                        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(settings.state_dir / "workspace")},
                                   capture_output=True, text=True, check=True)
        assert json.loads(restarted.stdout) == ["replacement", "https://models.invalid/v1/chat/completions", "private-secret"]
        # Auth-disabled Controller remains configurable without inventing scopes.
        settings.auth_mode = "none"
        assert (await client.get("/api/lsm/providers")).status_code == 200
        assert (await client.get("/api/lsm/providers", headers={"Origin": "https://lsm.invalid"})).status_code == 200
        assert (await client.get("/api/lsm/providers", headers={"Origin": "https://other.invalid"})).status_code == 401
        assert (await client.put("/api/lsm/providers", headers={"Origin": "https://other.invalid"}, json={})).status_code == 401


@pytest.mark.asyncio
async def test_keyless_loopback_profile_and_validation_are_atomic(setup_profiles):
    _, app = setup_profiles
    valid = {"provider": "openai", "base_url": "http://127.0.0.1:9000/v1", "models": ["local"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        assert (await client.put("/api/lsm/providers", json=valid)).status_code == 200
        assert provider_config("ollama").token == ""
        assert (await client.get("/api/lsm/providers")).json()["providers"][0]["configured"]
        for change in ({"provider": "unknown"}, {"provider": []}, {"base_url": None}, {"base_url": ""},
                       {"base_url": "x" * 2049}, {"base_url": "http://remote.invalid/v1"},
                       {"base_url": "https://user:secret@example.invalid/v1"}, {"base_url": "https://x.invalid/v1?token=secret"},
                       {"base_url": "https://x.invalid/v1#token"}, {"base_url": "https://x.invalid:bad/v1"},
                       {"base_url": "https://x.invalid:0/v1"}, {"base_url": "https://x .invalid/v1"}, {"models": []}, {"models": "local"},
                       {"models": ["x"] * 129}, {"models": [1]}, {"models": [""]}, {"models": ["x\n"]},
                       {"models": ["x" * 201]}, {"api_key": 12}, {"api_key": "a\nb"}, {"api_key": "a" * 16385},
                       {"provider": "google", "models": ["../bad"]}):
            failed = await client.put("/api/lsm/providers", json={**valid, **change})
            assert failed.status_code == 400, (change, failed.text)
            assert provider_config("openai").model == "local"
        assert (await client.put("/api/lsm/providers", content="not json")).status_code == 400
        assert (await client.put("/api/lsm/providers", json=[])).status_code == 400


@pytest.mark.asyncio
async def test_profile_write_rolls_back_and_can_retry(setup_profiles):
    _, app = setup_profiles
    body = {"provider": "openai", "base_url": "http://localhost:9000/v1", "models": ["before"], "api_key": "before-key"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        assert (await client.put("/api/lsm/providers", json=body)).status_code == 200
        with routes._repo().database.connect() as db:
            db.execute("CREATE TRIGGER reject_model_update BEFORE UPDATE ON settings BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            await client.put("/api/lsm/providers", json={**body, "api_key": "after-key", "models": ["after"]})
        assert provider_config("openai").token == "before-key"
        assert provider_config("openai").model == "before"
        with routes._repo().database.connect() as db:
            db.execute("DROP TRIGGER reject_model_update")
        assert (await client.put("/api/lsm/providers", json={**body, "models": ["after"]})).status_code == 200
        assert provider_config("openai").model == "after"


def test_environment_provider_inventory_redacts_url_credentials(setup_profiles, monkeypatch):
    from local_shell_mcp.webui.provider_profiles import public_profiles

    monkeypatch.setenv("OPENAI_BASE_URL", "https://user:secret@models.invalid/v1?key=hidden#fragment")
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    value = public_profiles()["providers"][0]
    assert value["base_url"] == "https://models.invalid/v1"
    assert "secret" not in str(value) and "hidden" not in str(value) and "private-key" not in str(value)


@pytest.mark.asyncio
async def test_profile_usage_option_survives_config_updates_and_rejects_invalid_values(setup_profiles):
    _, app = setup_profiles
    body = {'provider': 'openai', 'base_url': 'http://127.0.0.1:9000/v1',
            'models': ['compatible'], 'include_usage': True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='https://lsm.invalid', headers=_ADMIN) as client:
        result = await client.put('/api/lsm/providers', json=body)
        assert result.status_code == 200
        assert provider_config('openai').include_usage is True
        assert result.json()['providers'][0]['include_usage'] is True
        # Updating the key/model must preserve the explicitly enabled usage
        # option; callers may explicitly disable it again.
        without_option = {key: value for key, value in body.items() if key != 'include_usage'}
        assert (await client.put('/api/lsm/providers', json=without_option)).status_code == 200
        assert provider_config('openai').include_usage is True
        assert (await client.put('/api/lsm/providers', json={**body, 'include_usage': False})).status_code == 200
        assert provider_config('openai').include_usage is False
        for invalid in (1, 'yes', [], {}, 0):
            failed = await client.put('/api/lsm/providers', json={**body, 'include_usage': invalid})
            assert failed.status_code == 400
            assert provider_config('openai').include_usage is False
