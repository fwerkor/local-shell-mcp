"""Virtual models preserve logical identity while routing physical requests."""
import json
from dataclasses import replace

import httpx
import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import virtual_channels as routing
from local_shell_mcp.webui.agent_runtime import _retryable_model_error
from local_shell_mcp.webui.config_routes import _endpoint_models
from local_shell_mcp.webui.provider_profiles import _redact, _validate, profile
from local_shell_mcp.webui.providers import (
    ModelUsage,
    provider_config,
    stream_model,
)
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


def _anthropic_member(pool):
    value = _validate({"name": "Claude", "provider": "anthropic",
                       "base_url": "https://claude.invalid/v1", "api_key": "test",
                       "models": ["claude-sonnet-4-6"]})
    _repo().save_setting("__lsm_controller__", "model.channel.Claude", value)
    routes = {"alias": [{"channel": "Claude", "model": "claude-sonnet-4-6"},
                        {"channel": "Backup", "model": "flash"}]}
    value = _validate({"name": "Pool", "provider": "virtual", "routes": routes})
    _repo().save_setting("__lsm_controller__", "model.channel.Pool", value)
    return routes


def test_virtual_sampling_uses_strictest_member_limit(pool):
    routes = _anthropic_member(pool)
    config = {"name": "Pool", "provider": "virtual", "routes": routes,
              "model_sampling": {"alias": {"temperature": 1.5}}}
    with pytest.raises(ValueError, match="temperature"):
        _validate(config)
    config["model_sampling"]["alias"]["temperature"] = 0.8
    assert _validate(config)["model_sampling"]["alias"]["temperature"] == 0.8
    config["routes"]["alias"] = [{"channel": "Backup", "model": "flash"}]
    config["model_sampling"]["alias"]["temperature"] = 1.5
    assert _validate(config)["model_sampling"]["alias"]["temperature"] == 1.5


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tools", [False, True])
@pytest.mark.parametrize("error_type,failover", [("overloaded_error", True), ("invalid_request_error", False),
                                               ("authentication_error", True)])
async def test_native_sse_failover_preserves_classification(pool, monkeypatch, with_tools, error_type, failover):
    from local_shell_mcp.webui.provider_responses import ResponsesStreamError
    from local_shell_mcp.webui.providers import stream_model_with_tools

    _anthropic_member(pool)
    seen = []
    original = httpx.AsyncClient

    def reply(request):
        seen.append(request.url.host)
        if request.url.host == "claude.invalid":
            event = {"type": "error", "error": {"type": error_type, "message": "private"}}
            return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(reply), **kw))
    config = provider_config("Pool", "alias")
    messages = [{"role": "user", "content": "Hello"}]
    stream = (stream_model_with_tools(config, messages, tools=[]) if with_tools
              else stream_model(config, messages))
    if failover:
        assert "ok" in [item async for item in stream]
        assert seen == ["claude.invalid", "backup.invalid"]
        assert routing._health[("Claude", "claude-sonnet-4-6")].cooldown > 0
    else:
        with pytest.raises(ResponsesStreamError) as exc:
            async for _ in stream:
                pass
        assert exc.value.code == error_type and not exc.value.retryable
        assert "private" not in str(exc.value)
        assert seen == ["claude.invalid"]
    assert all(h.active == 0 for h in routing._health.values())


def test_virtual_tool_media_uses_canonical_artifact():
    from local_shell_mcp.webui.mcp_content import format_tool_content
    from local_shell_mcp.webui.mcp_projection import mcp_tool_history_message, openai_wire_messages
    from local_shell_mcp.webui.providers import ModelToolCall

    source = {"content": [{"type": "image", "mimeType": "image/png", "data": "aGVsbG8="}]}
    text, artifact = format_tool_content(source, "virtual")
    assert text == ""
    assert artifact == format_tool_content(source, "openai")[1]
    call = ModelToolCall("call", "mcp_tool_call", {})
    message = mcp_tool_history_message(call, json.dumps(source), "virtual")
    assert message["artifact"] == artifact
    assert "aGVsbG8=" not in message["content"]
    assistant = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call", "type": "function", "function": {"name": "mcp_tool_call", "arguments": "{}"}},
    ]}
    assert "aGVsbG8=" in json.dumps(openai_wire_messages([assistant, message]))


