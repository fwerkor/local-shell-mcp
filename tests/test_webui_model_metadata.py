"""Public context fallback never changes the upstream model list or leaks credentials."""

import asyncio

import httpx
import pytest
from test_webui_provider_profiles import _ADMIN
from test_webui_provider_profiles import setup_profiles as setup_profiles

from local_shell_mcp.webui import model_discovery, model_metadata, routes
from local_shell_mcp.webui.provider_profiles import profile

OPENAI = "https://api.openai.com/v1"
PUBLIC = "https://models.dev/api.json"


def entry(context):
    return {"limit": {"context": context}}


CATALOG = {
    "openai": {"models": {"same": entry(400000), "manual": entry(200000),
                          "not-listed": entry(128000), "bad": entry(True),
                          "too-big": entry(2000001), "string": entry("64000"),
                          "wrong-id": {"id": "different", **entry(64000)},
                          "output-only": {"limit": {"output": 4096}}}},
    "openrouter": {"models": {"same": entry(64000)}},
    "anthropic": {"models": {"same": entry(1000000)}},
}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(model_metadata, "_cache", model_metadata._CatalogCache())


@pytest.mark.parametrize("kind,url,expected", [
    ("openai", OPENAI, "openai"),
    ("openai-responses", OPENAI + "/", "openai"),
    ("anthropic", "https://api.anthropic.com/v1", "anthropic"),
    ("google", "https://generativelanguage.googleapis.com/v1beta", "google"),
    ("openai", "https://openrouter.ai/api/v1", "openrouter"),
    ("openai", "https://opencode.ai/inference/go/openai/v1", "opencode-go"),
    ("openai", "https://opencode.ai/zen/v1", "opencode"),
    ("openai", "https://api.z.ai/api/coding/paas/v4", "zai-coding-plan"),
    ("openai", "https://proxy.invalid/v1", None),
    ("openai", "http://api.openai.com/v1", None),
    ("openai", "https://api.openai.com.evil.invalid/v1", None),
    ("openai", "https://api.openai.com:444/v1", None),
    ("openai", "https://user@api.openai.com/v1", None),
    ("openai", "https://api.openai.com/v1/other", None),
    ("openai", "https://api.openai.com/v1?other=true", None),
    ("anthropic", OPENAI, None),
    ("openai", "https://api.minimax.io/anthropic/v1", None),
])
def test_exact_endpoint_identity(kind, url, expected):
    assert model_metadata._provider(kind, url) == expected


def test_public_catalog_strict_values():
    parsed = model_metadata._parse_catalog(CATALOG)
    assert parsed["openai"] == {"same": 400000, "manual": 200000, "not-listed": 128000}
    assert parsed["openrouter"] == {"same": 64000}
    with pytest.raises(ValueError):
        model_metadata._parse_catalog({"openai": {"models": []}})


@pytest.mark.asyncio
async def test_discovery_fallback_and_exact_model_identity(monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        if str(request.url) == PUBLIC:
            assert "authorization" not in request.headers
            assert "x-api-key" not in request.headers
            assert "x-goog-api-key" not in request.headers
            return httpx.Response(200, json=CATALOG)
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"data": [
            {"id": "same"}, {"id": "manual", "context_length": 32000},
            {"id": "same-v2"}, {"id": "bad"}, {"id": "wrong-id"},
            {"id": "output-only"}, {"id": "unknown"},
        ]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(respond), **kw))
    result = await model_discovery._fetch_models("openai", OPENAI, "secret")
    assert result["models"] == ["same", "manual", "same-v2", "bad", "wrong-id", "output-only", "unknown"]
    assert result["model_contexts"] == {"same": 400000, "manual": 32000}
    result = await model_discovery._fetch_models("openai-responses", "https://openrouter.ai/api/v1", "secret")
    assert result["model_contexts"] == {"same": 64000, "manual": 32000}
    result = await model_discovery._fetch_models("openai", "https://proxy.invalid/v1", "secret")
    assert result["model_contexts"] == {"manual": 32000}
    assert sum(str(r.url) == PUBLIC for r in requests) == 1


@pytest.mark.asyncio
async def test_cache_singleflight_expiry_and_failure(monkeypatch):
    now = 1.0
    calls = 0
    fail = False

    async def download():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        if fail:
            raise httpx.ConnectError("unavailable")
        return model_metadata._parse_catalog(CATALOG)

    monkeypatch.setattr(model_metadata, "_download_catalog", download)
    monkeypatch.setattr(model_metadata, "monotonic", lambda: now)
    cache = model_metadata._cache
    results = await asyncio.gather(*(cache.get() for _ in range(8)))
    assert calls == 1
    assert all(r["openai"]["same"] == 400000 for r in results)
    now += model_metadata._TTL + 1
    fail = True
    assert (await cache.get())["openai"]["same"] == 400000
    assert calls == 2
    assert (await cache.get())["openai"]["same"] == 400000
    assert calls == 2
    now += model_metadata._RETRY + 1
    fail = False
    await cache.get()
    assert calls == 3


@pytest.mark.asyncio
async def test_fallback_failure_is_nonfatal_and_not_retried_per_channel(monkeypatch):
    calls = 0

    async def download():
        nonlocal calls
        calls += 1
        raise ValueError("invalid public data")

    monkeypatch.setattr(model_metadata, "_download_catalog", download)
    known = {"same": 1234}
    await model_metadata.fill_missing_contexts("openai", OPENAI, known)
    await model_metadata.fill_missing_contexts("openai", "https://proxy.invalid/v1", {"same": None})
    assert calls == 0
    for _ in range(3):
        models = {"same": None, "manual": 32000}
        await model_metadata.fill_missing_contexts("openai", OPENAI, models)
        assert models == {"same": None, "manual": 32000}
    assert calls == 1


@pytest.mark.asyncio
async def test_saved_channel_upstream_and_manual_precedence(setup_profiles, monkeypatch):
    _, app = setup_profiles
    original = httpx.AsyncClient
    items = [{"id": "same"}, {"id": "manual"}]

    def respond(request):
        if str(request.url) == PUBLIC:
            return httpx.Response(200, json=CATALOG)
        return httpx.Response(200, json={"data": items})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(respond), **kw))
    async with original(transport=httpx.ASGITransport(app=app),
                        base_url="https://lsm.invalid", headers=_ADMIN) as client:
        response = await client.put("/api/lsm/providers", json={
            "name": "Official", "provider": "openai", "base_url": OPENAI,
            "api_key": "secret", "auto_discover": True, "models": ["same", "manual"],
            "model_contexts": {"manual": 16000},
        })
        assert response.status_code == 200, response.text
        assert profile("Official")["model_contexts"] == {"same": 400000, "manual": 16000}
        items = [{"id": "same", "context_length": 128000}, {"id": "manual", "context_length": 64000}]
        await model_discovery.refresh_model_channels(routes._repo().database)
        current = profile("Official")
        assert current["discovered_model_contexts"] == {"same": 128000, "manual": 64000}
        assert current["model_contexts"] == {"same": 128000, "manual": 16000}
        assert current["model_context_overrides"] == {"manual": 16000}
