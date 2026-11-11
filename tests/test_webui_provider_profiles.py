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
async def test_named_channels_same_provider_are_independent_and_survive_restart(setup_profiles):
    settings, app = setup_profiles
    from local_shell_mcp.webui.provider_profiles import profile
    from local_shell_mcp.webui.providers import selected_provider

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        # The original single-channel API and storage key are unchanged.
        old = {"provider": "openai", "base_url": "https://primary.invalid/v1", "models": ["same-model"], "api_key": "old-secret"}
        assert (await client.put("/api/lsm/providers", json=old)).status_code == 200
        for name, base, secret in (("Primary Research", "https://research.invalid/v1", "first-secret"),
                                   ("Secondary Research", "https://second.invalid/v1", "second-secret")):
            body = {"name": name, "provider": "openai", "base_url": base,
                    "models": ["same-model", "distinct-model"], "api_key": secret}
            response = await client.put("/api/lsm/providers", json=body)
            assert response.status_code == 200, response.text
            assert secret not in response.text and "api_key" not in response.text
            assert provider_config(name, "same-model").url == base + "/chat/completions"
            assert provider_config(name).token == secret
            assert selected_provider({"endpoint": name}) == name
            assert selected_provider({"endpoint": "agents"}, {"provider": name}) == name
        assert provider_config("openAI").token == "old-secret"
        names = (await client.get("/api/models")).json()
        assert names["openAI"] == ["same-model"]
        assert names["Primary Research"] == ["same-model", "distinct-model"]
        assert names["Secondary Research"] == ["same-model", "distinct-model"]
        endpoint = (await client.get("/api/endpoints")).json()
        assert endpoint["agents"]["allowedProviders"] == ["openAI", "Primary Research", "Secondary Research"]
        assert endpoint["Primary Research"]["type"] == "openAI"
        assert "ask_user_question" in endpoint["agents"]["capabilities"]
        # Key preservation works independently for every channel.
        assert (await client.put("/api/lsm/providers", json={"name": "Primary Research", "provider": "openai",
                    "base_url": "https://new.invalid/v1", "models": ["updated"]})).status_code == 200
        assert provider_config("Primary Research").token == "first-secret"
        assert provider_config("Secondary Research").token == "second-secret"
        assert provider_config("openai").token == "old-secret"
        public = (await client.get("/api/lsm/providers")).text
        for secret in ("first-secret", "second-secret", "old-secret"):
            assert secret not in public
        assert profile("Primary Research")["name"] == "Primary Research"
        with routes._repo().database.connect() as db:
            rows = db.execute("SELECT key FROM settings WHERE owner='__lsm_controller__' ORDER BY key").fetchall()
        assert {row[0] for row in rows} >= {"model.provider.openai", "model.channel.Primary Research", "model.channel.Secondary Research"}
        restarted = subprocess.run([sys.executable, "-c", "from local_shell_mcp.webui.providers import provider_config; import json; print(json.dumps([(p,provider_config(p).url,provider_config(p).token) for p in ('openai','Primary Research','Secondary Research')]))"],
                                   env={**os.environ, "LOCAL_SHELL_MCP_STATE_DIR": str(settings.state_dir),
                                        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(settings.state_dir / "workspace")},
                                   capture_output=True, text=True, check=True)
        assert json.loads(restarted.stdout) == [
            ["openai", "https://primary.invalid/v1/chat/completions", "old-secret"],
            ["Primary Research", "https://new.invalid/v1/chat/completions", "first-secret"],
            ["Secondary Research", "https://second.invalid/v1/chat/completions", "second-secret"],
        ]


@pytest.mark.asyncio
async def test_named_channel_protocols_validation_and_delete_protection(setup_profiles):
    _, app = setup_profiles
    from local_shell_mcp.webui.agents import AgentRepository

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        for name, kind, base, suffix in (("Anthropic Gateway", "anthropic", "https://anthropic-gateway.invalid/v1", "/messages"),
                                         ("Gemini Gateway", "google", "https://gemini-gateway.invalid/v1beta", "/models/gemini-test:streamGenerateContent?alt=sse")):
            body = {"name": name, "provider": kind, "base_url": base,
                    "models": ["gemini-test"], "api_key": "private-named-token"}
            response = await client.put("/api/lsm/providers", json=body)
            assert response.status_code == 200, response.text
            config = provider_config(name)
            assert config.url == base + suffix
            assert config.provider == kind and config.token == "private-named-token"
            assert config.model == "gemini-test"
            assert (await client.get("/api/models")).json()[name] == ["gemini-test"]
            assert "private-named-token" not in (await client.get("/api/endpoints")).text
            assert "private-named-token" not in (await client.get("/api/models")).text
            assert (await client.put("/api/lsm/providers", json={**body, "provider": "openai"})).status_code == 409
        for bad in ("openAI", "agents", "custom", "ollama", "bad/name", " name", "name ", "", "bad\nname"):
            result = await client.put("/api/lsm/providers", json={"name": bad, "provider": "openai",
                "base_url": "https://example.invalid/v1", "models": ["m"]})
            assert result.status_code == 400, (bad, result.text)
        assert (await client.put("/api/lsm/providers", json={"name": "anthropic gateway", "provider": "anthropic",
            "base_url": "https://example.invalid/v1", "models": ["m"]})).status_code == 409
        assert (await client.delete("/api/lsm/providers?name=Anthropic%20Gateway")).status_code == 200
        assert (await client.get("/api/models")).json().get("Anthropic Gateway") is None
        with pytest.raises(ValueError, match="Unknown model channel"):
            provider_config("Anthropic Gateway")
        repo = AgentRepository(routes._repo().database)
        agent = repo.create("owner", {"name": "Persistent Agent", "description": "", "provider": "Gemini Gateway", "model": "gemini-test"})
        assert (await client.delete("/api/lsm/providers?name=Gemini%20Gateway")).status_code == 409
        assert repo.get("owner", agent["id"])["provider"] == "Gemini Gateway"
        # Version rollback must never restore a dangling provider after a
        # newer Agent revision has switched to a different named channel.
        repo.update("owner", agent["id"], {"provider": "openai", "model": "safe-model"})
        assert repo.get("owner", agent["id"])["provider"] == "openai"
        assert (await client.delete("/api/lsm/providers?name=Gemini%20Gateway")).status_code == 409
        assert provider_config("Gemini Gateway").token == "private-named-token"
        assert (await client.delete("/api/lsm/providers?name=google")).status_code == 400
        assert (await client.delete("/api/lsm/providers?name=not%20existing")).status_code == 200
