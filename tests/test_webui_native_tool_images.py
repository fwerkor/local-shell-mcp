"""Native image tools must remain multimodal through live and reloaded history."""
import base64
import io
import json

import pytest
from PIL import Image

from local_shell_mcp.webui.mcp_projection import (
    mcp_tool_history_message, openai_wire_messages, project_artifact_messages,
)
from local_shell_mcp.webui.provider_responses import responses_input
from local_shell_mcp.webui.provider_tool_protocols import native_messages
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.fixture
def large_png():
    # Incompressible pixels ensure the encoded image exceeds the text budget.
    import random
    pixels = random.Random(42).randbytes(400 * 400 * 3)
    out = io.BytesIO()
    Image.frombytes("RGB", (400, 400), pixels).save(out, format="PNG")
    encoded = base64.b64encode(out.getvalue()).decode()
    assert len(encoded) > 400_000
    return encoded


@pytest.mark.parametrize("name", ["image_view", "gui_state"])
@pytest.mark.parametrize("legacy", [False, True])
def test_native_tool_image_wire_and_replay(large_png, name, legacy):
    call = ModelToolCall("id", name, {"path": "/tmp/example.png"})
    raw = json.dumps({
        "content": [{"type": "image", "mimeType": "image/png", "data": large_png},
                    {"type": "text", "text": "/tmp/example.png"}],
        "structuredContent": {"ok": True, "machine": "worker", "path": "/tmp/example.png"},
        "isError": False,
    })
    tool = mcp_tool_history_message(call, raw, "openai")
    assert tool["raw_result"] == raw
    assert large_png not in tool["content"]
    assert "worker" in tool["content"]
    if legacy:
        tool = {"role": "tool", "tool_call_id": "id", "content": raw}
    history = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "id", "type": "function", "function": {"name": name, "arguments": "{}"}}]},
        tool, {"role": "assistant", "content": "Done"}, {"role": "user", "content": "Next"}]
    original = json.dumps(history)
    image_url = "data:image/png;base64," + large_png
    wire = openai_wire_messages(history)
    assert wire[2]["content"][-1]["image_url"]["url"] == image_url
    assert large_png not in wire[1]["content"]
    anthropic, _ = native_messages(history, "anthropic")
    assert anthropic[1]["content"][0]["content"][-1]["source"]["data"] == large_png
    google, _ = native_messages(history, "google")
    assert any(p.get("inlineData", {}).get("data") == large_png
               for m in google for p in m["parts"])
    responses = responses_input(ProviderConfig("openai-responses", "test", "https://example.com", ""), history)
    assert any(p.get("image_url") == image_url for m in responses
               if isinstance(m.get("content"), list) for p in m["content"])
    assert json.dumps(history) == original
    # Even a fully consumed text budget cannot strip the image.
    projected = project_artifact_messages(history, "openai", max_chars=1)
    assert projected[2]["content"][-1]["image_url"]["url"] == image_url


def test_native_list_and_oversized_result(monkeypatch):
    call = ModelToolCall("id", "image_view", {})
    raw = json.dumps([{"type": "image", "mimeType": "image/png", "data": "AAAA"},
                      {"type": "text", "text": "/tmp/a.png"}])
    assert mcp_tool_history_message(call, raw, "openai")["artifact"]
    monkeypatch.setenv("MCP_IMAGE_DATA_MAX_BYTES", "1")
    result = mcp_tool_history_message(call, raw, "openai")
    assert "unavailable" in result["content"]
    assert "/tmp/a.png" in result["content"]
    assert "AAAA" not in result["content"]
    assert result["raw_result"] == raw


def test_native_image_resize_keeps_original_and_path(large_png, monkeypatch):
    monkeypatch.setenv("MCP_IMAGE_DATA_MAX_BYTES", "50000")
    call = ModelToolCall("id", "image_view", {})
    raw = json.dumps({"content": [
        {"type": "image", "mimeType": "image/png", "data": large_png},
        {"type": "text", "text": "/tmp/source.png"},
    ]})
    message = mcp_tool_history_message(call, raw, "openai")
    assert message["raw_result"] == raw
    assert "/tmp/source.png" in message["content"]
    assert "resized/compressed" in message["content"]
    url = message["artifact"]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    data = base64.b64decode(url.split(",", 1)[1], validate=True)
    assert len(data) <= 50000
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        assert image.size[0] <= 400


def test_real_native_dispatch_encoding(large_png):
    from local_shell_mcp.image_ops import ImageFile
    from local_shell_mcp.tools import _view_image_success_result
    from local_shell_mcp.webui.lsm_tool_registry import _encode_result

    binary = base64.b64decode(large_png)
    result = _view_image_success_result(
        ImageFile("/tmp/example.png", binary, "png", "image/png", len(binary)),
        "/tmp/example.png", "worker",
    )
    raw = _encode_result(result)
    call = ModelToolCall("id", "image_view", {"path": "/tmp/example.png", "machine": "worker"})
    message = mcp_tool_history_message(call, raw, "openai")
    assert message["artifact"]["content"][0]["image_url"]["url"].endswith(large_png)
    assert "worker" in message["content"]
    assert large_png not in message["content"]
