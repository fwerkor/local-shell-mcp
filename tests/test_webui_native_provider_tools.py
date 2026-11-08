"""Native provider wire protocols with real httpx SSE parsing and continuation."""
import json

import httpx
import pytest

from local_shell_mcp.webui.provider_tool_protocols import native_messages
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig, stream_model_with_tools

TOOLS = [{"type": "function", "function": {"name": "file_read", "description": "Read file",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}]


@pytest.fixture
def transport(monkeypatch):
    events = []
    requests = []
    original = httpx.AsyncClient
    def handle(request):
        requests.append((dict(request.headers), json.loads(request.content)))
        content = "".join("data: " + (event if isinstance(event, str) else json.dumps(event)) + "\n\n"
                          for event in events)
        return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})
    mock = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=mock, **kwargs))
    return events, requests


async def collect(provider, events, *, messages=None, temperature=None):
    return [event async for event in stream_model_with_tools(
        ProviderConfig(provider, "test", "https://provider.test/stream", "secret"),
        messages or [{"role": "system", "content": "Instructions"}, {"role": "user", "content": "Read a file"}],
        tools=TOOLS, temperature=temperature)]


@pytest.mark.parametrize("provider", ["anthropic", "google"])
async def test_native_tool_roundtrip_preserves_protocol_and_credentials(transport, provider):
    events, requests = transport
    if provider == "anthropic":
        events.extend([
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Checking"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tool-1", "name": "file_read", "input": {}}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":'}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '"a.txt"}'}},
            "[DONE]",
        ])
    else:
        events.extend([{"candidates": [{"content": {"parts": [
            {"text": "private thought", "thought": True}, {"text": "Checking"},
            {"functionCall": {"name": "file_read", "args": {"path": "a.txt"}}, "thoughtSignature": "signature"},
        ]}}]}, "[DONE]"])
    result = await collect(provider, events, temperature=0.3)
    assert result[0] == "Checking"
    call = result[1]
    assert isinstance(call, ModelToolCall)
    assert call.name == "file_read" and call.arguments == {"path": "a.txt"}
    headers, body = requests[-1]
    assert "secret" not in json.dumps(body)
    if provider == "anthropic":
        assert headers["x-api-key"] == "secret"
        assert body["tools"][0]["input_schema"] == TOOLS[0]["function"]["parameters"]
    else:
        assert headers["x-goog-api-key"] == "secret"
        assert body["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"] == TOOLS[0]["function"]["parameters"]
    history = [{"role": "system", "content": "Instructions"}, {"role": "user", "content": "Read file"},
        {"role": "assistant", "content": "Checking", "tool_calls": [{"id": call.call_id,
            "type": "function", **call.history_metadata(), "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}]},
        {"role": "tool", "tool_call_id": call.call_id, "content": "File contents"}]
    events[:] = ([{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Done"}}]
        if provider == "anthropic" else [{"candidates": [{"content": {"parts": [{"text": "Done"}]}}]}])
    assert await collect(provider, events, messages=history) == ["Done"]
    body = requests[-1][1]
    if provider == "anthropic":
        assert body["messages"][-1]["content"][0]["tool_use_id"] == call.call_id
    else:
        assert body["contents"][-2]["parts"][-1]["thoughtSignature"] == "signature"
        assert body["contents"][-1]["parts"][0]["functionResponse"]["name"] == "file_read"


@pytest.mark.parametrize("provider", ["anthropic", "google"])
async def test_unknown_frames_and_provider_error(transport, provider):
    events, _ = transport
    events[:] = ["invalid json", {"unrecognized": True}, {"error": {"message": "private provider diagnostic"}}]
    with pytest.raises(RuntimeError, match="rejected"):
        await collect(provider, events)


@pytest.mark.parametrize("case", ["index", "undeclared", "oversized", "arguments", "incomplete", "many"])
async def test_anthropic_rejects_invalid_partial_tool_calls(transport, case):
    events, _ = transport
    start = {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "id", "name": "file_read", "input": {}}}
    delta = {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}}
    if case == "index":
        start["index"] = -1
        events[:] = [start]
    elif case == "undeclared":
        events[:] = [delta]
    elif case == "oversized":
        delta["delta"]["partial_json"] = "x" * 9000
        events[:] = [start, delta]
    elif case == "arguments":
        delta["delta"]["partial_json"] = "[]"
        events[:] = [start, delta]
    elif case == "incomplete":
        start["content_block"]["name"] = ""
        events[:] = [start]
    else:
        events[:] = [{**start, "index": index} for index in range(5)]
    with pytest.raises(ValueError):
        await collect("anthropic", events)


@pytest.mark.parametrize("function", [[], {"name": "file_read", "args": []},
    {"name": "file_read", "args": {"text": "x" * 9000}}, {"name": "", "args": {}}])
async def test_gemini_rejects_invalid_tool_calls(transport, function):
    events, _ = transport
    events[:] = [{"candidates": [{"content": {"parts": [{"functionCall": function}]}}]}]
    with pytest.raises(ValueError):
        await collect("google", events)


async def test_gemini_bounds_parallel_calls_and_accepts_empty_history(transport):
    events, _ = transport
    events[:] = [{"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "file_read"}} for _ in range(5)]}}]}]
    with pytest.raises(ValueError):
        await collect("google", events)
    assert native_messages([{"role": "ignored"}, {"role": "assistant"},
                            {"role": "user", "content": "a"}, {"role": "user", "content": "b"}], "google") == (
        [{"role": "user", "parts": [{"text": "a"}, {"text": "b"}]}], "")
