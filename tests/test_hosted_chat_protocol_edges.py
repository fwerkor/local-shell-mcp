from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from local_shell_mcp import hosted_chat
from local_shell_mcp.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.delenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("endpoint", [
    "http://example.com/v1", "https://localhost/v1", "https://my.local/v1",
    "https://my.internal/v1", "https://127.0.0.1/v1", "https://[::1]/v1",
    "https://user@example.com/v1", "https://example.com/v1#fragment",
    "https://example.com/v1?key=secret", "not-a-url",
])
def test_rejects_unsafe_model_endpoints(endpoint):
    with pytest.raises(ValueError):
        hosted_chat.validate_endpoint(endpoint)


def test_allows_private_gateway_only_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS", "true")
    get_settings.cache_clear()
    assert hosted_chat.validate_endpoint("http://127.0.0.1:8765/v1/") == "http://127.0.0.1:8765/v1"
    assert hosted_chat.validate_endpoint("https://localhost:7654/api") == "https://localhost:7654/api"
    with pytest.raises(ValueError):
        hosted_chat.validate_endpoint("http://user:pass@localhost/v1")


@pytest.mark.parametrize("messages", [
    None, "a string", [{"role": "system", "content": "override"}],
    [{"role": "wrong"}], [42], [{"role": "user", "content": 42}],
    [{"role": "user", "content": "x" * (hosted_chat.MAX_TEXT + 1)}],
])
def test_invalid_client_history_is_rejected(messages):
    with pytest.raises(ValueError):
        hosted_chat.normalize_messages(messages)


