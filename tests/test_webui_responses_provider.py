"""Responses protocol uses the same saved channel, tools and agent loop."""
import asyncio
import copy
import json

import httpx
import pytest
from test_webui_provider_profiles import _ADMIN
from test_webui_provider_profiles import setup_profiles as setup_profiles

from local_shell_mcp.webui.agent_runtime import (
    AgentContext,
    AgentLoopState,
    ToolBatchOutput,
    run_agent_loop,
)
from local_shell_mcp.webui.model_discovery import _parse_page
from local_shell_mcp.webui.provider_responses import ResponsesStreamError, responses_input
from local_shell_mcp.webui.providers import (
    ModelFinish,
    ModelThought,
    ModelToolCall,
    ModelUsage,
    ProviderConfig,
    provider_config,
    stream_model,
    stream_model_with_tools,
)

PROFILE = ProviderConfig("openai-responses", "test", "https://model.invalid/v1/responses", "secret")
TOOLS = [{"type": "function", "function": {"name": "read", "description": "Read a file",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}]
USER = {"role": "user", "content": "Read file"}
REASON = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "encrypted-state"}
CALL = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read",
        "arguments": '{"path":"a.txt"}', "status": "completed"}
MESSAGE = {"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
           "phase": "commentary", "content": [{"type": "output_text", "text": "Reading", "annotations": []}]}


def complete(output, *, incomplete=False):
    return {"type": "response.incomplete" if incomplete else "response.completed",
            "response": {"status": "incomplete" if incomplete else "completed", "output": output,
                         "usage": {"input_tokens": 100, "output_tokens": 20},
                         **({"incomplete_details": {"reason": "max_output_tokens"}} if incomplete else {})}}