@pytest.mark.parametrize("changes", [
    {"name": "invalid channel "}, {"strategy": "random"},
    {"session_affinity": 1}, {"routes": {}}, {"routes": {"": [{"channel": "Primary", "model": "flash-free"}]}},
    {"routes": {"alias": []}}, {"routes": {"alias": ["Primary"]}},
    {"model_sampling": {"missing": {"temperature": 0.5}}}, {"model_sampling": []},
])
def test_reject_invalid_virtual_channel_configuration(pool, changes):
    with pytest.raises(ValueError):
        _validate({"name": "NewPool", "provider": "virtual", "routes": pool["routes"], **changes})


def test_unavailable_members_are_filtered_from_catalog(pool):
    value = {**pool, "routes": {"alias": [
        {"channel": "Unknown", "model": "missing"},
        {"channel": "Pool", "model": "alias"},
        {"channel": "Primary", "model": "missing"},
        {"channel": "Backup", "model": "flash"},
    ]}}
    assert [routing.member_key(member) for member, _ in routing.physical_members(value, "alias")] == [
        ("Backup", "flash"),
    ]
    assert routing.context_windows(value) == {"alias": 1000000}
    with pytest.raises(ValueError, match="No available models"):
        provider_config("Pool", "unknown")


@pytest.mark.parametrize("status,expected", [(401, 300), (403, 300), (404, 60), (429, 7), (400, None)])
def test_cooldown_classifies_http_failures(status, expected):
    request = httpx.Request("POST", "https://provider.invalid/v1")
    response = httpx.Response(status, request=request, headers={"Retry-After": "7"})
    assert routing.cooldown_for(httpx.HTTPStatusError("error", request=request, response=response)) == expected


@pytest.mark.asyncio
async def test_virtual_routes_preserve_only_originating_signed_metadata(pool, monkeypatch):
    from local_shell_mcp.webui import providers
    from local_shell_mcp.webui.provider_responses import _scope
    from local_shell_mcp.webui.providers import ModelThought, ModelToolCall

    primary_scope = _scope(provider_config("Primary", "flash-free"))
    config = replace(provider_config("Pool", "alias"), virtual_session=("owner", "session"), session_id="stable-session")
    seen = []

    async def stream(actual, messages, **kwargs):
        seen.append(actual.model)
        assert actual.session_id == "stable-session"
        assert messages[0]["role"] == "user"
        assert messages[1]["reasoning"] == [{"type": "thinking", "route_scope": primary_scope}]
        yield ModelThought("thinking", text="thought", provider_data={"signature": "signed"})
        yield ModelToolCall("call", "tool", {}, provider_data={"thoughtSignature": "signed"})
        yield ModelToolCall("plain", "tool", {})

    monkeypatch.setattr(providers, "stream_model", stream)
    for i in range(8192):
        routing._affinity[("Pool", "alias", ("owner", i))] = ("Primary", "flash-free")
    messages = [{"role": "user", "content": "hello"},
                {"role": "assistant", "reasoning": [{"type": "thinking", "route_scope": primary_scope},
                                                   {"type": "thinking", "route_scope": "elsewhere"}]}]
    events = [item async for item in routing.stream_virtual(config, messages)]
    assert events[0].provider_data["route_scope"] == primary_scope
    assert events[1].provider_data["route_scope"] == primary_scope
    assert not events[2].provider_data
    assert len(routing._affinity) == 8192
    assert ("Pool", "alias", ("owner", 0)) not in routing._affinity
    assert routing._affinity[("Pool", "alias", config.virtual_session)] == ("Primary", "flash-free")
    assert seen == ["flash-free"]


@pytest.mark.asyncio
async def test_member_configuration_error_uses_next_healthy_member(pool, monkeypatch):
    from local_shell_mcp.webui import providers

    original = providers.provider_config
    config = original("Pool", "alias")

    def physical(channel, model):
        if channel == "Primary":
            raise ValueError("member credentials unavailable")
        return original(channel, model)

    async def stream(actual, messages, **kwargs):
        assert actual.model == "flash"
        yield "ok"

    monkeypatch.setattr(providers, "provider_config", physical)
    monkeypatch.setattr(providers, "stream_model", stream)
    assert [item async for item in routing.stream_virtual(config, [])] == ["ok"]
    assert routing._health[("Primary", "flash-free")].cooldown > 0
    assert all(h.active == 0 for h in routing._health.values())


