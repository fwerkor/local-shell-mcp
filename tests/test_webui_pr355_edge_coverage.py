"""Provider, source-DTO and MCP artifact boundary checks for PR #355."""
from __future__ import annotations

import copy
import json

import pytest

from local_shell_mcp.webui.mcp_projection import (
    _Accumulator,
    _compact_segment,
    _count,
    mcp_tool_history_message,
    openai_wire_messages,
    project_artifact_messages,
)
from local_shell_mcp.webui.message_dto import format_agent_messages, format_message
from local_shell_mcp.webui.provider_tool_protocols import (
    _content_blocks,
    _reasoning_blocks,
    native_messages,
)
from local_shell_mcp.webui.providers import ModelToolCall


def test_message_dto_legacy_and_malformed_multimodal_edges():
    assert format_message({"role": "user", "content": "", "files": ["file"]})["content"] == "Please refer to the attached file(s)."
    assert format_message({"role": "user", "content": "text", "image_urls": [{"type": "image_url", "image_url": {"url": "x"}}]})["content"] == [
        {"type": "text", "text": "text"}, {"type": "image_url", "image_url": {"url": "x"}},
    ]
    assert format_message({"role": "assistant", "text": "x", "_name": "strange name!", "reasoning": []})["name"] == "strange_name_"
    assert format_agent_messages([{"role": "tool", "content": "ready", "tool_call_id": "call"}])[0]["content"] == [
        {"type": "text", "text": "ready"},
    ]
    assert format_agent_messages([{"role": "assistant", "content": None, "text": "legacy"}]) == [
        {"role": "assistant", "content": "legacy"},
    ]
    assert format_agent_messages([{"role": "assistant", "content": ["ignored", {"type": "error"},
        {"type": "text", "text": "Hello"}]}])[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}
    original = [{"role": "assistant", "content": [{"type": "text", "tool_call_ids": ["1"], "text": ""},
        {"type": "tool_call", "tool_call": {"id": "1", "name": "f", "args": "invalid", "raw_output": "raw"}}]}]
    result = format_agent_messages(original)
    assert json.loads(result[0]["tool_calls"][0]["function"]["arguments"]) == {"input": "invalid"}
    assert result[1]["content"] == "raw"
    assert original[0]["content"][1]["tool_call"]["args"] == "invalid"
    assert format_agent_messages([{"role": "assistant", "content": [{"type": "think", "text": "secret"},
        {"type": "text", "text": "answer"}]}]) == [{"role": "assistant", "content": "answer"}]
    assert format_agent_messages([{"role": "assistant", "content": [{"type": "steer", "media": [{"type": "text", "text": "prompt"}]}]}])[0]["content"] == [{"type": "text", "text": "prompt"}]


def test_mcp_projection_atomic_media_budget_fallback_and_immutable_raw_result():
    assert _count("😀") == 2
    assert _count([{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]) == 3
    assert _compact_segment([{"type": "text", "text": "text"}], 100) == [{"type": "text", "text": "text"}]
    assert _compact_segment([{"type": "image_url", "image_url": {"url": "long-image"}}], 1) == "["
    omitted = _compact_segment([{"type": "image_url", "image_url": {"url": "long-image"}}], 40)
    assert isinstance(omitted, list)
    with pytest.raises(ValueError, match="Unsupported"):
        _compact_segment([{"type": "unexpected"}], 20)
    accumulator = _Accumulator(4)
    accumulator.append("first")
    accumulator.append("second")
    assert accumulator.remaining >= 0
    assert accumulator.has_content
    assert _Accumulator(float("inf")).remaining > 400_000

    call = ModelToolCall("call-1", "mcp_tool_call", {"name": "source"})
    raw = {"data": {"result": {"content": [{"type": "image", "mimeType": "image/png", "data": "AA=="}]}}}
    tool = mcp_tool_history_message(call, json.dumps(raw), "openai")
    assert tool["artifact"]["content"]
    assert mcp_tool_history_message(call, "not json", "openai")["content"] == "not json"
    assert mcp_tool_history_message(call, '{}', "openai")["content"] == '{}'
    native_tool = ModelToolCall("read-1", "file_read", {"path": "raw.json"})
    assert mcp_tool_history_message(native_tool, json.dumps(raw), "openai")["content"] == json.dumps(raw)
    anchor = {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "function": {"name": "mcp_tool_call", "arguments": "{}"}}]}
    plain = {"role": "tool", "tool_call_id": "other", "content": "plain"}
    steps = [anchor, tool, {"role": "assistant", "content": "Answer"}, plain]
    before = copy.deepcopy(steps)
    projected = project_artifact_messages(steps, "anthropic", max_chars=4000)
    assert projected[1]["role"] == "tool" and any(p["type"] == "image_url" for p in projected[1]["content"])
    assert steps == before
    projected = project_artifact_messages(steps, "openai", max_chars=4000)
    assert projected[1]["content"].startswith("Tool response is included")
    assert projected[2]["role"] == "user"
    assert openai_wire_messages(steps)[1]["content"].startswith("Tool response")
    assert project_artifact_messages([{"role": "user", "content": "Hi"}], "openai") == [{"role": "user", "content": "Hi"}]


def test_native_provider_wire_rejects_unsupported_blocks_and_preserves_reasoning_signatures():
    image = {"type": "image_url", "image_url": {"url": "https://example.test/s.png"}}
    assert _content_blocks([image], "anthropic")[0]["source"] == {"type": "url", "url": "https://example.test/s.png"}
    with pytest.raises(ValueError, match="Anthropic"):
        _content_blocks([{"type": "image_url", "image_url": "file://private"}], "anthropic")
    with pytest.raises(ValueError, match="Unsupported"):
        _content_blocks([{"type": "file", "file_id": "private"}], "anthropic")
    reasoning = [{"type": "thinking", "thinking": "private", "signature": "sig"},
                 {"type": "redacted_thinking", "data": "opaque"},
                 {"type": "thinking", "thinking": "unsigned"}]
    assert _reasoning_blocks({"reasoning": reasoning}, "anthropic") == reasoning[:2]
    assert _reasoning_blocks({"reasoning": reasoning}, "google") == []
    assert _content_blocks([{"type": "image", "source": {"type": "url", "url": "https://source.test"}}], "anthropic") == [
        {"type": "image", "source": {"type": "url", "url": "https://source.test"}},
    ]
    with pytest.raises(ValueError, match="Invalid system"):
        native_messages([{"role": "system", "content": None}], "anthropic")
    with pytest.raises(ValueError, match="Invalid message content"):
        native_messages([{"role": "user", "content": {"unsafe": True}}], "google")
    with pytest.raises(ValueError, match="Tool result missing"):
        native_messages([{"role": "tool", "content": "orphan"}], "anthropic")
    with pytest.raises(ValueError, match="Invalid tool content"):
        native_messages([{"role": "tool", "tool_call_id": "id", "content": {"unsafe": 1}}], "anthropic")
    with pytest.raises(ValueError, match="Tool call arguments"):
        native_messages([{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "[]"}}]}], "google")
    native, system = native_messages([
        {"role": "system", "content": [{"type": "text", "text": "instruction"}, {"type": "image_url", "image_url": "ignored"}]},
        {"role": "assistant", "content": "intro", "reasoning": reasoning},
        {"role": "assistant", "content": "continuation"},
        {"role": "user", "content": "hi"},
    ], "anthropic")
    assert system == "instruction"
    assert native[0]["role"] == "assistant"
    assert native[0]["content"][0]["signature"] == "sig"
    assert any(part.get("type") == "text" for part in native[0]["content"])