@pytest.fixture
def transport(monkeypatch):
    batches, requests = [], []
    original = httpx.AsyncClient

    def handle(request):
        requests.append((str(request.url), dict(request.headers), json.loads(request.content)))
        events = batches.pop(0)
        return httpx.Response(200, text="".join("data: " + (event if isinstance(event, str) else json.dumps(event)) + "\n\n"
                                               for event in events),
                              headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    return batches, requests


@pytest.mark.asyncio
async def test_responses_agent_roundtrip_preserves_output_order_and_canonical_arguments(transport):
    batches, requests = transport
    final = {**MESSAGE, "id": "msg_2", "phase": "final_answer",
             "content": [{"type": "output_text", "text": "Done", "annotations": []}]}
    batches.extend([
        [{"type": "response.reasoning_summary_text.delta", "delta": "Plan"},
         {"type": "response.output_text.delta", "output_index": 1, "delta": "Reading"},
         {"type": "response.output_item.added", "output_index": 2,
          "item": {**CALL, "arguments": ""}},
         {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": '{"path":'},
         {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": '"a.txt"}'},
         {"type": "response.output_item.done", "output_index": 2, "item": CALL},
         complete([REASON, MESSAGE, CALL])],
        [{"type": "response.output_text.delta", "output_index": 0, "delta": "Done"},
         complete([final])],
    ])
    state = AgentLoopState(AgentContext(PROFILE, TOOLS, {"max_tokens": 123}), [USER])
    seen_text, thoughts, usage, calls, checkpoints = [], [], [], [], []

    async def on_text(text):
        seen_text.append(text)

    async def on_thought(text):
        thoughts.append(text)

    async def on_usage(item, state):
        usage.append(item)

    async def dispatch(proposed, current):
        calls.extend(proposed)
        return ToolBatchOutput([{"role": "tool", "tool_call_id": proposed[0].call_id, "content": "file contents"}])

    async def save(current, pending):
        # Round trip through SQLite's JSON-compatible checkpoint representation.
        checkpoints.append(json.loads(json.dumps(current.messages)))

    await run_agent_loop(state, stream_tools=stream_model_with_tools, stream_text=stream_model,
                         dispatch=dispatch, on_text=on_text, on_thought=on_thought,
                         on_model_usage=on_usage, save_state=save)
    assert seen_text == ["Reading", "Done"]
    assert thoughts == ["Plan"]
    assert usage == [ModelUsage("openai-responses", 100, 20)] * 2
    assert len(calls) == 1 and calls[0].arguments == {"path": "a.txt"}
    url, headers, first = requests[0]
    assert url == PROFILE.url and headers["authorization"] == "Bearer secret"
    assert first["store"] is False and first["stream"] is True
    assert first["include"] == ["reasoning.encrypted_content"]
    assert first["max_output_tokens"] == 123
    assert first["tools"] == [{"type": "function", **TOOLS[0]["function"], "strict": False}]
    assert "messages" not in first and "previous_response_id" not in first
    second = requests[1][2]["input"]
    assert second[0] == {"role": "user", "content": [{"type": "input_text", "text": "Read file"}]}
    assert second[1] == REASON and second[2] == MESSAGE
    assert second[3]["type"] == "function_call" and second[3]["call_id"] == "call_1"
    assert json.loads(second[3]["arguments"]) == {"path": "a.txt"}
    assert second[4] == {"type": "function_call_output", "call_id": "call_1", "output": "file contents"}
    assert responses_input(PROFILE, checkpoints[-1])[-1] == final
    assert "encrypted-state" not in "".join(seen_text + thoughts)

    canonical = copy.deepcopy(checkpoints[-1])
    canonical[1]["tool_calls"][0]["function"]["arguments"] = '{"path":"redacted"}'
    assert json.loads(responses_input(PROFILE, canonical)[3]["arguments"]) == {"path": "redacted"}
    # Changed endpoint, account, model, text or preempted batch cannot replay stale metadata.
    for other in (ProviderConfig(PROFILE.provider, PROFILE.model, PROFILE.url, "other"),
                  ProviderConfig(PROFILE.provider, "other", PROFILE.url, PROFILE.token)):
        assert "encrypted-state" not in json.dumps(responses_input(other, canonical))
    canonical[1]["content"] = "edited"
    assert "encrypted-state" not in json.dumps(responses_input(PROFILE, canonical))
    canonical[1]["content"] = "Reading"
    canonical[1].pop("tool_calls")
    assert "encrypted-state" not in json.dumps(responses_input(PROFILE, canonical))


@pytest.mark.asyncio
async def test_text_summary_and_terminal_fallback(transport):
    batches, requests = transport
    batches.append([{"type": "response.output_item.done", "output_index": 0, "item": MESSAGE},
                    {"type": "response.completed", "response": {"status": "completed"}}])
    result = [event async for event in stream_model(PROFILE, [USER], temperature=0.4, top_p=0.8,
                                                    emit_finish_reason=True)]
    assert result[0] == "Reading" and isinstance(result[1], ModelThought)
    assert result[-1] == ModelFinish("openai-responses", "stop")
    assert requests[0][2]["temperature"] == 0.4 and requests[0][2]["top_p"] == 0.8
    batches.append([complete([MESSAGE], incomplete=True)])
    result = [event async for event in stream_model(PROFILE, [USER], emit_finish_reason=True)]
    assert result == ["Reading", ModelUsage("openai-responses", 100, 20),
                      ModelFinish("openai-responses", "max_output_tokens")]


@pytest.mark.asyncio
async def test_responses_provider_preserves_cache_hit_count(transport):
    batches, _ = transport
    frame = complete([MESSAGE])
    frame["response"]["usage"]["input_tokens_details"] = {"cached_tokens": 80}
    batches.append([frame])
    events = [event async for event in stream_model(PROFILE, [USER])]
    assert [event for event in events if isinstance(event, ModelUsage)] == [
        ModelUsage("openai-responses", 100, 20, 80)
    ]


@pytest.mark.parametrize("events,error", [
    ([{"type": "response.output_item.done", "output_index": 0, "item": CALL}], RuntimeError),
    ([{"type": "response.output_item.done", "output_index": 0, "item": CALL}, "[DONE]"], RuntimeError),
    ([complete([CALL], incomplete=True)], RuntimeError),
    ([complete([CALL, CALL])], ValueError),
    ([complete([{**CALL, "arguments": "bad"}])], ValueError),
    ([complete([{**CALL, "arguments": "[]"}])], ValueError),
    ([complete([{**CALL, "arguments": None}])], ValueError),
    ([complete([{**CALL, "status": "in_progress"}])], RuntimeError),
    ([{"type": "error"}], RuntimeError),
    ([{"type": "response.failed"}], RuntimeError),
    ([{"type": "response.completed", "response": None}], ValueError),
    ([{"type": "response.completed", "response": {"output": {}}}], ValueError),
    ([{"type": "response.output_text.delta", "output_index": 0, "delta": "different"}, complete([MESSAGE])], ValueError),
    ([{"type": "response.output_text.delta", "output_index": 1, "delta": "missing"}, complete([MESSAGE])], ValueError),
    ([{"type": "response.output_item.done", "output_index": -1, "item": CALL}], ValueError),
    ([{"type": "response.output_text.delta", "output_index": "0", "delta": "bad"}], ValueError),
    (["invalid json"], ValueError),
    (["[]"], ValueError),
])
@pytest.mark.asyncio
async def test_never_dispatches_unverified_tool_calls(transport, events, error):
    transport[0].append(events)
    received = []
    with pytest.raises(error):
        async for item in stream_model_with_tools(PROFILE, [USER], tools=TOOLS):
            received.append(item)
    assert not any(isinstance(item, ModelToolCall) for item in received)


def test_multimodal_and_tool_output_serialization():
    messages = [{"role": "system", "content": "Instructions"},
                {"role": "user", "content": [
                    {"type": "text", "text": "Look"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    {"type": "file", "file": {"filename": "a.pdf", "file_data": "data:application/pdf;base64,AAAA"}}]},
                {"role": "assistant", "content": "Checking", "tool_calls": [
                    {"id": "call", "function": {"name": "read", "arguments": {}}}]},
                {"role": "tool", "tool_call_id": "call", "content": "result"}]
    items = responses_input(PROFILE, messages)
    assert items[0]["role"] == "system"
    assert items[1]["content"] == [
        {"type": "input_text", "text": "Look"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA", "detail": "auto"},
        {"type": "input_file", "filename": "a.pdf", "file_data": "data:application/pdf;base64,AAAA"}]
    assert items[2] == {"role": "assistant", "content": "Checking"}
    assert items[3]["arguments"] == "{}" and items[4]["output"] == "result"


@pytest.mark.asyncio
async def test_fourth_protocol_shared_channel_and_catalog(setup_profiles, monkeypatch):
    _, app = setup_profiles
    from local_shell_mcp.webui import model_discovery
    calls = []

    async def fetch(kind, base, token, **kwargs):
        calls.append((kind, base, token))
        return {"models": ["reasoner"], "model_contexts": {"reasoner": 128000}}

    monkeypatch.setattr(model_discovery, "_fetch_models", fetch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.invalid", headers=_ADMIN) as client:
        body = {"name": "Responses gateway", "provider": "openai-responses",
                "base_url": "https://example.invalid/v1", "api_key": "key", "auto_discover": True}
        result = await client.put("/api/lsm/providers", json=body)
        assert result.status_code == 200, result.text
        assert calls == [("openai-responses", "https://example.invalid/v1", "key")]
        assert provider_config(body["name"]).url == "https://example.invalid/v1/responses"
        assert provider_config(body["name"]).provider == "openai-responses"
        assert (await client.get("/api/models")).json()[body["name"]] == ["reasoner"]
        assert (await client.get("/api/endpoints")).json()[body["name"]]["type"] == "openAI"
        assert (await client.get("/api/endpoints/token-config")).json()[body["name"]] == {"reasoner": {"context": 128000}}
        assert (await client.put("/api/lsm/providers", json={**body, "name": None})).status_code == 400
    models = {}
    _parse_page("openai-responses", {"data": [{"id": "reasoner", "supported_endpoints": ["/v1/responses"]},
                                            {"id": "chat", "supported_endpoints": ["/v1/chat/completions"]}]}, models)
    assert models == {"reasoner": None}


@pytest.mark.parametrize("message", [
    {"role": "user", "content": 3},
    {"role": "user", "content": ["invalid"]},
    {"role": "user", "content": [{"type": "image_url", "image_url": {}}]},
    {"role": "user", "content": [{"type": "file", "file": None}]},
    {"role": "user", "content": [{"type": "file", "file": {}}]},
    {"role": "user", "content": [{"type": "unknown"}]},
    {"role": "tool", "content": "missing identity"},
    {"role": "unknown", "content": "invalid"},
])
def test_invalid_input_rejected(message):
    with pytest.raises(ValueError):
        responses_input(PROFILE, [message])


def test_structured_tool_output_and_empty_messages():
    items = responses_input(PROFILE, [
        {"role": "user", "content": ""},
        {"role": "developer", "content": "Rules"},
        {"role": "tool", "tool_call_id": "call", "content": [{"type": "text", "text": "result"}]},
    ])
    assert items == [
        {"role": "developer", "content": [{"type": "input_text", "text": "Rules"}]},
        {"type": "function_call_output", "call_id": "call", "output": [{"type": "input_text", "text": "result"}]},
    ]


@pytest.mark.parametrize("extra", [
    {"index": -1, "item": REASON},
    {"index": 0, "item": None},
    {"index": 0, "item": {"type": "unknown"}},
    {"index": 0, "item": {"type": "function_call"}},
    {"index": 0, "item": {"type": "function_call", "call_id": "another"}},
    {"index": 1, "item": MESSAGE},
])
def test_invalid_replay_metadata_falls_back(extra):
    from local_shell_mcp.webui.provider_responses import _scope

    scope = _scope(PROFILE)
    meta = {"type": "responses_item", "scope": scope}
    message = {"role": "assistant", "content": "Reading",
               "reasoning": [{**meta, "index": 1, "item": MESSAGE}, {**meta, **extra}]}
    assert responses_input(PROFILE, [message]) == [{"role": "assistant", "content": "Reading"}]


def test_replay_ignores_unencrypted_reasoning_and_checks_call_metadata():
    from local_shell_mcp.webui.provider_responses import _scope

    scope = _scope(PROFILE)
    meta = {"type": "responses_item", "scope": scope}
    message = {"role": "assistant", "content": "Reading", "reasoning": [
        {**meta, "index": 0, "item": {"type": "reasoning"}},
        {**meta, "index": 1, "item": MESSAGE},
    ]}
    assert responses_input(PROFILE, [message]) == [MESSAGE]
    message["tool_calls"] = [{"id": "call", "function": {"name": "read", "arguments": "{}"}}]
    assert responses_input(PROFILE, [message]) == [
        {"role": "assistant", "content": "Reading"},
        {"type": "function_call", "call_id": "call", "name": "read", "arguments": "{}"},
    ]
    message["reasoning"] = [
        {**meta, "index": 0, "item": {"type": "function_call", "call_id": "call"}},
        {**meta, "index": 0, "item": MESSAGE},
    ]
    assert responses_input(PROFILE, [message])[0] == {"role": "assistant", "content": "Reading"}


@pytest.mark.asyncio
async def test_refusal_keyless_stream_and_empty_deltas(transport):
    batches, requests = transport
    refusal = {**MESSAGE, "content": [{"type": "refusal", "refusal": "Cannot comply"}]}
    batches.append([
        {"type": "response.output_text.delta", "output_index": 0, "delta": ""},
        {"type": "response.reasoning_summary_text.delta", "delta": ""},
        {"type": "response.refusal.delta", "output_index": 0, "delta": "Cannot comply"},
        complete([refusal, {"type": "reasoning", "id": "rs_2", "summary": []}]),
    ])
    keyless = ProviderConfig(PROFILE.provider, PROFILE.model, PROFILE.url, "")
    result = [item async for item in stream_model(keyless, [USER])]
    assert result[0] == "Cannot comply"
    assert "authorization" not in requests[0][1]
    assert len([item for item in result if isinstance(item, ModelThought)]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("events,error", [
    ([complete([MESSAGE], incomplete=True)], RuntimeError),
    ([complete([{"type": "unknown"}])], ValueError),
    ([complete([None])], ValueError),
    ([{"type": "response.completed", "response": {"status": "failed"}}], RuntimeError),
    ([complete([CALL])], ValueError),
])
async def test_text_stream_terminal_errors(transport, events, error):
    transport[0].append(events)
    with pytest.raises(error):
        _ = [item async for item in stream_model(PROFILE, [USER])]


@pytest.mark.asyncio
async def test_unsupported_tool_declaration():
    with pytest.raises(ValueError, match="Unsupported Responses tool"):
        _ = [item async for item in stream_model_with_tools(PROFILE, [USER], tools=[{"type": "invalid"}])]

@pytest.mark.parametrize("event,code,retryable", [
    ({"type": "error", "code": "rate_limit_exceeded", "message": "private key"}, "rate_limit_exceeded", True),
    ({"type": "response.failed", "response": {"error": {"code": "server_error"}}}, "server_error", True),
    ({"type": "response.cancelled"}, None, True),
    ({"type": "error", "error": {"type": "insufficient_quota"}}, "insufficient_quota", False),
    ({"type": "error", "code": "invalid_api_key"}, "invalid_api_key", False),
    ({"type": "error", "code": "private key"}, "unrecognized_code", False),
])
def test_sse_failure_classification_and_safe_diagnostics(event, code, retryable):
    from local_shell_mcp.webui.error_diagnostics import generation_failure

    error = ResponsesStreamError.from_event(event)
    assert error.event_type == event["type"]
    assert error.code == code and error.retryable is retryable
    diagnostic = generation_failure(error, "run")
    assert event["type"] in str(error) and event["type"] in diagnostic
    if code:
        assert code in diagnostic
    assert "private key" not in str(error) + diagnostic


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    {"type": "error", "code": "rate_limit_exceeded"},
    {"type": "response.failed", "response": {"error": {"code": "server_error"}}},
    {"type": "response.cancelled"},
    {"type": "response.completed", "response": {"status": "failed", "error": {"code": "server_error"}}},
])
async def test_parallel_responses_recover_empty_sse_failure(transport, monkeypatch, failure):
    from local_shell_mcp.webui import agent_runtime

    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0, 0))
    batches, requests = transport
    batches.extend([[complete([MESSAGE])]] * 8 + [[failure]] + [[complete([MESSAGE])]] * 2)

    async def run_child():
        state = AgentLoopState(AgentContext(PROFILE, []), [USER])
        text = []

        async def on_text(chunk):
            text.append(chunk)

        async def dispatch(*args):
            pytest.fail("unexpected tool dispatch")

        await run_agent_loop(state, stream_tools=stream_model_with_tools, stream_text=stream_model,
                             dispatch=dispatch, on_text=on_text)
        return "".join(text)

    assert await asyncio.gather(*(run_child() for _ in range(10))) == ["Reading"] * 10
    assert len(requests) == 11 and not batches


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,code", [
    ([], "insufficient_quota"),
    ([{"type": "response.output_text.delta", "output_index": 0, "delta": "partial"}], "server_error"),
    ([{"type": "response.reasoning_summary_text.delta", "delta": "thinking"}], "server_error"),
])
async def test_sse_does_not_retry_permanent_or_observable_failure(transport, monkeypatch, prefix, code):
    from local_shell_mcp.webui import agent_runtime

    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0, 0))
    batches, requests = transport
    batches.append(prefix + [{"type": "error", "code": code}])
    state = AgentLoopState(AgentContext(PROFILE, []), [USER])

    async def ignore(*args):
        pass

    with pytest.raises(ResponsesStreamError, match=code):
        await run_agent_loop(state, stream_tools=stream_model_with_tools, stream_text=stream_model,
                             dispatch=ignore, on_text=ignore, on_thought=ignore)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_sse_retry_preserves_completed_tool_results(transport, monkeypatch):
    from local_shell_mcp.webui import agent_runtime

    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0, 0))
    batches, requests = transport
    batches.extend([
        [complete([CALL])],
        [{"type": "response.output_item.done", "output_index": 0, "item": CALL},
         {"type": "response.failed", "response": {"error": {"code": "server_error"}}}],
        [complete([MESSAGE])],
    ])
    state = AgentLoopState(AgentContext(PROFILE, TOOLS), [USER])
    calls = []

    async def dispatch(proposed, current):
        calls.extend(proposed)
        return ToolBatchOutput([{"role": "tool", "tool_call_id": proposed[0].call_id, "content": "result"}])

    async def on_text(text):
        pass

    await run_agent_loop(state, stream_tools=stream_model_with_tools, stream_text=stream_model,
                         dispatch=dispatch, on_text=on_text)
    assert len(calls) == 1 and len(requests) == 3
    assert requests[1][2]["input"] == requests[2][2]["input"]