def test_physical_channel_references_are_reported_for_deletion(pool):
    from local_shell_mcp.webui.provider_profiles import _reference_types

    with _repo().database.connect() as db:
        assert "virtual channels" in _reference_types(db, "Primary")
        assert "virtual channels" in _reference_types(db, "Backup")
        assert "virtual channels" not in _reference_types(db, "Unrelated")


@pytest.mark.asyncio
async def test_virtual_runner_records_physical_usage_and_session(pool, monkeypatch):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState
    from local_shell_mcp.webui.generations import GenerationStore

    db = _repo().database
    store = GenerationStore(db)
    job, _ = store.begin("alice", {"text": "hello"})
    config = provider_config("Pool", "alias")
    seen = []

    async def stream(profile, messages, **kwargs):
        seen.append(profile.virtual_session)
        yield "ok"

    async def emit(_):
        pass

    runner = AgentRunner("alice", job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=stream, stream_text=stream, on_text=emit, profile=config)
    messages = [{"role": "user", "content": "hello"}]
    assert [event async for event in runner._stream_with_image_fallback(stream, config, messages)] == ["ok"]
    assert seen == [("alice", job.conversation_id)]
    state = AgentLoopState(AgentContext(config, []), messages)
    usage = ModelUsage("openai", 100, 5, 20, channel="Backup", model="flash")
    await runner._observe_model_usage(usage, state)
    events = [event for _, event in store.events("alice", job.run_id)]
    route = next(event["data"] for event in events if event.get("event") == "on_model_route_usage")
    assert route["channel"] == "Backup" and route["model"] == "flash"
    assert route["inputTokens"] == 100 and route["outputTokens"] == 5
    snapshot = next(event["data"] for event in events if event.get("event") == "on_context_usage")
    assert snapshot["physicalChannel"] == "Backup" and snapshot["physicalModel"] == "flash"
    assert snapshot["physicalProvider"] == "openai"
    assert snapshot["providerInputTokens"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("already_invalid", [True, False])
async def test_oauth_member_reauthorization_fails_over(pool, monkeypatch, already_invalid):
    from local_shell_mcp.webui import model_oauth

    account = {
        "name": "Codex", "provider": "openai-responses",
        "base_url": model_oauth.RESOURCE, "models": ["test"],
        "api_key": "", "oauth_id": "account-id", "auth_method": "chatgpt",
        "oauth_error": "Sign in again" if already_invalid else None,
    }
    repo = _repo()
    repo.save_setting("__lsm_controller__", "model.channel.Codex", account)
    value = _validate({"name": "Pool", "provider": "virtual", "routes": {
        "alias": [{"channel": "Codex", "model": "test"},
                  {"channel": "Backup", "model": "flash"}]}})
    repo.save_setting("__lsm_controller__", "model.channel.Pool", value)

    seen = []
    attempts = []
    original_client = httpx.AsyncClient
    if not already_invalid:
        async def access(database, name, identity, *, rejected=None):
            assert (name, identity) == ("Codex", "account-id")
            attempts.append(rejected)
            if rejected:
                raise model_oauth.ReauthorizationRequired("Sign in again")
            return "old-token"

        monkeypatch.setattr(model_oauth, "access_token", access)

    def reply(request):
        seen.append(request.url.host)
        if request.url.host == "api.openai.com":
            return httpx.Response(401, json={"error": "revoked"})
        assert request.url.host == "backup.invalid"
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original_client(transport=httpx.MockTransport(reply), **kw))
    config = provider_config("Pool", "alias")
    messages = [{"role": "user", "content": "Hello"}]
    assert "ok" in [item async for item in stream_model(config, messages)]
    assert seen == (["backup.invalid"] if already_invalid else ["api.openai.com", "backup.invalid"])
    assert attempts == ([] if already_invalid else [None, "old-token"])
    assert routing._health[("Codex", "test")].cooldown > 0
    assert all(h.active == 0 for h in routing._health.values())
    assert routing.cooldown_for(ValueError("Unrelated configuration failure")) is None


