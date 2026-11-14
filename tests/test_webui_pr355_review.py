"""Regression cases for PR #355 review: resume, cloning and native UI attachments."""
from __future__ import annotations

import asyncio
import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner, generation_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.conversation_routes import _clone
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.routes import _repo
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def web_store(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    db = shared_database(get_settings().state_dir)
    yield GenerationStore(db)
    get_settings.cache_clear()


def test_fork_and_duplicate_keep_canonical_raw_provider_history(web_store):
    store = web_store
    run, _ = store.begin("local", {"text": "Look at the image"})
    result = '{"content":[{"type":"text","text":"nested tool output"}]}'
    steps = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "tool-A", "type": "function",
            "function": {"name": "mcp_tool_call", "arguments": "{}"},
            "provider_data": {"thoughtSignature": "provider-sig"}}]},
        {"role": "tool", "tool_call_id": "tool-A", "content": "nested tool output", "raw_result": result,
         "artifact": {"ui_resources": {"data": [{"resourceId": "r1", "uri": "ui://a", "text": "<b>hi</b>"}]}}},
        {"role": "assistant", "content": "Rendered"},
    ]
    store.append("local", run.run_id, {"event": "attachment", "data": {
        "type": "ui_resources", "messageId": run.response_message_id,
        "toolCallId": "tool-A", "conversationId": run.conversation_id,
        "ui_resources": [{"resourceId": "r1", "uri": "ui://a", "text": "<b>hi</b>"}],
    }})
    assert store.finish("local", run.run_id, status="complete", text="Rendered", model_steps=steps)
    original = store.history("local", run.conversation_id)
    assert original[1:] == steps
    for copy in (_clone("local", {"conversationId": run.conversation_id}),
                 _clone("local", {"conversationId": run.conversation_id}, only_to_message=run.response_message_id)):
        cid = copy["conversationId"]
        assert store.history("local", cid) == original
        assert store.history("local", cid)[1]["tool_calls"][0]["provider_data"] == {"thoughtSignature": "provider-sig"}
        with store.database.connect() as conn:
            state = json.loads(conn.execute("SELECT state FROM runs WHERE conversation_id=?", (cid,)).fetchone()["state"])
        assert state["userMessageId"] == copy["messages"][0]["messageId"]
        assert state["responseMessageId"] == copy["messages"][1]["messageId"]
        assert state["modelSteps"] == steps
        assert copy["messages"][1]["attachments"][0]["messageId"] == copy["messages"][1]["messageId"]
        assert copy["messages"][1]["attachments"][0]["conversationId"] == cid
        assert store.latest("local", cid).status == "complete"
        second, _ = store.begin("local", {"conversationId": cid, "text": "And now?"})
        assert store.history("local", cid, message_id=second.user_message_id)[:-1] == original
    user_only = _clone("local", {"conversationId": run.conversation_id}, only_to_message=run.user_message_id)
    with store.database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?", (user_only["conversationId"],)).fetchone()[0] == 0


def test_ui_resource_attachment_is_delivered_and_reloaded(web_store):
    store = web_store
    run, _ = store.begin("local", {"text": "Draw UI"})
    call = ModelToolCall("call-UI", "mcp_tool_call", {"name": "draw"})
    result = {"content": [{"type": "resource", "resource": {
        "uri": "ui://component/screen", "mimeType": "text/html", "text": "<div>native UI</div>"}}]}
    profile = ProviderConfig("openai", "demo", "https://test.invalid", "")

    async def consume():
        async def text(*args, **kwargs):
            yield "unused"

        async def emit(chunk):
            return None

        runner = AgentRunner("local", run, store.database, store, scopes=set(), grant_expires=None,
                             stream_tools=text, stream_text=text, on_text=emit, profile=profile)
        runner.saver.put_writes = lambda *args, **kwargs: None
        await runner._completed(call, {"output": json.dumps(result)})

    asyncio.run(consume())
    events = [event for _, event in store.events("local", run.run_id) if event.get("event") == "attachment"]
    assert len(events) == 1
    resource = events[0]["data"]
    assert resource["type"] == "ui_resources"
    assert resource["messageId"] == run.response_message_id
    assert resource["toolCallId"] == call.call_id
    assert resource["conversationId"] == run.conversation_id
    assert resource["ui_resources"][0]["uri"] == "ui://component/screen"
    assert resource["ui_resources"][0]["resourceId"]
    assert store.finish("local", run.run_id, status="complete", text="Here's your UI")
    final = store.events("local", run.run_id)[-1][1]["responseMessage"]
    assert final["attachments"] == [resource]
    reloaded = WorkspaceRepository(store.database).messages("local", run.conversation_id)["messages"][-1]
    assert reloaded["attachments"] == [resource]


