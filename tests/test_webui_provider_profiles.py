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
async def test_legacy_usage_option_is_ignored_and_not_persisted(setup_profiles):
    _, app = setup_profiles
    from local_shell_mcp.webui.provider_profiles import profile

    body = {'provider': 'openai', 'base_url': 'http://127.0.0.1:9000/v1',
            'models': ['compatible']}
    # A channel saved by an older release may explicitly disable usage.
    routes._repo().save_setting('__lsm_controller__', 'model.provider.openai', {
        **body, 'api_key': '', 'include_usage': False})
    assert provider_config('openai').model == 'compatible'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='https://lsm.invalid', headers=_ADMIN) as client:
        listed = (await client.get('/api/lsm/providers')).json()['providers'][0]
        assert 'include_usage' not in listed
        # Older clients can still submit the field; it has no effect.
        result = await client.put('/api/lsm/providers', json={**body, 'include_usage': False})
        assert result.status_code == 200
        assert 'include_usage' not in result.json()['providers'][0]
        assert 'include_usage' not in profile('openai')


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
        # Saved legacy endpoint aliases must keep resolving after channel migration.
        assert provider_config("custom").token == "old-secret"
        assert provider_config("custom").url == "https://primary.invalid/v1/chat/completions"
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
async def test_unicode_channel_name_create_rename_and_delete(setup_profiles):
    _, app = setup_profiles
    from local_shell_mcp.webui.provider_profiles import profile

    channel = {"name": "DeepSeek开放平台", "provider": "openai",
               "base_url": "https://api.deepseek.com/v1",
               "models": ["deepseek-chat"], "api_key": "unicode-secret"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://lsm.invalid", headers=_ADMIN) as client:
        created = await client.put("/api/lsm/providers", json=channel)
        assert created.status_code == 200, created.text
        assert profile(channel["name"])["api_key"] == "unicode-secret"
        assert provider_config(channel["name"]).model == "deepseek-chat"
        assert channel["name"] in (await client.get("/api/models")).json()

        # Duplicate names remain case-insensitive, including non-ASCII letters.
        duplicate = await client.put("/api/lsm/providers", json={**channel, "name": "deepseek开放平台"})
        assert duplicate.status_code == 409, duplicate.text
        for bad in ("中文/模型", "中文\\模型", "中文\n模型", "中文 ", "1号模型"):
            result = await client.put("/api/lsm/providers", json={**channel, "name": bad})
            assert result.status_code == 400, (bad, result.text)

        renamed_name = "深度求索 Research"
        renamed = await client.put("/api/lsm/providers", json={
            **channel, "name": renamed_name, "previous_name": channel["name"],
            "models": ["deepseek-reasoner"], "api_key": "",
        })
        assert renamed.status_code == 200, renamed.text
        assert profile(renamed_name)["api_key"] == "unicode-secret"
        assert provider_config(renamed_name).model == "deepseek-reasoner"
        assert renamed_name in (await client.get("/api/models")).json()
        assert channel["name"] not in (await client.get("/api/models")).json()

        deleted = await client.delete("/api/lsm/providers", params={"name": renamed_name})
        assert deleted.status_code == 200, deleted.text
        assert renamed_name not in (await client.get("/api/models")).json()
        with pytest.raises(ValueError, match="Unknown model channel"):
            profile(renamed_name)


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
        for bad in ("openAI", "agents", "custom", "ollama", "Research Assistants", "mini-assistants", "Assistants Overlay Assistants", "bad/name", " name", "name ", "", "bad\nname"):
            result = await client.put("/api/lsm/providers", json={"name": bad, "provider": "openai",
                "base_url": "https://example.invalid/v1", "models": ["m"]})
            assert result.status_code == 400, (bad, result.text)
        # Historical names predating validation must remain removable.
        routes._repo().save_setting("__lsm_controller__", "model.channel.Legacy Assistants", {
            "name": "Legacy Assistants", "provider": "openai",
            "base_url": "https://legacy.invalid/v1", "models": ["m"], "api_key": "secret"})
        assert (await client.delete("/api/lsm/providers?name=Legacy%20Assistants")).status_code == 200
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


@pytest.mark.asyncio
async def test_channel_management_create_rename_edit_delete_and_legacy_reset(setup_profiles):
    _, app = setup_profiles
    from local_shell_mcp.webui.provider_profiles import profile

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://lsm.invalid", headers=_ADMIN) as client:
        initial = (await client.get("/api/lsm/providers")).json()["providers"]
        assert [entry["source"] for entry in initial] == ["default", "default", "default"]
        first = {"name": "Research A", "provider": "openai", "base_url": "https://research.invalid/v1",
                 "models": ["model-a"], "api_key": "secret-a"}
        assert (await client.put("/api/lsm/providers", json=first)).status_code == 200
        entries = (await client.get("/api/lsm/providers")).json()["providers"]
        assert [entry["name"] for entry in entries if entry["source"] == "named"] == ["Research A"]
        assert "secret-a" not in str(entries)
        # Editing name, models and URL should keep the secret and clean the old key atomically.
        renamed = {**first, "name": "Research B", "previous_name": "Research A",
                   "base_url": "https://updated.invalid/v1", "models": ["model-b"]}
        renamed.pop("api_key")
        result = await client.put("/api/lsm/providers", json=renamed)
        assert result.status_code == 200, result.text
        assert profile("Research B")["api_key"] == "secret-a"
        assert provider_config("Research B").url == "https://updated.invalid/v1/chat/completions"
        with pytest.raises(ValueError, match="Unknown model channel"):
            profile("Research A")
        assert "Research B" in (await client.get("/api/models")).json()
        assert "Research A" not in (await client.get("/api/models")).json()
        # Changing provider transport after creation is still forbidden.
        assert (await client.put("/api/lsm/providers",
            json={**renamed, "previous_name": "Research B", "provider": "anthropic"})).status_code == 409
        assert (await client.put("/api/lsm/providers",
            json={**renamed, "previous_name": "unknown"})).status_code == 404

        # A separate channel is allowed for the same provider, but names are case-insensitive.
        assert (await client.put("/api/lsm/providers", json=first)).status_code == 200
        assert (await client.put("/api/lsm/providers",
            json={**first, "name": "research b"})).status_code == 409
        assert (await client.put("/api/lsm/providers",
            json={**renamed, "name": "Research A", "previous_name": "Research B"})).status_code == 409
        assert (await client.delete("/api/lsm/providers?name=Research%20A")).status_code == 200

        legacy = {"provider": "anthropic", "base_url": "https://api.anthropic.com/v1",
                  "models": ["model-legacy"], "api_key": "legacy-secret"}
        assert (await client.put("/api/lsm/providers", json=legacy)).status_code == 200
        entries = (await client.get("/api/lsm/providers")).json()["providers"]
        assert next(entry["source"] for entry in entries if entry["provider"] == "anthropic") == "saved"
        assert (await client.delete("/api/lsm/providers?legacy_provider=anthropic")).status_code == 200
        assert next(entry["source"] for entry in (await client.get("/api/lsm/providers")).json()["providers"]
                    if entry["provider"] == "anthropic") == "default"
        assert (await client.delete("/api/lsm/providers?legacy_provider=unknown")).status_code == 400
        assert (await client.delete("/api/lsm/providers?legacy_provider=anthropic&name=Research%20B")).status_code == 400
        assert (await client.delete("/api/lsm/providers")).status_code == 400


@pytest.mark.asyncio
async def test_rename_and_legacy_reset_protect_saved_agent_references(setup_profiles):
    _, app = setup_profiles
    from local_shell_mcp.webui.agents import AgentRepository

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://lsm.invalid", headers=_ADMIN) as client:
        named = {"name": "Used Research", "provider": "openai",
                 "base_url": "https://research.invalid/v1", "models": ["m"], "api_key": "k"}
        assert (await client.put("/api/lsm/providers", json=named)).status_code == 200
        agents = AgentRepository(routes._repo().database)
        agents.create("owner", {"name": "Used Agent", "description": "",
                                "provider": "Used Research", "model": "m"})
        renamed = {**named, "name": "New Research", "previous_name": "Used Research"}
        assert (await client.put("/api/lsm/providers", json=renamed)).status_code == 409
        assert (await client.delete("/api/lsm/providers?name=Used%20Research")).status_code == 409
        assert "Used Research" in (await client.get("/api/models")).json()
        assert "New Research" not in (await client.get("/api/models")).json()
        # A non-identity edit remains possible while a channel is referenced.
        assert (await client.put("/api/lsm/providers",
            json={**named, "models": ["m", "new-m"]})).status_code == 200
        old = {"provider": "openai", "base_url": "https://legacy.invalid/v1",
               "models": ["legacy-m"], "api_key": "k"}
        assert (await client.put("/api/lsm/providers", json=old)).status_code == 200
        agents.create("owner", {"name": "Legacy Agent", "description": "",
                                "provider": "openAI", "model": "legacy-m"})
        assert (await client.delete("/api/lsm/providers?legacy_provider=openai")).status_code == 409
        assert provider_config("openai").url == "https://legacy.invalid/v1/chat/completions"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy,reference", [
    ("openai", "OpenAI"),
    ("openai", "OPENAI-COMPATIBLE"),
    ("openai", "OlLaMa"),
    ("openai", "CUSTOM"),
    ("openai", "AzureOpenAI"),
    ("anthropic", "Anthropic"),
    ("google", "GEMINI"),
    ("google", "GOOGLE"),
])
async def test_legacy_reset_protects_case_insensitive_runtime_aliases(setup_profiles, legacy, reference):
    _, app = setup_profiles
    from local_shell_mcp.webui.agents import AgentRepository

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://lsm.invalid", headers=_ADMIN) as client:
        body = {"provider": legacy, "base_url": "https://model-gateway.invalid/v1",
                "models": ["m"], "api_key": "saved-secret"}
        assert (await client.put("/api/lsm/providers", json=body)).status_code == 200
        agent = AgentRepository(routes._repo().database).create("owner", {
            "name": "Case-sensitive legacy reference", "description": "",
            "provider": reference, "model": "m",
        })
        assert agent["provider"] == reference
        result = await client.delete(f"/api/lsm/providers?legacy_provider={legacy}")
        assert result.status_code == 409, result.text
        assert provider_config(reference).token == "saved-secret"


