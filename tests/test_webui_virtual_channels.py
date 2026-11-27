"""Virtual models preserve logical identity while routing physical requests."""
from dataclasses import replace
import json

import httpx
import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import virtual_channels as routing
from local_shell_mcp.webui.agent_runtime import _retryable_model_error
from local_shell_mcp.webui.config_routes import _endpoint_models
from local_shell_mcp.webui.provider_profiles import _validate, _redact, profile
from local_shell_mcp.webui.providers import ModelUsage, provider_config, stream_model, stream_model_with_tools
from local_shell_mcp.webui.routes import _repo


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    get_settings.cache_clear()
    routing._health.clear()
    routing._affinity.clear()
    routing._cursors.clear()
    repo = _repo()
    for channel, model, limit in [("Primary", "flash-free", 128000), ("Backup", "flash", 1000000)]:
        value = _validate({"name": channel, "provider": "openai", "base_url": f"https://{channel.lower()}.invalid/v1",
                           "models": [model], "model_contexts": {model: limit}, "api_key": "test"})
        repo.save_setting("__lsm_controller__", "model.channel." + channel, value)
    value = _validate({"name": "Pool", "provider": "virtual", "routes": {
        "alias": [{"channel": "Primary", "model": "flash-free", "weight": 2},
                  {"channel": "Backup", "model": "flash", "weight": 1}],
        "other": [{"channel": "Backup", "model": "flash"}]}})
    repo.save_setting("__lsm_controller__", "model.channel.Pool", value)
    try:
        yield value
    finally:
        get_settings.cache_clear()
        routing._health.clear()
        routing._affinity.clear()
        routing._cursors.clear()


def test_catalog_inherits_min_context_without_credentials(pool):
    config = provider_config("Pool", "alias")
    assert config.virtual_channel == "Pool" and config.model == "alias"
    assert not config.token and not config.url
    assert profile("Pool")["model_contexts"] == {"alias": 128000, "other": 1000000}
    assert _endpoint_models()["Pool"] == ["alias", "other"]
    assert "api_key" not in _redact(pool)
    value = profile("Primary")
    value["model_contexts"]["flash-free"] = 65536
    _repo().save_setting("__lsm_controller__", "model.channel.Primary", value)
    assert profile("Pool")["model_contexts"]["alias"] == 65536
    value["model_contexts"] = {}
    _repo().save_setting("__lsm_controller__", "model.channel.Primary", value)
    assert "alias" not in profile("Pool")["model_contexts"]


@pytest.mark.parametrize("bad", [
    [{"channel": "Pool", "model": "alias"}],
    [{"channel": "Primary", "model": "missing"}],
    [{"channel": "Primary", "model": "flash-free", "weight": 0}],
    [{"channel": "Primary", "model": "flash-free"}] * 2,
])
def test_invalid_members(pool, bad):
    with pytest.raises(ValueError):
        _validate({"name": "Invalid", "provider": "virtual", "routes": {"alias": bad}})


def test_strategies_and_independent_model_cursors(pool):
    a, b = candidates = pool["routes"]["alias"]
    for m in candidates:
        routing._health[routing.member_key(m)] = routing.Health()
    for strategy, expected in [
        ("priority", [a, a, a]),
        ("round_robin", [a, b, a]),
        ("weighted_round_robin", [a, a, b]),
    ]:
        routing._cursors.clear()
        value = {**pool, "strategy": strategy}
        assert [routing.choose(value, "alias", candidates) for _ in range(3)] == expected
        assert routing.choose(value, "other", candidates) == a
    routing._health[routing.member_key(a)].active = 2
    assert routing.choose({**pool, "strategy": "least_connections"}, "alias", candidates) == b
    routing._health[routing.member_key(a)].latency = 2
    routing._health[routing.member_key(b)].latency = 1
    assert routing.choose({**pool, "strategy": "least_latency"}, "alias", candidates) == b


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [402, 429, 503])
async def test_real_http_failover_preserves_model_and_usage(pool, monkeypatch, status):
    seen = []
    original = httpx.AsyncClient

    def reply(request):
        seen.append((request.url.host, json.loads(request.content)["model"]))
        if request.url.host == "primary.invalid":
            return httpx.Response(status, json={"error": "test"})
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2}}\n\n'
            'data: [DONE]\n\n'))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(reply), **kw))
    config = replace(provider_config("Pool", "alias"), virtual_session=("owner", "conversation"))
    messages = [{"role": "user", "content": "Hello"}]
    output = [item async for item in stream_model(config, messages)]
    assert output[0] == "ok"
    assert output[-1] == ModelUsage("openai", 10, 2, channel="Backup", model="flash")
    assert seen == [("primary.invalid", "flash-free"), ("backup.invalid", "flash")]
    # Shared cooldown is not needed to keep affinity after the first successful turn.
    routing._health[("Primary", "flash-free")].cooldown = 0
    assert [item async for item in stream_model(config, messages)][0] == "ok"
    assert seen[-1] == ("backup.invalid", "flash")
    assert all(h.active == 0 for h in routing._health.values())


@pytest.mark.asyncio
async def test_partial_stream_is_not_replayed_and_close_releases_slot(pool, monkeypatch):
    from local_shell_mcp.webui import providers
    seen = []

    async def partial(config, messages, **kwargs):
        seen.append(config.model)
        yield "partial"
        raise httpx.ReadError("interrupted")

    monkeypatch.setattr(providers, "stream_model", partial)
    config = provider_config("Pool", "alias")
    stream = routing.stream_virtual(config, [])
    assert await anext(stream) == "partial"
    with pytest.raises(httpx.ReadError):
        await anext(stream)
    assert seen == ["flash-free"]
    assert all(h.active == 0 for h in routing._health.values())
    routing._health.clear()
    stream = routing.stream_virtual(config, [])
    assert await anext(stream) == "partial"
    await stream.aclose()
    assert all(h.active == 0 for h in routing._health.values())


@pytest.mark.asyncio
async def test_all_members_unavailable_is_retryable(pool, monkeypatch):
    from local_shell_mcp.webui import providers

    async def unavailable(config, messages, **kwargs):
        raise httpx.ConnectError("unavailable")
        yield

    monkeypatch.setattr(providers, "stream_model", unavailable)
    with pytest.raises(routing.VirtualUnavailable) as error:
        async for _ in routing.stream_virtual(provider_config("Pool", "alias"), []):
            pass
    assert _retryable_model_error(error.value)
    assert all(h.active == 0 for h in routing._health.values())


def test_opaque_reasoning_is_scoped_without_mutating_history():
    history = [{"role": "assistant", "content": "answer",
                "reasoning": [{"type": "thinking", "route_scope": "A", "signature": "sig"},
                              {"type": "responses_item", "scope": "other"}],
                "tool_calls": [{"id": "call", "provider_data": {"thoughtSignature": "g", "route_scope": "A"}}]}]
    assert routing.scoped_messages(history, "A") == history
    filtered = routing.scoped_messages(history, "B")[0]
    assert filtered["reasoning"] == [{"type": "responses_item", "scope": "other"}]
    assert not filtered["tool_calls"][0]["provider_data"]
    assert history[0]["tool_calls"][0]["provider_data"]["thoughtSignature"] == "g"
