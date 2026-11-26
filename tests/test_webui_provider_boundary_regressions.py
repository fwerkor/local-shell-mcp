"""Regression coverage for provider credentials, native media and policy boundaries."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from local_shell_mcp.webui import content_filters, machine_permissions, model_oauth, routes
from local_shell_mcp.webui.mcp_projection import mcp_tool_history_message, project_artifact_messages
from local_shell_mcp.webui.provider_responses import _response_stream, responses_input
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("second_status", [200, 401])
async def test_account_response_refreshes_only_once(monkeypatch, second_status):
    db = object()
    monkeypatch.setattr(routes, "_repo", lambda: SimpleNamespace(database=db))
    requests = []
    refreshes = []

    async def token(database, channel, account, *, rejected=None):
        assert database is db
        assert (channel, account) == ("channel", "account")
        refreshes.append(rejected)
        return "old-token" if rejected is None else "new-token"

    def upstream(request):
        requests.append(request.headers["Authorization"])
        assert json.loads(request.content) == {"model": "test"}
        return httpx.Response(401 if len(requests) == 1 else second_status)

    monkeypatch.setattr(model_oauth, "access_token", token)
    url = model_oauth.adapter("chatgpt").base_url + "/responses"
    config = ProviderConfig("openai-responses", "test", url, "",
                            account_channel="channel", account_id="account", auth_method="chatgpt")
    async with (httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client,
                _response_stream(client, config, {"model": "test"}, {}) as response):
        assert response.status_code == second_status
    assert requests == ["Bearer old-token", "Bearer new-token"]
    assert refreshes == [None, "old-token"]


@pytest.mark.asyncio
async def test_account_credentials_cannot_leave_authorized_endpoint(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("An unauthorized endpoint must not obtain a token")
    monkeypatch.setattr(model_oauth, "access_token", forbidden)
    config = ProviderConfig("openai-responses", "test", "https://other.invalid/responses", "",
                            account_channel="channel", account_id="account", auth_method="chatgpt")
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="different API endpoint"):
            async with _response_stream(client, config, {}, {}):
                pytest.fail("An unauthorized endpoint must not receive a request")


def test_chatgpt_tool_namespace_matches_call_and_result():
    config = ProviderConfig("openai-responses", "test", "https://test.invalid", "", auth_method="chatgpt")
    call = {"id": "call_1", "type": "function",
            "function": {"name": "file_read", "arguments": "{}"}}
    items = responses_input(config, [
        {"role": "system", "content": "Instructions"},
        {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "call_1", "content": "file"},
    ])
    assert items[0]["role"] == "developer"
    assert items[1]["namespace"] == items[2]["namespace"] == "lsm"
    assert items[1]["name"] == items[2]["name"] == "file_read"
    assert items[1]["call_id"] == items[2]["call_id"]


@pytest.mark.parametrize("raw", ["not JSON", "null", '{"content": [{"type": "resource"}]}'])
def test_unrecognized_native_result_is_not_reinterpreted(raw):
    result = mcp_tool_history_message(ModelToolCall("media", "image_view", {}), raw, "openai")
    assert result == {"role": "tool", "tool_call_id": "media", "content": raw}


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_mixed_image_and_text_tool_batch_keeps_text_result(provider):
    calls = [
        {"id": "media", "type": "function", "function": {"name": "image_view", "arguments": "{}"}},
        {"id": "plain", "type": "function", "function": {"name": "file_read", "arguments": "{}"}},
    ]
    media = mcp_tool_history_message(ModelToolCall("media", "image_view", {}),
                                    json.dumps([{"type": "image", "mimeType": "image/png", "data": "AAAA"}]),
                                    provider)
    plain = {"role": "tool", "tool_call_id": "plain", "content": "plain result"}
    history = [{"role": "assistant", "content": "", "tool_calls": calls}, media, plain]
    result = project_artifact_messages(history, provider)
    assert result[2] == plain
    assert history[1] == media
    assert result[1]["artifact"]["content"] == []


def test_registry_failure_and_invalid_worker_names_do_not_grant_access(monkeypatch):
    def unavailable():
        raise RuntimeError("Registry unavailable")
    monkeypatch.setattr("local_shell_mcp.remote.remote_manager", unavailable)
    assert machine_permissions._registered_defaults() == {"local": "write"}
    registry = SimpleNamespace(list_machines=lambda: {
        "machines": [None, {"name": "../unknown"}, {"name": "worker"}],
    })
    monkeypatch.setattr("local_shell_mcp.remote.remote_manager", lambda: registry)
    assert machine_permissions._registered_defaults() == {"local": "write", "worker": "write"}


def test_malformed_provider_context_is_not_treated_as_valid_text():
    fragments = content_filters.model_message_fragments([
        None, {"role": "unknown", "content": "ignored"},
        {"role": "user", "content": [None, {"type": "text", "text": 123}]},
        {"role": "assistant", "tool_calls": [None, {"function": "invalid"}]},
    ])
    assert len(fragments) == 1
    assert len(fragments[0].text) > content_filters._MAX_FIELD_CHARS


def test_parameter_wrapper_cycle_is_bounded_and_malformed_wrapper_scanned():
    parameters = {"options": "secret"}
    parameters["model_parameters"] = parameters
    fragments = content_filters.model_parameter_fragments(parameters)
    assert [(part.field, part.text) for part in fragments] == [("request_fields", "secret")]


def test_oversized_provider_context_and_nested_parameters_fail_closed():
    count = content_filters._MAX_NODES + 1
    excessive = ["private"] * count
    fragments = content_filters.model_message_fragments([
        {"role": "user", "content": [{"type": "text", "text": "part"}] * count},
        {"role": "assistant", "reasoning": excessive, "tool_calls": [
            {"function": {"name": "file_read", "arguments": excessive}},
        ]},
    ])
    assert len(fragments) == 3
    assert all(len(fragment.text) > content_filters._MAX_FIELD_CHARS for fragment in fragments)
    fragments = content_filters.model_parameter_fragments({"metadata": excessive})
    assert len(fragments) == 1
    assert len(fragments[0].text) > content_filters._MAX_FIELD_CHARS
    fragments = content_filters.model_parameter_fragments({"metadata": {str(i): "secret" for i in range(count)}})
    assert len(fragments) == 1
    assert len(fragments[0].text) > content_filters._MAX_FIELD_CHARS


def test_parameter_wrapper_depth_budget_protects_every_relevant_field(monkeypatch):
    monkeypatch.setattr(content_filters, "_MAX_DEPTH", 2)
    fragments = content_filters.model_parameter_fragments({
        "options": {"options": {"options": {"metadata": "secret"}}},
    })
    assert {part.field for part in fragments} == {"stop", "request_fields", "response_format", "metadata"}
    assert all(len(part.text) > content_filters._MAX_FIELD_CHARS for part in fragments)


def test_native_media_budget_cannot_decode_excessive_pixels_or_emit_oversized_image(monkeypatch):
    import base64
    from io import BytesIO

    from PIL import Image

    from local_shell_mcp import image_ops
    from local_shell_mcp.webui import mcp_projection

    image = Image.new("RGB", (16, 16), color="red")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    block = {"type": "image", "mimeType": "image/png",
             "data": base64.b64encode(buffer.getvalue()).decode()}
    monkeypatch.setattr(mcp_projection, "_NATIVE_IMAGE_MAX_BYTES", 20)
    with monkeypatch.context() as patch:
        patch.setattr(image_ops, "MAX_PREVIEW_SOURCE_PIXELS", 100)
        with pytest.raises(ValueError, match="decode dimensions"):
            mcp_projection._bounded_native_image(block)
    with pytest.raises(ValueError, match="cannot fit media budget"):
        mcp_projection._bounded_native_image(block)
