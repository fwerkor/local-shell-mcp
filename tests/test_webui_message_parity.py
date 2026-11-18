"""Source-shaped DTO, real SQLite reload and provider wire regression vectors."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.mcp_content import format_tool_content, mcp_result_envelope
from local_shell_mcp.webui.mcp_projection import (
    mcp_tool_history_message,
    openai_wire_messages,
    project_artifact_messages,
)
from local_shell_mcp.webui.message_dto import format_agent_messages, format_message
from local_shell_mcp.webui.provider_tool_protocols import native_messages
from local_shell_mcp.webui.providers import ModelToolCall


def test_agent_ui_format_replays_ordered_calls_steer_and_per_step_thought_signatures():
    display = [{"role": "assistant", "text": "Not model truth", "metadata": {"thoughtSignatures": {
        "one": "sig-one", "two": "sig-two"}}, "content": [
            {"type": "think", "text": "reasoning kept outside text"},
            {"type": "text", "text": "First", "tool_call_ids": ["one"]},
            {"type": "tool_call", "tool_call": {"id": "one", "name": "file_read", "args": '{"path":"a"}', "output": "original A"}},
            {"type": "steer", "steer": "Use B"},
            {"type": "text", "text": "Second", "tool_call_ids": ["two"]},
            {"type": "tool_call", "tool_call": {"id": "two", "name": "file_read", "args": '{"path":"b"}', "output": "original B"}},
            {"type": "text", "text": "Finished"},
            {"type": "activity_label", "text": "never model input"},
        ]}]
    original = copy.deepcopy(display)
    result = format_agent_messages(display)
    assert [step["role"] for step in result] == ["assistant", "tool", "user", "assistant", "tool", "assistant"]
    assert [step["tool_call_id"] for step in result if step["role"] == "tool"] == ["one", "two"]
    assert result[0]["tool_calls"][0]["provider_data"]["thoughtSignature"] == "sig-one"
    assert result[3]["tool_calls"][0]["provider_data"]["thoughtSignature"] == "sig-two"
    assert result[2]["source"] == "steer"
    assert result[-1]["content"] == "Finished"
    assert display == original


def test_image_only_user_and_invalid_or_missing_tool_anchor():
    assert format_message({"sender": "User", "content": "", "image_urls": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]})["content"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]
    assert format_message({"sender": "User", "content": ""})["content"] == ""
    assert format_agent_messages([{"sender": "User", "content": ""}])[0]["content"] == [
        {"type": "text", "text": "(no text)"}]
    with pytest.raises(ValueError, match="anchor"):
        format_agent_messages([{"role": "assistant", "content": [{"type": "tool_call", "tool_call": {"id": "a"}}]}])
    with pytest.raises(ValueError, match="ID"):
        format_agent_messages([{"role": "assistant", "content": [{"type": "text", "tool_call_ids": ["x"]},
            {"type": "tool_call", "tool_call": {"name": "x"}}]}])


def test_mcp_source_text_images_binary_ui_resource_links_and_errors(monkeypatch):
    image = base64.b64encode(b"\x89PNG\x00").decode()
    source = {"isError": True, "_meta": {"origin": "mcp"}, "content": [
        {"type": "text", "text": "A"},
        {"type": "image", "mimeType": "image/png", "data": image},
        {"type": "resource", "resource": {"uri": "ui://screen", "mimeType": "text/html", "text": "<section>View</section>"}},
        {"type": "resource", "resource": {"uri": "bin://fixture", "mimeType": "application/octet-stream",
                                           "blob": base64.b64encode(b"\x00\xff").decode()}},
        {"type": "resource_link", "uri": "link://a\nInjected: b", "name": "reference\nHeader"},
    ]}
    text, artifact = format_tool_content(source)
    assert "A" in text and "UI Resource Marker: \\ui{" in text
    assert "Resource Content: 2 bytes" in text
    assert "Resource Name: reference Header" in text
    assert "Injected: b" in text and "link://a Injected" in text
    assert artifact["content"][0]["image_url"]["url"] == "data:image/png;base64," + image
    assert artifact["ui_resources"]["data"][0]["uri"] == "ui://screen"
    assert format_tool_content({"content": []}) == ("(No response)", None)
    assert mcp_result_envelope({"data": {"result": source}}, "mcp_tool_call") == source
    monkeypatch.setenv("MCP_IMAGE_DATA_MAX_BYTES", "1")
    with pytest.raises(ValueError, match="maximum"):
        format_tool_content(source)
    monkeypatch.setenv("MCP_IMAGE_DATA_MAX_BYTES", "invalid")
    assert format_tool_content(source)[1] is not None


def test_full_sqlite_reload_preserves_raw_steps_parallel_calls_and_ui_preview(tmp_path):
    db = SQLiteDatabase(tmp_path / "db")
    store = GenerationStore(db)
    job, _ = store.begin("alice", {"text": "Inspect both tools"})
    raw = "{" + "x" * 410000 + "}"
    calls = [ModelToolCall("c1", "a", {"x": 1}), ModelToolCall("c2", "b", {"x": 2}, {"thoughtSignature": "Gemini-signature"})]
    steps = [{"role": "assistant", "content": "Starting", "tool_calls": [
        {"id": c.call_id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
         **c.history_metadata()} for c in calls]},
        {"role": "tool", "tool_call_id": "c1", "content": raw},
        {"role": "tool", "tool_call_id": "c2", "content": "second result"},
        {"role": "assistant", "content": "Done"}]
    # UI step previews are optional and *not* the model's data source.
    store.append("alice", job.run_id, {"event": "on_run_step_completed", "data": {"result": {
        "id": "step1", "tool_call": {"id": "c1", "name": "a", "args": {}, "output": "short preview"}}}})
    assert store.finish("alice", job.run_id, status="complete", text="Done", model_steps=steps)
    store = GenerationStore(SQLiteDatabase(tmp_path / "db"))
    replay = store.history("alice", job.conversation_id)
    assert replay[0]["role"] == "user"
    assert replay[1:] == steps
    assert replay[2]["content"] == raw
    assert len(openai_wire_messages(replay)[2]["content"]) < len(raw)
    assert "truncated" in openai_wire_messages(replay)[2]["content"]
    assert native_messages(replay, "google")[0][1]["parts"][-1]["thoughtSignature"] == "Gemini-signature"
    followup, _ = store.begin("alice", {"conversationId": job.conversation_id, "text": "And now?"})
    chain = store.history("alice", job.conversation_id, message_id=followup.user_message_id)
    assert chain[:-1] == replay
    assert chain[-1]["content"] == "And now?"
    with db.connect() as conn:
        assistant = conn.execute("SELECT content FROM messages WHERE id=?", (job.response_message_id,)).fetchone()
        assert "short preview" in assistant["content"]
        state = conn.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()
        assert json.loads(state["state"])["modelSteps"] == steps


def test_replay_project_media_at_original_tool_batch_not_only_last_message():
    tool = ModelToolCall("id-1", "mcp_tool_call", {"name": "demo:read"})
    source = {"content": [{"type": "image", "mimeType": "image/png", "data": "AA=="}], "isError": False}
    result = mcp_tool_history_message(tool, json.dumps({"data": {"result": source}}), "openai")
    assert result["raw_result"] and result["artifact"]["content"]
    assistant = {"role": "assistant", "content": "", "tool_calls": [{"id": tool.call_id, "type": "function",
        "function": {"name": tool.name, "arguments": "{}"}}]}
    original = [assistant, result, {"role": "assistant", "content": "Rendered"}, {"role": "user", "content": "Next"}]
    expected = project_artifact_messages(original, "openai")
    assert [r["role"] for r in expected] == ["assistant", "tool", "user", "assistant", "user"]
    assert expected[2]["content"][-1]["type"] == "image_url"
    assert original[1]["content"] == "" and original[1]["artifact"] == result["artifact"]
    wire = openai_wire_messages(original)
    assert wire[2]["role"] == "user" and wire[2]["content"][-1]["type"] == "image_url"
    anthropic = native_messages(original, "anthropic")[0]
    assert any(b.get("type") == "image" for m in anthropic if m["role"] == "user"
               for block in (m["content"] if isinstance(m["content"], list) else [])
               for b in (block.get("content", []) if block.get("type") == "tool_result" else []))
    google = native_messages(original, "google")[0]
    assert any("inlineData" in b for m in google if m["role"] == "user" for b in m["parts"])


def test_invalid_vendor_blocks_fail_instead_of_leaking_local_metadata():
    with pytest.raises(ValueError, match="Unsupported"):
        native_messages([{"role": "user", "content": [{"type": "resource", "uri": "secret"}]}], "google")
    with pytest.raises(ValueError, match="matching"):
        native_messages([{"role": "tool", "tool_call_id": "missing", "content": "x"}], "google")
    with pytest.raises(ValueError, match="base64"):
        native_messages([{"role": "user", "content": [{"type": "image_url", "image_url": "https://example.com"}]}], "google")
    with pytest.raises(ValueError, match="role"):
        native_messages([{"role": "intruder", "content": "x"}], "anthropic")
    assert native_messages([{"role": "assistant", "content": "hello", "reasoning": [{"type": "thinking", "thinking": "secret"}]}], "anthropic")[0] == [
        {"role": "assistant", "content": "hello"}]

# Regenerate these fixtures using scripts/export-librechat-*-vectors.cjs and
# the exact pinned source/real @langchain/core 1.2.8 and TypeScript transpiler.
_REF = Path(__file__).parent / "fixtures" / "librechat"
_MSG_VECTORS = json.loads((_REF / "message_history_vectors.json").read_text())
_MCP_VECTORS = json.loads((_REF / "mcp_content_vectors.json").read_text())


def _normalize_source_shape(message):
    result = {"role": message["role"], "content": message.get("content")}
    calls = message.get("tool_calls")
    if calls:
        result["tool_calls"] = [{"id": c["id"], "name": c["function"]["name"],
                                 "args": json.loads(c["function"]["arguments"])} for c in calls]
        signatures = [(c.get("provider_data") or {}).get("thoughtSignature") for c in calls]
        if any(signatures):
            result["additional_kwargs"] = {"signatures": signatures}
    for field in ("name", "tool_call_id"):
        if message.get(field):
            result[field] = message[field]
    if message.get("source"):
        result["additional_kwargs"] = {"source": message["source"]}
    return result


@pytest.mark.parametrize("case", _MSG_VECTORS["vectors"], ids=lambda c: c["name"])
def test_differential_real_librechat_message_converter(case):
    # No fallback to hand-authored fixtures: these are exported using the
    # pinned original JavaScript function and actual locked LangChain classes.
    assert _MSG_VECTORS["sha256"] == "88f8a1b77d6171c9e180c942d6f59775c7e2c6103b3c4d75cb8b74622eff02ad"
    assert [_normalize_source_shape(item) for item in format_agent_messages(case["input"])] == case["expected"]


@pytest.mark.parametrize("case", _MCP_VECTORS["vectors"], ids=lambda c: c["name"])
def test_differential_real_librechat_mcp_parser(case):
    assert _MCP_VECTORS["sha256"] == "85170923b508332f4f9a647eeafbb7ac6d79d6d3fbb606d6f4d1838d7623d584"
    assert list(format_tool_content(case["result"], case["provider"])) == case["expected"]