@pytest.mark.asyncio
async def test_virtual_sampling_overrides_validate_selected_alias_before_dispatch(pool, monkeypatch):
    from local_shell_mcp.webui.sampling import validate_channel_sampling

    routes = _anthropic_member(pool)
    routes["other"] = [{"channel": "Backup", "model": "flash"}]
    _repo().save_setting("__lsm_controller__", "model.channel.Pool",
                         _validate({"name": "Pool", "provider": "virtual", "routes": routes}))
    assert validate_channel_sampling({"temperature": 1.5}, "Pool", "other") == {"temperature": 1.5}
    assert validate_channel_sampling({"temperature": 1}, "Pool", "alias") == {"temperature": 1}
    with pytest.raises(ValueError, match="temperature"):
        validate_channel_sampling({"temperature": 1.5}, "Pool", "alias")
    with pytest.raises(ValueError, match="temperature"):
        validate_channel_sampling({"temperature": 1.5}, "Pool")

    def unexpected_client(**kwargs):
        pytest.fail("invalid override reached provider transport")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    with pytest.raises(ValueError, match="temperature"):
        _ = [item async for item in stream_model(provider_config("Pool", "alias"), [],
                                                  temperature=1.5)]


def save_virtual(name, routes, **options):
    value = _validate({"name": name, "provider": "virtual", "routes": routes, **options})
    _repo().save_setting("__lsm_controller__", "model.channel." + name, value)
    return value


def member(channel, model, weight=1):
    return {"channel": channel, "model": model, "weight": weight}


def test_nested_catalog_context_and_cycle_detection(pool):
    save_virtual("Middle", {"mid": [member("Pool", "alias")]})
    save_virtual("Outer", {"outer": [member("Middle", "mid"), member("Backup", "flash")]})
    assert profile("Outer")["model_contexts"] == {"outer": 128000}
    assert _endpoint_models()["Outer"] == ["outer"]
    assert [routing.member_key(m) for m, _ in routing.physical_members(profile("Outer"), "outer")] == [
        ("Primary", "flash-free"), ("Backup", "flash"),
    ]
    with pytest.raises(ValueError, match="Recursive virtual channel"):
        _validate({"name": "Pool", "provider": "virtual",
                   "routes": {"other": [member("Outer", "outer")]}})
    with pytest.raises(ValueError, match="Recursive virtual channel"):
        _validate({"name": "NewPool", "provider": "virtual",
                   "routes": {"alias": [member("NewPool", "alias")]}})
    with _repo().database.connect() as db:
        from local_shell_mcp.webui.provider_profiles import _reference_types
        assert "virtual channels" in _reference_types(db, "Middle")
    primary = profile("Primary")
    primary["model_contexts"] = {}
    _repo().save_setting("__lsm_controller__", "model.channel.Primary", primary)
    assert profile("Outer")["model_contexts"] == {}


def test_nested_sampling_uses_physical_protocol(pool):
    claude = _validate({"name": "Claude", "provider": "anthropic", "base_url": "https://claude.invalid",
                        "api_key": "test", "models": ["sonnet"]})
    _repo().save_setting("__lsm_controller__", "model.channel.Claude", claude)
    save_virtual("Middle", {"mid": [member("Claude", "sonnet")]})
    with pytest.raises(ValueError, match="temperature"):
        save_virtual("Outer", {"outer": [member("Middle", "mid")]},
                     model_sampling={"outer": {"temperature": 1.5}})
    save_virtual("Outer", {"outer": [member("Middle", "mid")]})
    from local_shell_mcp.webui.sampling import validate_channel_sampling
    with pytest.raises(ValueError, match="temperature"):
        validate_channel_sampling({"temperature": 1.5}, "Outer", "outer")


@pytest.mark.asyncio
async def test_nested_independent_strategies_and_physical_usage(pool, monkeypatch):
    from local_shell_mcp.webui import providers

    save_virtual("Child", {"mid": pool["routes"]["alias"]},
                 strategy="weighted_round_robin", session_affinity=False)
    save_virtual("Outer", {"outer": [member("Child", "mid"), member("Backup", "flash")]},
                 strategy="round_robin", session_affinity=False)
    seen = []

    async def reply(config, messages, **kwargs):
        seen.append((config.model, config.session_id))
        yield ModelUsage("openai", 10, 2)

    monkeypatch.setattr(providers, "stream_model", reply)
    config = replace(provider_config("Outer", "outer"), session_id="session",
                     virtual_session=("owner", "conversation"))
    outputs = []
    for _ in range(6):
        outputs.extend([event async for event in routing.stream_virtual(config, [])])
    assert [m for m, _ in seen] == ["flash-free", "flash", "flash-free", "flash", "flash", "flash"]
    assert all(session == "session" for _, session in seen)
    assert [event.channel for event in outputs] == ["Primary", "Backup", "Primary", "Backup", "Backup", "Backup"]
    assert all(h.active == 0 for h in routing._health.values())


