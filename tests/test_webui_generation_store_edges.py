"""Crash-safe SQLite generation continuation, approval and audit edge cases."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generations
from local_shell_mcp.webui.generations import GenerationStore


@pytest.fixture
def current_run(tmp_path):
    db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    store = GenerationStore(db)
    job, fresh = store.begin("alice", {"text": "A multi-step task"})
    assert fresh
    return db, store, job


def test_generation_event_rejection_and_retention(current_run, monkeypatch):
    _, store, job = current_run
    with pytest.raises(ValueError, match="256 KiB"):
        store.append("alice", job.run_id, {"data": "A" * (257 * 1024)})
    with pytest.raises(KeyError):
        store.append("bob", job.run_id, {"event": "unauthorized"})
    monkeypatch.setattr(generations, "_EVENT_LIMIT", 1)
    with pytest.raises(ValueError, match="retention limit"):
        store.append("alice", job.run_id, {"event": "overflow"})
    assert store.events("bob", job.run_id) == []
    with pytest.raises(KeyError, match="Conversation not found"):
        store.history("bob", job.conversation_id)
    with pytest.raises(ValueError, match="terminal"):
        store.finish("alice", job.run_id, status="running")
    assert store.finish("alice", job.run_id, status="aborted")
    with pytest.raises(KeyError, match="not active"):
        store.append("alice", job.run_id, {"event": "after_abort"})
    assert not store.pause_for_question("alice", job.run_id, {}, [], "")


def test_invalid_ask_user_pause_and_recovery(current_run):
    db, store, job = current_run
    payload = {"actionId": "ask-1", "payload": {"type": "ask_user_question", "tool_call_id": "call-1"}}
    with pytest.raises(ValueError, match="too large"):
        store.pause_for_question("alice", job.run_id, payload,
                                 [{"role": "user", "content": "X" * 530000}], "")
    assert store.pause_for_question("alice", job.run_id, payload, [], "partial")
    with pytest.raises(ValueError, match="Ask User"):
        with db.connect() as conn:
            state = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0])
            state["pendingAction"]["payload"]["type"] = "tool_approval"
            conn.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), job.run_id))
        store.answer_question("alice", job.run_id, "ask-1", "answer")
    with db.connect() as conn:
        state = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0])
        state["pendingAction"]["payload"]["type"] = "ask_user_question"
        state["resumeHistory"] = None
        conn.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), job.run_id))
    with pytest.raises(ValueError, match="continuation"):
        store.answer_question("alice", job.run_id, "ask-1", "answer")
    assert store.pending_action("alice", job.run_id) is not None


def test_tool_approval_validation_and_exactly_once_claim(current_run):
    db, store, job = current_run
    request = {"name": "mcp_tool_call", "arguments": {"name": "server:tool"},
               "tool_call_id": "call-42"}
    pending = {"actionId": "approval-1", "payload": {
        "type": "tool_approval", "action_requests": [request],
    }}
    assert store.pause_for_approval("alice", job.run_id, pending, [], "partial answer")
    for decision, expected in [
        ([], "Exactly one"),
        ([{"decision": "maybe", "tool_call_id": "call-42"}], "approved or rejected"),
        ([{"decision": "approve", "tool_call_id": "other"}], "Mismatched"),
    ]:
        with pytest.raises(ValueError, match=expected):
            store.claim_approval("alice", job.run_id, "approval-1", decision)
    with pytest.raises(KeyError, match="No pending"):
        store.claim_approval("bob", job.run_id, "approval-1", [
            {"decision": "approve", "tool_call_id": "call-42"},
        ])
    with pytest.raises(ValueError, match="Stale"):
        store.claim_approval("alice", job.run_id, "outdated", [
            {"decision": "approve", "tool_call_id": "call-42"},
        ])
    with db.connect() as conn:
        state = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0])
        state["pendingAction"]["payload"]["type"] = "ask_user_question"
        conn.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), job.run_id))
    with pytest.raises(ValueError, match="Unexpected approval"):
        store.claim_approval("alice", job.run_id, "approval-1", [
            {"decision": "reject", "tool_call_id": "call-42"},
        ])
    with db.connect() as conn:
        state = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0])
        state["pendingAction"]["payload"]["type"] = "tool_approval"
        state["resumeHistory"] = None
        conn.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), job.run_id))
    with pytest.raises(ValueError, match="continuation"):
        store.claim_approval("alice", job.run_id, "approval-1", [
            {"decision": "reject", "tool_call_id": "call-42"},
        ])
    with db.connect() as conn:
        state = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0])
        state["resumeHistory"] = []
        conn.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), job.run_id))
    resumed, history, partial, requested, decision = store.claim_approval(
        "alice", job.run_id, "approval-1", [{"decision": "reject", "tool_call_id": "call-42"}],
    )
    assert resumed.run_id == job.run_id
    assert history == []
    assert partial == "partial answer"
    assert requested == request
    assert decision == "reject"
    with pytest.raises(KeyError, match="No pending"):
        store.claim_approval("alice", job.run_id, "approval-1", [
            {"decision": "reject", "tool_call_id": "call-42"},
        ])