@pytest.mark.asyncio
async def test_repeated_sse_failures_exhaust_retry_budget(transport, monkeypatch):
    from local_shell_mcp.webui import agent_runtime

    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0, 0))
    batches, requests = transport
    batches.extend([[{"type": "response.failed", "response": {"error": {"code": "server_error"}}}]] * 3)
    state = AgentLoopState(AgentContext(PROFILE, []), [USER])

    async def unexpected(*args):
        pytest.fail("failed attempts must not publish text or dispatch tools")

    with pytest.raises(ResponsesStreamError, match="server_error"):
        await run_agent_loop(state, stream_tools=stream_model_with_tools, stream_text=stream_model,
                             dispatch=unexpected, on_text=unexpected)
    assert len(requests) == 3 and state.messages == [USER]


@pytest.mark.parametrize("with_tools", [False, True])
@pytest.mark.parametrize("url,model,auth_method,expected_header,expected_key", [
    ("https://api.openai.com/v1/responses", "gpt-5.5", None, None, "conversation-1"),
    ("https://api.openai.com/v1/responses", "gpt-6.2", None, None, None),
    ("https://api.openai.com/v1/responses", "gpt-6.2", "chatgpt", "session-id", None),
    ("https://chatgpt.com/backend-api/codex/responses", "gpt-5.5", None, "session-id", None),
    ("https://openrouter.ai/api/v1/responses", "openai/gpt-5.5", None, "x-session-id", None),
    ("https://gateway.invalid/v1/responses", "gpt-5.5", None, None, None),
])
async def test_responses_session_affinity_on_wire(transport, with_tools, url, model, auth_method,
                                                  expected_header, expected_key):
    from local_shell_mcp.webui.providers import bind_model_session

    batches, requests = transport
    batches.append([complete([MESSAGE])])
    config = bind_model_session(ProviderConfig("openai-responses", model, url, "secret",
                                               auth_method=auth_method), "conversation-1")
    source = stream_model_with_tools(config, [USER], tools=TOOLS) if with_tools else stream_model(config, [USER])
    assert any(event == "Reading" for event in [event async for event in source])
    _, headers, body = requests[-1]
    assert body.get("prompt_cache_key") == expected_key
    for name in ("session-id", "x-session-id", "x-opencode-session"):
        assert headers.get(name) == ("conversation-1" if name == expected_header else None)