@pytest.mark.asyncio
async def test_nested_exhaustion_deduplicates_shared_leaves_and_recovers(pool, monkeypatch):
    from local_shell_mcp.webui import providers

    save_virtual("Child", {"mid": [member("Primary", "flash-free")]})
    save_virtual("Outer", {"outer": [member("Child", "mid"), member("Primary", "flash-free"),
                                     member("Backup", "flash")]})
    seen = []
    fail = True

    async def reply(config, messages, **kwargs):
        seen.append(config.model)
        if config.model == "flash-free" and fail:
            raise httpx.ConnectError("down")
        yield "ok"

    monkeypatch.setattr(providers, "stream_model", reply)
    config = provider_config("Outer", "outer")
    assert [event async for event in routing.stream_virtual(config, [])] == ["ok"]
    assert seen == ["flash-free", "flash"]
    assert routing._health[("Child", "mid")].cooldown == 0
    routing._health[("Primary", "flash-free")].cooldown = 0
    fail = False
    assert [event async for event in routing.stream_virtual(config, [])] == ["ok"]
    assert seen[-1] == "flash-free"
    assert all(h.active == 0 for h in routing._health.values())


@pytest.mark.asyncio
async def test_nested_affinity_and_partial_stream_never_replays(pool, monkeypatch):
    from local_shell_mcp.webui import providers

    save_virtual("Outer", {"outer": [member("Pool", "alias"), member("Backup", "flash")]})
    seen = []
    partial = False

    async def reply(config, messages, **kwargs):
        seen.append(config.model)
        if config.model == "flash-free":
            raise httpx.ConnectError("down")
        yield "ok"
        if partial:
            raise httpx.ReadError("interrupted")

    monkeypatch.setattr(providers, "stream_model", reply)
    session = ("owner", "conversation")
    config = replace(provider_config("Outer", "outer"), virtual_session=session)
    assert [event async for event in routing.stream_virtual(config, [])] == ["ok"]
    assert routing._affinity[("Outer", "outer", session)] == ("Pool", "alias")
    assert routing._affinity[("Pool", "alias", session)] == ("Backup", "flash")
    routing._health[("Primary", "flash-free")].cooldown = 0
    partial = True
    stream = routing.stream_virtual(config, [])
    assert await anext(stream) == "ok"
    assert routing._health[("Pool", "alias")].active == 1
    assert routing._health[("Backup", "flash")].active == 1
    with pytest.raises(httpx.ReadError):
        await anext(stream)
    assert seen == ["flash-free", "flash", "flash"]
    assert all(h.active == 0 for h in routing._health.values())


@pytest.mark.asyncio
async def test_image_fallback_is_scoped_to_physical_member(pool, monkeypatch):
    from local_shell_mcp.webui import providers
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore

    pool = dict(pool, strategy="round_robin", session_affinity=False)
    _repo().save_setting("__lsm_controller__", "model.channel.Pool", pool)
    db = _repo().database
    store = GenerationStore(db)
    job, _ = store.begin("alice", {"text": "image"})
    config = provider_config("Pool", "alias")
    seen = []
    original_stream = providers.stream_model

    async def model(profile, messages, **kwargs):
        if profile.provider == "virtual":
            async for event in original_stream(profile, messages, **kwargs):
                yield event
            return
        image = isinstance(messages[-1]["content"], list)
        seen.append((profile.model, image))
        if profile.model == "flash-free" and image:
            raise providers.UnsupportedImageInput("no vision")
        yield profile.model

    async def emit(_):
        pass

    monkeypatch.setattr(providers, "stream_model", model)
    runner = AgentRunner("alice", job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=emit, profile=config)
    messages = [{"role": "user", "source": "attachment", "attachmentImageIndices": [1],
                 "content": [{"type": "text", "text": "image path"},
                             {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}]}]
    for expected in ("flash-free", "flash", "flash-free", "flash"):
        assert [event async for event in runner._stream_with_image_fallback(model, config, messages)] == [expected]
    assert seen == [("flash-free", True), ("flash-free", False), ("flash", True),
                    ("flash-free", False), ("flash", True)]
    assert len(runner.image_disabled) == 1
    assert sum(event.get("event") == "on_attachment_image_fallback"
               for _, event in store.events("alice", job.run_id)) == 1