def test_single_native_attachment_record_updates_without_duplication(web_store):
    store = web_store
    run, _ = store.begin("local", {"text": "Export"})
    attachment = {"file_id": "file-1", "type": "file", "messageId": run.response_message_id,
                  "toolCallId": "tool-1", "conversationId": run.conversation_id, "status": "pending"}
    store.append("local", run.run_id, {"event": "attachment", "data": attachment})
    store.append("local", run.run_id, {"event": "attachment", "data": {**attachment, "status": "ready", "text": "ready"}})
    ui = {"type": "ui_resources", "toolCallId": "tool-2", "messageId": run.response_message_id,
          "conversationId": run.conversation_id, "ui_resources": [{"resourceId": "r2", "uri": "ui://a"}]}
    store.append("local", run.run_id, {"event": "attachment", "data": ui})
    store.append("local", run.run_id, {"event": "attachment", "data": ui})
    assert store.finish("local", run.run_id, status="complete", text="Done")
    final = store.events("local", run.run_id)[-1][1]["responseMessage"]
    assert len(final["attachments"]) == 2
    assert final["attachments"][0]["status"] == "ready"
    assert final["attachments"][0]["text"] == "ready"


@pytest.mark.asyncio
async def test_ask_user_resume_preserves_original_assistant_call_and_response(web_store, monkeypatch):
    store = web_store
    run, _ = store.begin("local", {"text": "Choose a file"})
    profile = ProviderConfig("openai", "fake", "https://test.invalid", "")
    counter = 0

    async def stream(profile, history, **kwargs):
        nonlocal counter
        counter += 1
        if counter == 1:
            yield ModelToolCall("ask-1", "ask_user_question", {"question": "Which file?"})
        else:
            assert history[-1]["role"] == "tool"
            yield "Will inspect it."

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", stream)
    monkeypatch.setattr(agent_runner, "provider_config", lambda *_: profile)
    await generation_routes._run_model("local", run, profile, ask_user_enabled=True)
    pending = store.pending_action("local", run.run_id)
    assert pending is not None
    resumed, history, previous_text = store.answer_question("local", run.run_id, pending["actionId"], {"answer": "README.md"})
    assert store.model_history_boundary("local", run.run_id) == 1
    await generation_routes._run_model("local", resumed, profile, ask_user_enabled=True,
                                       resume_history=history, partial_text=previous_text)
    assert store.latest("local", run.conversation_id).status == "complete"
    canonical = store.history("local", run.conversation_id)
    assert [step["role"] for step in canonical] == ["user", "assistant", "tool", "assistant"]
    assert canonical[1]["tool_calls"][0]["id"] == "ask-1"
    assert canonical[2]["tool_call_id"] == "ask-1"
    assert "README.md" in canonical[2]["content"]


@pytest.mark.asyncio
async def test_approval_resume_preserves_declared_tool_call_before_result(web_store, monkeypatch):
    store = web_store
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {
        "enabled": True, "ask": ["file_write"],
    }}})
    run, _ = store.begin("local", {"text": "Write file"})
    profile = ProviderConfig("openai", "fake", "https://test.invalid", "")
    counter = 0

    async def stream(profile, history, **kwargs):
        nonlocal counter
        counter += 1
        if counter == 1:
            yield ModelToolCall("write-1", "file_write", {"path": "draft.txt", "content": "yes"})
        else:
            assert history[-1]["role"] == "tool"
            yield "Saved."

    async def fake_call(*args, **kwargs):
        return "written"

    from local_shell_mcp.webui import lsm_tool_registry
    monkeypatch.setattr(lsm_tool_registry, "call_tool", fake_call)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", stream)
    monkeypatch.setattr(agent_runner, "provider_config", lambda *_: profile)
    await generation_routes._run_model("local", run, profile, granted_scopes=frozenset({"shell:read", "shell:write"}))
    pending = store.pending_action("local", run.run_id)
    assert pending is not None
    resumed, history, previous_text, batch = store.claim_approval(
        "local", run.run_id, pending["actionId"], [{"tool_call_id": "write-1", "decision": "approve"}],
    )
    await generation_routes._run_model("local", resumed, profile, resume_history=history,
                                       partial_text=previous_text, approved_batch=batch,
                                       granted_scopes=frozenset({"shell:read", "shell:write"}))
    assert store.latest("local", run.conversation_id).status == "complete"
    canonical = store.history("local", run.conversation_id)
    assert [step["role"] for step in canonical] == ["user", "assistant", "tool", "assistant"]
    assert canonical[1]["tool_calls"][0]["id"] == canonical[2]["tool_call_id"] == "write-1"
