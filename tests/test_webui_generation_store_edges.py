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
    # SQLite continuation state is not a browser-event preview; it must not
    # impose a 512 KiB cap on valid model/tool history.
    assert store.pause_for_question("alice", job.run_id, payload,
                                   [{"role": "user", "content": "X" * 530000}], "partial")
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
        "review_configs": [{"tool_call_id": "call-42", "action_name": "mcp_tool_call", "allowed_decisions": ["approve", "reject"]}],
    }}
    assert store.pause_for_approval("alice", job.run_id, pending, [], "partial answer")
    for decision, expected in [
        ([], "Every paused tool call"),

        ([{"decision": "approve", "tool_call_id": "other"}], "Invalid tool approval decisions"),
    ]:
        with pytest.raises(ValueError, match=expected):
            store.claim_approval("alice", job.run_id, "approval-1", decision)
    with pytest.raises(PermissionError, match="Decision not permitted"):
        store.claim_approval("alice", job.run_id, "approval-1", [
            {"decision": "maybe", "tool_call_id": "call-42"}])
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
    resumed, history, partial, batch = store.claim_approval(
        "alice", job.run_id, "approval-1", [{"decision": "reject", "tool_call_id": "call-42"}],
    )
    assert resumed.run_id == job.run_id
    assert history == []
    assert partial == "partial answer"
    assert batch.entries[0].call_id == request["tool_call_id"]
    assert batch.entries[0].tool_call().arguments == request["arguments"]
    assert batch.entries[0].decision == {"type": "reject"}
    with pytest.raises(KeyError, match="No pending"):
        store.claim_approval("alice", job.run_id, "approval-1", [
            {"decision": "reject", "tool_call_id": "call-42"},
        ])


@pytest.mark.parametrize(('payload', 'error'), [
    ({'text': 'task', 'conversationId': 123}, 'Invalid conversation id'),
    ({'text': 'task', 'clientRequestId': ''}, 'Invalid client request id'),
    ({'text': 'task', 'clientRequestId': 'x' * 161}, 'Invalid client request id'),
    ({'text': 'task', 'projectId': []}, 'Invalid project id'),
    ({'text': 'task', 'projectId': 'missing-project'}, 'Project not found'),
    ({'text': 'task', 'conversationId': 'no-such-conversation'}, 'Conversation not found'),
    ({'text': 'task', 'text2': None, 'projectId': None}, None),
])
def test_generation_creation_validates_boundaries_before_writing(current_run, payload, error):
    _, store, _ = current_run
    if error is None:
        result, fresh = store.begin('alice', payload)
        assert fresh and result.status == 'running'
        return
    with pytest.raises((ValueError, KeyError), match=error):
        store.begin('alice', payload)


def test_oauth_dispatch_requires_original_stage_and_durable_completion_proof(current_run):
    db, store, job = current_run
    with pytest.raises(ValueError, match='stage'):
        store.oauth_dispatch('alice', job.run_id, 'call-1', 'unrecognized')
    with pytest.raises(PermissionError, match='no longer active'):
        store.oauth_dispatch('other', job.run_id, 'call-1', 'completed')
    assert store.oauth_dispatch('alice', job.run_id, 'call-1', 'completed') is None

    with db.connect() as sql:
        state = json.loads(sql.execute('SELECT state FROM runs WHERE id=?', (job.run_id,)).fetchone()[0])
        state['oauthResume'] = {'stage': 'claimed', 'tool_call_id': 'call-1'}
        state['partialText'] = 'Saved prefix'
        state['resumeHistory'] = [{'role': 'user', 'content': 'initial'}]
        sql.execute('UPDATE runs SET state=? WHERE id=?', (json.dumps(state), job.run_id))

    store.oauth_dispatch('alice', job.run_id, 'another-call', 'dispatching')
    with pytest.raises(PermissionError, match='dispatch record'):
        store.oauth_dispatch('alice', job.run_id, 'call-1', 'completed')
    store.oauth_dispatch('alice', job.run_id, 'call-1', 'dispatching')
    with pytest.raises(PermissionError, match='clear unverified'):
        store.oauth_dispatch('alice', job.run_id, 'call-1', 'cleared')
    with pytest.raises(PermissionError, match='already dispatched'):
        store.oauth_dispatch('alice', job.run_id, 'call-1', 'dispatching')
    store.oauth_dispatch('alice', job.run_id, 'call-1', 'completed')
    with pytest.raises(PermissionError, match='dispatch record'):
        store.oauth_dispatch('alice', job.run_id, 'call-1', 'completed')
    store.append('alice', job.run_id, {'event': 'on_run_step_completed', 'data': {'result': {
        'tool_call': {'id': 'call-1', 'name': 'mcp_tool_call'},
    }}})
    # Durable tool evidence now authorizes idempotent completion replay.
    store.oauth_dispatch('alice', job.run_id, 'call-1', 'completed')
    store.oauth_dispatch('alice', job.run_id, 'call-1', 'cleared')
    with db.connect() as sql:
        state = json.loads(sql.execute('SELECT state FROM runs WHERE id=?', (job.run_id,)).fetchone()[0])
    assert 'oauthResume' not in state and 'resumeHistory' not in state
    assert 'partialText' not in state


def test_tool_evidence_rejects_event_spoof_and_changed_execution_arguments(current_run):
    db, store, job = current_run
    with pytest.raises(ValueError, match='completed tool evidence'):
        store.append('alice', job.run_id, {'event': 'on_message_delta', 'data': {}},
                     full_arguments={'command': 'not executed'})
    event = {'event': 'on_run_step_completed', 'data': {'result': {'tool_call': {
        'id': 'call-42', 'name': 'run_shell', 'args': {'_truncated': True},
    }}}}
    store.append('alice', job.run_id, event, full_arguments={'command': 'echo trusted'})
    store.append('alice', job.run_id, event, full_arguments={'command': 'echo trusted'})
    with pytest.raises(ValueError, match='Cannot change completed tool arguments'):
        store.append('alice', job.run_id, event, full_arguments={'command': 'echo tampered'})
    with db.connect() as sql:
        state = json.loads(sql.execute('SELECT state FROM runs WHERE id=?', (job.run_id,)).fetchone()[0])
    assert state['completedToolArguments']['call-42']['arguments']['command'] == 'echo trusted'


@pytest.mark.parametrize('saved,expected', [
    ('', [{'type': 'tool_call', 'tool_call': {'id': 'tool-1'}}]),
    ('Left', [{'type': 'text', 'text': 'Left'}, {'type': 'tool_call', 'tool_call': {'id': 'tool-1'}}]),
    ('LeftR', [{'type': 'text', 'text': 'Left'}, {'type': 'tool_call', 'tool_call': {'id': 'tool-1'}},
               {'type': 'text', 'text': 'R'}]),
])
def test_content_rewind_preserves_tool_positions_and_only_checkpointed_text(saved, expected):
    pieces = [{'type': 'text', 'text': 'Left'},
              {'type': 'tool_call', 'tool_call': {'id': 'tool-1'}},
              {'type': 'text', 'text': 'Right is provisional'}]
    generations._rewind_uncheckpointed_text(pieces, saved)
    assert pieces == expected
    with pytest.raises(ValueError, match='checkpoint text'):
        generations._rewind_uncheckpointed_text(pieces, None)