@pytest.mark.asyncio
async def test_model_context_limits_in_token_config_and_input_validation(setup_profiles):
    _, app = setup_profiles
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='https://lsm.invalid') as client:
        data = {'name': 'Window Test', 'provider': 'openai',
                'base_url': 'https://gateway.invalid/v1', 'api_key': 'secret',
                'models': ['m1', 'm2'], 'model_contexts': {'m1': 128000, 'm2': 8192}}
        response = await client.put('/api/lsm/providers', headers=_ADMIN, json=data)
        assert response.status_code == 200, response.text
        assert (await client.get('/api/endpoints/token-config', headers=_ADMIN)).json() == {
            'Window Test': {'m1': {'context': 128000}, 'm2': {'context': 8192}}}
        listed = (await client.get('/api/lsm/providers', headers=_ADMIN)).json()['providers']
        assert next(item for item in listed if item.get('name') == 'Window Test')['model_contexts'] == data['model_contexts']
        for limits in ({'unknown': 100}, {'m1': 0}, {'m1': -1}, {'m1': True},
                       {'m1': 2_000_001}, {'m1': '8192'}, ['m1', 8192]):
            invalid = await client.put('/api/lsm/providers', headers=_ADMIN,
                                       json={**data, 'model_contexts': limits})
            assert invalid.status_code == 400, (limits, invalid.text)
        assert (await client.get('/api/endpoints/token-config', headers=_ADMIN)).json() == {
            'Window Test': {'m1': {'context': 128000}, 'm2': {'context': 8192}}}