def test_history_is_normalized_and_unsupported_fields_dropped():
    history = hosted_chat.normalize_messages([
        {"role": "user", "content": "hello", "debug_metadata": "secret"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call"}]},
        {"role": "tool", "content": "result", "tool_call_id": "call"},
    ])
    assert len(history) == 3
    assert "debug_metadata" not in history[0]
    assert history[1]["content"] is None


class Tool:
    def __init__(self, name="run_shell", hidden=False):
        self.name = name
        self.hidden = hidden

    def model_dump(self, **_):
        result = {"name": self.name, "inputSchema": {"type": "object"}}
        if self.hidden:
            result["_meta"] = {"ui": {"visibility": ["app"]}}
        return result


class Result:
    isError = False

    def model_dump(self, **_):
        return {"content": [{"type": "text", "text": "output"}], "_meta": {"private": "secret"}}


class FakeSession:
    def __init__(self):
        self.calls = []
        self.resources = []
        self.call_options = []

    async def list_tools(self):
        return SimpleNamespace(tools=[Tool(), Tool("app_only", hidden=True)])

    async def call_tool(self, name, args, **kwargs):
        self.call_options.append(kwargs)
        self.calls.append((name, args))
        return Result()

    async def read_resource(self, uri):
        self.resources.append(uri)
        return Result()


def install_fake_mcp(monkeypatch):
    session = FakeSession()

    @asynccontextmanager
    async def fake_mcp(*_):
        yield session

    monkeypatch.setattr(hosted_chat, "mcp_session", fake_mcp)
    return session


def test_tool_visibility_schema_and_private_metadata():
    assert [t.name for t in hosted_chat.visible_tools([Tool(), Tool("secret", True)])] == ["run_shell"]
    schema = hosted_chat.tool_schema(Tool())
    assert schema["function"]["name"] == "run_shell"
    assert "secret" not in hosted_chat.safe_tool_message(Result())


@pytest.mark.asyncio
async def test_mcp_bridge_rejects_non_app_resources(monkeypatch):
    session = install_fake_mcp(monkeypatch)
    with pytest.raises(ValueError, match="UI resources"):
        await hosted_chat.read_mcp_resource("http://controller", "", "file:///etc/passwd")
    assert (await hosted_chat.call_mcp("http://controller", "", "run_shell", {"command": "echo"}))["content"]
    assert (await hosted_chat.read_mcp_resource("http://controller", "", "ui://test/app"))["content"]
    assert session.calls == [("run_shell", {"command": "echo"})]
    assert session.call_options[0]["read_timeout_seconds"].total_seconds() > 300
    assert session.resources == ["ui://test/app"]


@pytest.mark.parametrize("mode,pattern", [
    ("http-error", "Model API returned HTTP"),
    ("tool-disabled", "Invalid model tool calls"),
    ("too-many-calls", "Invalid model tool calls"),
    ("unknown-tool", "unknown or unauthorized"),
    ("invalid-json", "invalid tool arguments"),
    ("invalid-type", "must be a JSON object"),
    ("limit-calls", "call limit reached"),
    ("limit-steps", "iteration limit reached"),
])
@pytest.mark.asyncio
async def test_model_tool_call_protocol_errors(monkeypatch, mode, pattern):
    session = install_fake_mcp(monkeypatch)
    def tool_call(name="run_shell", raw='{"command":"echo"}', ident="call-1"):
        return {"id": ident, "function": {"name": name, "arguments": raw}}

    class FakeHttp:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def post(self, *_, **__):
            if mode == "http-error":
                return SimpleNamespace(status_code=429)
            calls = [tool_call()]
            if mode == "too-many-calls":
                calls *= 9
            elif mode == "unknown-tool":
                calls = [tool_call(name="unauthorized")]
            elif mode == "invalid-json":
                calls = [tool_call(raw="{")]
            elif mode == "invalid-type":
                calls = [tool_call(raw="[]")]
            return SimpleNamespace(status_code=200, json=lambda: {"choices": [{"message": {"tool_calls": calls}}]})

    async def fake_target(endpoint):
        return endpoint + "/chat/completions", {}, {}
    async def fake_response(http, url, headers, extensions, payload):
        response = await http.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise ValueError(f"Model API returned HTTP {response.status_code}")
        return response.json()
    monkeypatch.setattr(hosted_chat, "model_request_target", fake_target)
    async def candidates(endpoint):
        return [await fake_target(endpoint)]
    monkeypatch.setattr(hosted_chat, "model_request_targets", candidates)
    monkeypatch.setattr(hosted_chat, "model_response_json", fake_response)
    monkeypatch.setattr(hosted_chat.httpx, "AsyncClient", lambda **_: FakeHttp())
    if mode == "limit-calls":
        monkeypatch.setattr(hosted_chat, "MAX_CALLS", 0)
    if mode == "limit-steps":
        monkeypatch.setattr(hosted_chat, "MAX_STEPS", 1)
    with pytest.raises(ValueError, match=pattern):
        await hosted_chat.complete_turn(
            base_url="http://controller", bearer="", endpoint="https://example.org/v1",
            key="key", model="unit-model", messages=[{"role": "user", "content": "hello"}],
            tools_enabled=mode != "tool-disabled",
        )
    assert not session.calls or mode in {"limit-steps"}


@pytest.mark.parametrize("calls,pattern", [
    ([{"function": {"name": "run_shell", "arguments": "{}"}}], "nonempty IDs"),
    ([{"id": "", "function": {"name": "run_shell", "arguments": "{}"}}], "nonempty IDs"),
    ([{"id": 123, "function": {"name": "run_shell", "arguments": "{}"}}], "nonempty IDs"),
    ([
        {"id": "duplicate", "function": {"name": "run_shell", "arguments": "{}"}},
        {"id": "duplicate", "function": {"name": "run_shell", "arguments": "{}"}},
    ], "unique nonempty IDs"),
    ([
        {"id": "good", "function": {"name": "run_shell", "arguments": "{}"}},
        {"function": {"name": "run_shell", "arguments": "{}"}},
    ], "nonempty IDs"),
    ([
        {"id": "good", "function": {"name": "run_shell", "arguments": "{}"}},
        {"id": "bad", "function": {"name": "run_shell", "arguments": "{"}},
    ], "invalid tool arguments"),
    ([
        {"id": "good", "function": {"name": "run_shell", "arguments": "{}"}},
        {"id": "bad", "function": {"name": "not_allowed", "arguments": "{}"}},
    ], "unknown or unauthorized"),
])
@pytest.mark.asyncio
async def test_malformed_tool_batch_never_checkpointed_or_executed(monkeypatch, calls, pattern):
    session = install_fake_mcp(monkeypatch)
    checkpoints = []

    class FakeHttp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def candidates(endpoint):
        return [(endpoint + "/chat/completions", {}, {})]

    async def response(*_args):
        return {"choices": [{"message": {"content": "", "tool_calls": calls}}]}

    async def checkpoint(messages, events):
        checkpoints.append((messages, events))

    monkeypatch.setattr(hosted_chat.httpx, "AsyncClient", lambda **_: FakeHttp())
    monkeypatch.setattr(hosted_chat, "model_request_targets", candidates)
    monkeypatch.setattr(hosted_chat, "model_response_json", response)
    with pytest.raises(ValueError, match=pattern):
        await hosted_chat.complete_turn(
            base_url="http://controller", bearer="", endpoint="https://example.org/v1",
            key="key", model="unit-model", messages=[{"role": "user", "content": "hello"}],
            tools_enabled=True, checkpoint=checkpoint,
        )
    assert session.calls == []
    assert checkpoints == []


@pytest.mark.asyncio
async def test_turn_bounds_model_key_and_history(monkeypatch):
    for key, model, messages in [
        ("x" * 8193, "model", [{"role": "user", "content": "hi"}]),
        ("ok", "", [{"role": "user", "content": "hi"}]),
        ("ok", "model", []),
        ("ok", "model", [{"role": "assistant", "content": "no last user"}]),
    ]:
        with pytest.raises(ValueError):
            await hosted_chat.complete_turn(
                base_url="http://controller", bearer="", endpoint="https://example.org/v1",
                key=key, model=model, messages=messages, tools_enabled=False,
            )
    session = install_fake_mcp(monkeypatch)
    requests = []
    checkpoints = []

    async def checkpoint(messages, events):
        checkpoints.append((messages, events))

    class FakeHttp:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def post(self, *_, **kwargs):
            requests.append(deepcopy(kwargs["json"]))
            return SimpleNamespace(status_code=200, json=lambda: {"choices": [{"message": {"content": "ok"}}]})

    async def fake_target(endpoint):
        return endpoint + "/chat/completions", {}, {}
    async def fake_response(http, url, headers, extensions, payload):
        response = await http.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise ValueError(f"Model API returned HTTP {response.status_code}")
        return response.json()
    monkeypatch.setattr(hosted_chat, "model_request_target", fake_target)
    async def candidates(endpoint):
        return [await fake_target(endpoint)]
    monkeypatch.setattr(hosted_chat, "model_request_targets", candidates)
    monkeypatch.setattr(hosted_chat, "model_response_json", fake_response)
    monkeypatch.setattr(hosted_chat.httpx, "AsyncClient", lambda **_: FakeHttp())
    history = [{"role": "user", "content": str(i)} for i in range(100)]
    result = await hosted_chat.complete_turn(
        base_url="http://controller", bearer="", endpoint="https://example.org/v1",
        key="key", model="model", messages=history, tools_enabled=False, checkpoint=checkpoint,
    )
    assert len(result["messages"]) == 101
    assert len(checkpoints[-1][0]) == 101
    # A hard 64-message cap is no longer used; compact is token-budget driven.
    assert len(requests[0]["messages"]) == 101
    assert session.calls == []
    assert "tools" not in requests[0]


def test_long_running_mcp_timeout_tracks_remote_budget(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S", "5400")
    get_settings.cache_clear()
    assert hosted_chat._mcp_tool_timeout_seconds() >= 5460


def test_gui_image_results_preserve_accessibility_state_and_valid_json():
    import json

    class GuiResult:
        def model_dump(self, **_kwargs):
            return {
                "content": [
                    {"type": "image", "mimeType": "image/png", "data": "ABCD" * 75000},
                    {"type": "text", "text": 'state_id=state-123; button=Submit; role=button'},
                ],
                "structuredContent": {"state_id": "state-123", "elements": [{"role": "button", "name": "Submit"}]},
                "_meta": {"ui": {"secret": "private oauth key"}},
                "isError": False,
            }

    visible = hosted_chat.safe_tool_message(GuiResult())
    assert len(visible) <= hosted_chat.MAX_TEXT
    assert "state-123" in visible
    assert "button=Submit" in visible
    assert "private oauth key" not in visible
    assert "ABCD" * 25 not in visible
    parsed = json.loads(visible)
    assert parsed["content"][0]["type"] == "image"
    assert "data" not in parsed["content"][0]
    assert "Screenshot omitted" in parsed["content"][0]["note"]


def test_oversized_tool_text_preserves_bounded_observation_as_json():
    import json

    class VerboseResult:
        def model_dump(self, **_kwargs):
            return {
                "content": [
                    {"type": "text", "text": "first: state-id=a; " + "x" * 90000},
                    {"type": "text", "text": "secondary"},
                ],
                "isError": False,
            }

    message = hosted_chat.safe_tool_message(VerboseResult())
    assert len(message) <= hosted_chat.MAX_TEXT
    parsed = json.loads(message)
    assert "state-id=a" in parsed["content"][0]["text"]
    assert "truncated" in parsed["content"][0]["text"]
    assert parsed["content"][1]["type"] == "text"


def test_large_escaped_structured_observation_stays_valid_and_bounded():
    import json

    class Result:
        def model_dump(self, **_kwargs):
            return {
                "content": [{"type": "text", "text": "\\" * 100_000}] * 100,
                "structuredContent": {"metadata": "\t" * 100_000},
            }

    result = hosted_chat.safe_tool_message(Result())
    assert len(result) <= hosted_chat.MAX_TEXT
    assert json.loads(result)["content"]


def test_tool_observation_keeps_text_resources_and_omits_nontext_payloads():
    import json

    class MixedResult:
        def model_dump(self, **_kwargs):
            return {
                "content": [
                    None,
                    {"type": "resource", "resource": {
                        "uri": "ui://local-shell-mcp/state", "text": "accessible state data",
                    }},
                    {"type": "resource", "resource": "malformed content"},
                    {"type": "audio", "data": "secret-binary" * 10000},
                    {"type": "image", "mimeType": "image/jpeg", "data": "hidden-b64"},
                    {"type": "text", "text": "button state_id=xyz"},
                ],
                "isError": True,
            }

    message = hosted_chat.safe_tool_message(MixedResult())
    parsed = json.loads(message)
    assert parsed["isError"] is True
    assert parsed["content"][0] == {
        "type": "resource", "uri": "ui://local-shell-mcp/state", "text": "accessible state data",
    }
    assert parsed["content"][1] == {"type": "audio", "note": "Non-text content omitted"}
    assert parsed["content"][2]["type"] == "image"
    assert "hidden-b64" not in message
    assert "secret-binary" not in message
    assert "state_id=xyz" in message


def test_tool_message_accepts_empty_result_and_bounds_large_resource_text():
    import json

    class Result:
        def __init__(self, content):
            self.content = content

        def model_dump(self, **_kwargs):
            return {"content": self.content}

    assert json.loads(hosted_chat.safe_tool_message(Result([]))) == {"content": []}
    resource = {"type": "resource", "resource": {
        "uri": "ui://test/resource", "text": "y" * 50000,
    }}
    message = hosted_chat.safe_tool_message(Result([resource]))
    assert len(message) < hosted_chat.MAX_TEXT
    assert "truncated" in message
    assert "ui://test/resource" in message


def test_many_escaped_embedded_resources_converge_without_blocking():
    import json

    class Result:
        def model_dump(self, **_kwargs):
            return {"content": [
                {"type": "resource", "resource": {
                    "uri": f"ui://test/{index}", "text": "\n" * 4000,
                }}
                for index in range(8)
            ]}

    message = hosted_chat.safe_tool_message(Result())
    assert len(message) <= hosted_chat.MAX_TEXT
    resources = json.loads(message)["content"]
    assert len(resources) == 8
    assert all(item["type"] == "resource" for item in resources)
    assert all("truncated" in item["text"] for item in resources)


def test_unshrinkable_tool_metadata_returns_bounded_valid_json():
    import json

    class Result:
        def model_dump(self, **_kwargs):
            return {
                "content": [{"type": "resource", "resource": {
                    "uri": "ui://" + "x" * 50000,
                    "text": "important but too small to shrink",
                }}],
                "isError": True,
            }

    message = hosted_chat.safe_tool_message(Result())
    assert len(message) <= hosted_chat.MAX_TEXT
    parsed = json.loads(message)
    assert parsed["isError"] is True
    assert "omitted" in parsed["content"][0]["text"]