@pytest.mark.asyncio
async def test_explicit_force_delete_named_channel_retains_history_without_rerouting(setup_profiles):
    _, app = setup_profiles
    from local_shell_mcp.webui.agents import AgentRepository
    from local_shell_mcp.webui.provider_profiles import profile

    repo = routes._repo()
    channel = {"name": "Used Research", "provider": "openai",
               "base_url": "https://research.invalid/v1", "models": ["m"],
               "api_key": "must-not-be-returned"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://lsm.invalid", headers=_ADMIN) as client:
        assert (await client.put("/api/lsm/providers", json=channel)).status_code == 200
        agent = AgentRepository(repo.database).create("owner", {
            "name": "Historical Agent", "description": "", "provider": "Used Research", "model": "m"})
        conversation = repo.create_conversation("owner", {
            "conversationId": "historical-conversation", "title": "Keep my history",
            "endpoint": "Used Research", "model": "m"})
        assert conversation["endpoint"] == "Used Research"

        refusal = await client.delete("/api/lsm/providers?name=Used%20Research")
        assert refusal.status_code == 409
        assert refusal.json()["can_force"] is True
        assert "saved conversations" in refusal.json()["detail"]
        assert "must-not-be-returned" not in refusal.text
        assert (await client.delete("/api/lsm/providers?name=Used%20Research&force=1")).status_code == 400
        assert profile("Used Research")["api_key"] == "must-not-be-returned"

        response = await client.delete("/api/lsm/providers?name=Used%20Research&force=true")
        assert response.status_code == 200, response.text
        assert "Used Research" not in (await client.get("/api/models")).json()
        assert "must-not-be-returned" not in response.text
        with pytest.raises(ValueError, match="Unknown model channel"):
            profile("Used Research")
        assert repo.conversation("owner", "historical-conversation")["endpoint"] == "Used Research"
        assert AgentRepository(repo.database).get("owner", agent["id"])["provider"] == "Used Research"
        assert AgentRepository(repo.database).versions("owner", agent["id"])[0]["provider"] == "Used Research"
        # Deleting a used named channel never changes the built-in provider.
        assert profile("openai")["base_url"] == "https://api.openai.com/v1"
        assert (await client.delete("/api/lsm/providers?name=Used%20Research&force=true")).status_code == 200


@pytest.mark.asyncio
async def test_force_delete_referenced_legacy_channel_does_not_fall_back_to_defaults(setup_profiles):
    _, app = setup_profiles
    repo = routes._repo()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://lsm.invalid", headers=_ADMIN) as client:
        assert (await client.put("/api/lsm/providers", json={
            "provider": "openai", "base_url": "https://legacy.invalid/v1",
            "models": ["legacy"], "api_key": "old-key"})).status_code == 200
        repo.create_conversation("owner", {
            "conversationId": "legacy-chat", "title": "Legacy chat", "model": "legacy", "endpoint": "custom"})
        refusal = await client.delete("/api/lsm/providers?legacy_provider=openai&force=true")
        assert refusal.status_code == 409
        assert refusal.json()["can_force"] is False
        assert provider_config("custom").url == "https://legacy.invalid/v1/chat/completions"


@pytest.mark.asyncio
async def test_model_sampling_defaults_are_independent_and_validated(setup_profiles):
    _, app = setup_profiles
    body = {"provider": "openai", "base_url": "http://127.0.0.1:9000/v1",
            "name": "Research", "models": ["a", "b"],
            "model_sampling": {"a": {"temperature": 0, "top_p": 0.7, "max_tokens": 128}}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://lsm.invalid", headers=_ADMIN) as client:
        saved = await client.put("/api/lsm/providers", json=body)
        assert saved.status_code == 200, saved.text
        assert next(p for p in saved.json()["providers"] if p.get("name") == "Research")["model_sampling"] == body["model_sampling"]
        assert provider_config("Research", "a").sampling == body["model_sampling"]["a"]
        assert provider_config("Research", "b").sampling == {}
        for invalid in ({"c": {}}, {"a": {"temperature": 3}}, {"a": {"max_tokens": True}}):
            assert (await client.put("/api/lsm/providers", json={**body, "model_sampling": invalid})).status_code == 400
        without = {k: v for k, v in body.items() if k != "model_sampling"}
        assert (await client.put("/api/lsm/providers", json=without)).status_code == 200
        assert provider_config("Research", "a").sampling == body["model_sampling"]["a"]
        assert (await client.put("/api/lsm/providers", json={**body, "model_sampling": {}})).status_code == 200
        assert provider_config("Research", "a").sampling == {}


@pytest.mark.asyncio
async def test_model_discovery_uses_saved_key_only_at_original_endpoint(setup_profiles, monkeypatch):
    _, app = setup_profiles
    original_client = httpx.AsyncClient
    outbound = []
    def respond(request):
        outbound.append(request)
        return httpx.Response(200, json={'data': [
            {'id': 'flash', 'context_window': 1048576, 'max_output_tokens': 393216},
            {'id': 'pro', 'context_length': 128000}, {'id': 'unknown', 'context_window': True},
            {'id': 'output-only', 'max_output_tokens': 8192}, {'id': 'flash'}, None,
            {'id': 'invalid\n'}, {'id': 'too-big', 'max_model_len': 2000001},
            {'id': 'text-embedding-3-small'}, {'id': 'whisper-1'},
            {'id': 'gpt-image-1'}, {'id': 'vendor/reranker-v2'},
            {'id': 'arbitrary', 'architecture': {'output_modalities': ['image']}},
            {'id': 'other', 'supported_endpoints': ['/v1/embeddings']},
            {'id': 'opaque-pool', 'task': 'embed'},
            {'id': 'opaque-score', 'supported_tasks': ['score', 'rerank']},
            {'id': 'opaque-multi', 'supported_tasks': ['generate', 'embed']},
            {'id': 'opaque-tts', 'model_type': 'text_to_speech'},
            {'id': 'davinci-002'}, {'id': 'gpt-3.5-turbo-instruct'},
            {'id': 'sora-2'}, {'id': 'text-search-ada-doc-001'},

            {'id': 'explicit-chat', 'supported_endpoints': ['/v1/chat/completions']},
        ]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(respond), **kw))
    path = '/api/lsm/providers/discover'
    body = {'name': 'Discovery', 'provider': 'openai', 'base_url': 'https://models.invalid/v1',
            'models': ['old'], 'api_key': 'secret', 'model_contexts': {'old': 8192}}
    async with original_client(transport=httpx.ASGITransport(app=app), base_url='https://lsm.invalid') as client:
        assert (await client.post(path, json=body)).status_code == 401
        assert (await client.post(path, headers={'x-test-scope': 'files:read'}, json=body)).status_code == 403
        assert (await client.put('/api/lsm/providers', headers=_ADMIN, json=body)).status_code == 200
        probe = {'provider': 'openai', 'base_url': body['base_url'], 'existing_channel': 'Discovery'}
        result = await client.post(path, headers=_ADMIN, json=probe)
        assert result.status_code == 200, result.text
        assert result.json() == {'models': ['flash', 'pro', 'unknown', 'output-only', 'too-big', 'opaque-multi', 'explicit-chat'],
                                 'model_contexts': {'flash': 1048576, 'pro': 128000}}
        assert result.headers['cache-control'] == 'no-store'
        assert 'secret' not in result.text
        assert outbound[0].headers['authorization'] == 'Bearer secret'
        assert str(outbound[0].url) == 'https://models.invalid/v1/models'
        for changed in ({'base_url': 'https://different.invalid/v1'}, {'provider': 'anthropic'},
                        {'existing_channel': 'nonexistent'}, {'base_url': 'http://external.invalid'}):
            assert (await client.post(path, headers=_ADMIN, json={**probe, **changed})).status_code == 400
        assert len(outbound) == 1
        assert (await client.post(path, headers=_ADMIN, json={**probe, 'base_url': 'https://different.invalid/v1', 'api_key': 'new'})).status_code == 200
        assert outbound[-1].headers['authorization'] == 'Bearer new'
        # Discovery alone is not an update: the catalog changes only after Save.
        from local_shell_mcp.webui.provider_profiles import profile
        assert profile('Discovery')['models'] == ['old']
        assert profile('Discovery')['model_contexts'] == {'old': 8192}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['anthropic', 'google'])
async def test_native_discovery_pagination(kind, monkeypatch):
    from local_shell_mcp.webui.model_discovery import _fetch_models
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        if kind == 'google':
            assert request.headers['x-goog-api-key'] == 'key'
            if len(requests) == 1:
                return httpx.Response(200, json={'models': [
                    {'name': 'models/gemini', 'supportedGenerationMethods': ['generateContent'], 'inputTokenLimit': 1000000},
                    {'name': 'models/embedding', 'supportedGenerationMethods': ['embedContent']},
                    {'name': 'models/invalid/name', 'supportedGenerationMethods': ['generateContent']},
                    {'name': 'models/invalid', 'supportedGenerationMethods': 5}], 'nextPageToken': 'next'})
            assert request.url.params['pageToken'] == 'next'
            return httpx.Response(200, json={'models': [{'name': 'models/next', 'supportedGenerationMethods': ['generateContent']}]})
        assert request.headers['x-api-key'] == 'key'
        assert request.headers['anthropic-version'] == '2023-06-01'
        if len(requests) == 1:
            return httpx.Response(200, json={'data': [{'id': 'claude', 'max_input_tokens': 200000}], 'has_more': True, 'last_id': 'claude'})
        assert request.url.params['after_id'] == 'claude'
        return httpx.Response(200, json={'data': [{'id': 'next'}], 'has_more': False})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await _fetch_models(kind, 'https://native.invalid/v1', 'key')
    model, limit = ('gemini', 1000000) if kind == 'google' else ('claude', 200000)
    assert result == {'models': [model, 'next'], 'model_contexts': {model: limit}}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload,expected', [
    (302, {}, 502), (401, {'error': 'private detail'}, 502), (200, [], 400),
    (200, {'data': []}, 400), (200, {'data': None}, 400),
    (200, {'data': [{'id': f'm{i}'} for i in range(129)]}, 400),
    (200, None, 502),
])
async def test_discovery_failure_returns_safe_error_and_no_save(setup_profiles, monkeypatch, status, payload, expected):
    _, app = setup_profiles
    original = httpx.AsyncClient
    def respond(request):
        if payload is None:
            return httpx.Response(status, text='private detail')
        return httpx.Response(status, json=payload, headers={'location': 'https://redirect.invalid'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    async with original(transport=httpx.ASGITransport(app=app), base_url='https://lsm.invalid') as client:
        response = await client.post('/api/lsm/providers/discover', headers=_ADMIN, json={
            'provider': 'openai', 'base_url': 'https://models.invalid', 'api_key': 'private-key'})
        assert response.status_code == expected
        assert 'private detail' not in response.text and 'private-key' not in response.text
        assert not any(p['configured'] for p in (await client.get('/api/lsm/providers', headers=_ADMIN)).json()['providers'])


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,mode,match', [
    ('google', 'invalid_cursor', 'Invalid model list cursor'),
    ('anthropic', 'invalid_cursor', 'Invalid model list cursor'),
    ('google', 'repeat', 'repeated a model list page'),
    ('google', 'many_pages', 'too many pages'),
    ('openai', 'oversized', 'model list is too large'),
])
async def test_discovery_bounds_and_pagination_errors(kind, mode, match, monkeypatch):
    from local_shell_mcp.webui.model_discovery import _fetch_models
    original = httpx.AsyncClient
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        assert 'authorization' not in request.headers
        if mode == 'oversized':
            return httpx.Response(200, content=b' ' * (2 * 1024 * 1024 + 1))
        if kind == 'anthropic':
            return httpx.Response(200, json={'data': [], 'has_more': True})
        cursor = 5 if mode == 'invalid_cursor' else ('repeat' if mode == 'repeat' else str(count))
        return httpx.Response(200, json={'models': [], 'nextPageToken': cursor})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match=match):
        await _fetch_models(kind, 'http://127.0.0.1:8000/v1', '')


@pytest.mark.asyncio
async def test_keyless_channel_can_discover_at_changed_endpoint(setup_profiles, monkeypatch):
    _, app = setup_profiles
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'data': [{'id': 'local-chat'}]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    async with original(transport=httpx.ASGITransport(app=app), base_url='https://lsm.invalid', headers=_ADMIN) as client:
        assert (await client.put('/api/lsm/providers', json={
            'name': 'Local', 'provider': 'openai', 'base_url': 'http://127.0.0.1:8000/v1',
            'models': ['old']})).status_code == 200
        response = await client.post('/api/lsm/providers/discover', json={
            'provider': 'openai', 'base_url': 'http://127.0.0.1:9000/v1',
            'existing_channel': 'Local'})
        assert response.status_code == 200, response.text
        assert response.json()['models'] == ['local-chat']
        assert str(requests[0].url) == 'http://127.0.0.1:9000/v1/models'
        assert 'authorization' not in requests[0].headers
