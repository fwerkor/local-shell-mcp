"""Human interrupt crash recovery and exact-once action claims.

The source React components retry POST /api/agents/chat/resume with the same
actionId after disconnect/reload; these tests exercise SQLite concurrency and
the checkpoint handoff without introducing a parallel runtime.
"""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.approval_runtime import (
    approval_policy_decision,
    ask_user_approval_policy,
    build_approval_payload,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall


def store_and_run(tmp_path, owner="alice"):
    root = tmp_path / "sqlite"
    database = SQLiteDatabase(root)
    store = GenerationStore(database)
    generation, _ = store.begin(owner, {"text": "Review this action"})
    return root, store, generation


def question_pause(job, *, expires_at=None):
    result = {
        "actionId": "question-one", "conversationId": job.conversation_id,
        "payload": {"type": "ask_user_question", "tool_call_id": "ask-one",
                    "question": {"question": "Choose a format"}},
    }
    if expires_at is not None:
        result["expiresAt"] = expires_at
    return result


def approval_pause(job, *, expires_at=None):
    result = {
        "actionId": "approval-one", "conversationId": job.conversation_id,
        "payload": build_approval_payload([
            ModelToolCall("a", "file_read", {"path": "one"}),
            ModelToolCall("b", "file_write", {"path": "two", "content": "new"}),
        ]),
    }
    if expires_at is not None:
        result["expiresAt"] = expires_at
    return result


def test_question_answer_persisted_across_crash_and_duplicate_retry(tmp_path):
    root, store, job = store_and_run(tmp_path)
    pause = question_pause(job)
    assert store.pause_for_question("alice", job.run_id, pause, [{"role": "user", "content": "choose"}], "partial")
    accepted, history, prior = store.answer_question("alice", job.run_id, pause["actionId"],
                                                     {"answer": "markdown"})
    assert accepted.run_id == job.run_id and prior == "partial"
    assert json.loads(history[-1]["content"]) == {"answer": "markdown"}
    reloaded = GenerationStore(SQLiteDatabase(root))
    assert reloaded.resume_claim("bob", job.run_id) is None
    assert reloaded.recover_claimed_resumes() == 1
    assert reloaded.recover_claimed_resumes() == 0
    assert reloaded.recover_orphans() == 0
    assert reloaded.pending_action("alice", job.run_id) == pause
    assert reloaded.latest("alice", job.conversation_id).status == "requires_action"
    with pytest.raises(KeyError):
        reloaded.restart_claimed_resume("bob", job.run_id, pause["actionId"], {"answer": "markdown"})
    with pytest.raises(ValueError, match="Conflicting"):
        reloaded.restart_claimed_resume("alice", job.run_id, pause["actionId"], {"answer": "json"})
    with pytest.raises(ValueError, match="Stale"):
        reloaded.restart_claimed_resume("alice", job.run_id, "other-action", {"answer": "markdown"})
    resumed, recovered_history, text, batch, namespace = reloaded.restart_claimed_resume(
        "alice", job.run_id, pause["actionId"], {"answer": "markdown"})
    assert resumed.run_id == job.run_id and resumed.status == "running"
    assert recovered_history == history and text == "partial"
    assert batch is None and namespace == ""
    repeated, repeated_history, *_ = reloaded.restart_claimed_resume(
        "alice", job.run_id, pause["actionId"], {"answer": "markdown"})
    assert repeated.run_id == job.run_id and repeated_history == history
    assert sum(item.get("tool_call_id") == "ask-one" for item in repeated_history) == 1
    assert reloaded.finish("alice", job.run_id, status="complete", text="done")
    with pytest.raises(KeyError):
        reloaded.restart_claimed_resume("alice", job.run_id, pause["actionId"], {"answer": "markdown"})


def test_approval_decisions_fenced_across_crash_and_concurrent_retries(tmp_path):
    root, store, job = store_and_run(tmp_path)
    pause = approval_pause(job)
    assert store.pause_for_approval("alice", job.run_id, pause, [], "")
    submitted = {"decisions": [
        {"tool_call_id": "b", "decision": "reject"},
        {"tool_call_id": "a", "decision": "edit", "editedArguments": {"path": "alternative"}},
    ]}
    store.claim_approval("alice", job.run_id, pause["actionId"], submitted["decisions"])
    reopened = GenerationStore(SQLiteDatabase(root))
    assert reopened.recover_claimed_resumes() == 1
    assert reopened.pending_action("alice", job.run_id) == pause
    with pytest.raises(ValueError, match="Conflicting"):
        reopened.restart_claimed_resume("alice", job.run_id, pause["actionId"], {
            "decisions": [{"tool_call_id": "a", "decision": "approve"},
                          {"tool_call_id": "b", "decision": "reject"}],
        })
    def retry(_):
        resumed, _, _, batch, _ = reopened.restart_claimed_resume(
            "alice", job.run_id, pause["actionId"], submitted)
        return resumed.run_id, batch.entries[0].tool_call().arguments
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(retry, range(12)))
    assert all(run_id == job.run_id and args == {"path": "alternative"}
               for run_id, args in results)
    assert reopened.pending_action("alice", job.run_id) is None
    assert reopened.approved_review("alice", job.run_id)["actionId"] == pause["actionId"]


@pytest.mark.parametrize("kind", ["question", "approval"])
def test_expired_action_never_accepts_decision(tmp_path, kind):
    _, store, job = store_and_run(tmp_path)
    pause = question_pause(job, expires_at=1) if kind == "question" else approval_pause(job, expires_at=1)
    assert store.pause_for_question("alice", job.run_id, pause, [], "")
    with pytest.raises(ValueError, match="expired"):
        if kind == "question":
            store.answer_question("alice", job.run_id, pause["actionId"], {"answer": "text"})
        else:
            store.claim_approval("alice", job.run_id, pause["actionId"], [
                {"tool_call_id": "a", "decision": "approve"},
                {"tool_call_id": "b", "decision": "approve"},
            ])
    assert store.pending_action("alice", job.run_id) == pause
    assert not store.finish("alice", job.run_id, status="interrupted", expired_action_id="wrong")
    assert store.finish("alice", job.run_id, status="interrupted",
                        error="Human action expired", expired_action_id=pause["actionId"])
    assert store.events("alice", job.run_id)[-1][1]["final"]
    assert store.pending_action("alice", job.run_id) is None


def test_exempt_ask_user_from_default_approval_but_respect_explicit_policy():
    source_cases = [
        ({"enabled": True}, "allow"),
        ({"enabled": True, "mode": "dontAsk"}, "allow"),
        ({"enabled": True, "ask": ["ask_user_question"]}, "ask"),
        ({"enabled": True, "deny": ["ask_user_question"]}, "deny"),
        ({"enabled": True, "allow": ["ask_user_question"]}, "allow"),
    ]
    for policy, expected in source_cases:
        result = approval_policy_decision(ask_user_approval_policy(policy), "ask_user_question")
        assert result["decision"] == expected
    assert ask_user_approval_policy(None) is None



def test_source_client_pending_projection_hides_server_replay_secrets(tmp_path):
    _, store, generation = store_and_run(tmp_path)
    pending = question_pause(generation)
    pending.update({
        "requestFingerprint": "private-legacy",
        "requestFingerprintV2": "private-v2",
        "resumeContext": {"provider_token": "secret"},
        "codeExecutionBinding": {"token": "secret"},
        "interruptId": "safe-identity",
    })
    assert store.pause_for_question("alice", generation.run_id, pending, [], "")
    assert store.pending_action("alice", generation.run_id) == pending
    snapshot, _ = store.resume_snapshot("alice", generation.run_id)
    visible = snapshot["pendingAction"]
    for private_key in ("requestFingerprint", "requestFingerprintV2",
                        "resumeContext", "codeExecutionBinding"):
        assert private_key not in visible
    assert visible["interruptId"] == "safe-identity"
    event = store.events("alice", generation.run_id)[-1][1]
    assert event["data"] == visible

@pytest.mark.parametrize("cleanup", ["checkpoint", "oauth_dispatch"])
def test_oauth_cleanup_retains_claimed_approval_resume_history(tmp_path, cleanup):
    root, store, run = store_and_run(tmp_path)
    db = store.database
    pending = approval_pause(run)
    history = [{"role": "user", "content": "Authorize a reviewed action"}]
    decisions = [{"tool_call_id": "a", "decision": "approve"},
                 {"tool_call_id": "b", "decision": "reject"}]
    assert store.pause_for_approval("alice", run.run_id, pending, history, "pre-OAuth text")
    store.claim_approval("alice", run.run_id, pending["actionId"], decisions)
    with db.connect() as conn:
        saved = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (run.run_id,)).fetchone()["state"])
        saved["oauthResume"] = {"tool_call_id": "a", "stage": "completed"}
        conn.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(saved), run.run_id))
    if cleanup == "checkpoint":
        assert store.clear_oauth_checkpoint("alice", run.run_id)
    else:
        store.oauth_dispatch("alice", run.run_id, "a", "cleared")
    reopened = GenerationStore(SQLiteDatabase(root))
    assert reopened.recover_claimed_resumes() == 1
    _, replay, partial, batch, namespace = reopened.restart_claimed_resume(
        "alice", run.run_id, pending["actionId"], {"decisions": decisions})
    assert replay == history and partial == "pre-OAuth text"
    assert batch is not None and namespace == ""


def test_claimed_approval_replays_completed_oauth_result_without_second_dispatch(tmp_path):
    root, store, run = store_and_run(tmp_path)
    pending = approval_pause(run)
    decision = [{'tool_call_id': 'a', 'decision': 'approve'},
                {'tool_call_id': 'b', 'decision': 'reject'}]
    assert store.pause_for_approval('alice', run.run_id, pending, [], '')
    store.claim_approval('alice', run.run_id, pending['actionId'], decision)
    db = store.database
    with db.connect() as conn:
        saved = json.loads(conn.execute('SELECT state FROM runs WHERE id=?',
                                        (run.run_id,)).fetchone()['state'])
        saved['oauthResume'] = {'stage': 'completed', 'tool_call_id': 'a',
                                'action_id': 'action-a', 'action_version': 1}
        conn.execute('UPDATE runs SET state=? WHERE id=?', (json.dumps(saved), run.run_id))
    with pytest.raises(PermissionError, match='no dispatch record'):
        store.oauth_dispatch('alice', run.run_id, 'a', 'completed')
    store.append('alice', run.run_id, {'event': 'on_run_step_completed', 'data': {
        'result': {'id': 'tool-a', 'type': 'tool_call',
                   'tool_call': {'id': 'a', 'name': 'oauth_action', 'output': 'cached success'}}}})
    reopened = GenerationStore(SQLiteDatabase(root))
    assert reopened.recover_claimed_resumes() == 1
    reopened.restart_claimed_resume('alice', run.run_id, pending['actionId'], {'decisions': decision})
    # Replayed cached ToolNode completion is idempotent and cannot reopen HTTP.
    reopened.oauth_dispatch('alice', run.run_id, 'a', 'completed')
    with pytest.raises(PermissionError, match='already dispatched'):
        reopened.oauth_dispatch('alice', run.run_id, 'a', 'dispatching')
    assert reopened.clear_oauth_checkpoint('alice', run.run_id)


def test_resume_snapshot_replayed_tool_completion_updates_same_step_slot(tmp_path):
    _, store, run = store_and_run(tmp_path)
    original = {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'step-one', 'type': 'tool_call',
        'tool_call': {'id': 'call-one', 'name': 'file_read', 'args': {}, 'output': 'old result'}}}}
    store.append('alice', run.run_id, original)
    store.append('alice', run.run_id, {'event': 'on_steer_applied', 'data': {
        'part': {'type': 'steer', 'steerId': 'steer-one', 'steer': 'Explain now'}}})
    replay = json.loads(json.dumps(original))
    replay['data']['result']['tool_call']['output'] = 'new cached presentation'
    store.append('alice', run.run_id, replay)
    snapshot, _ = store.resume_snapshot('alice', run.run_id)
    slots = snapshot['aggregatedContent']
    assert len([slot for slot in slots if slot.get('type') == 'tool_call']) == 1
    assert slots[0]['tool_call']['stepId'] == 'step-one'
    assert slots[0]['tool_call']['output'] == 'new cached presentation'
    assert slots[1]['type'] == 'steer'


def test_recover_human_claim_removes_abandoned_stream_text_before_new_continuation(tmp_path):
    root, store, job = store_and_run(tmp_path)
    # Only the first text segment was checkpointed at the human boundary.
    store.append('alice', job.run_id, {'event': 'on_message_delta',
        'data': {'delta': {'content': {'type': 'text', 'text': 'Confirmed prefix. '}}}})
    pause = question_pause(job)
    assert store.pause_for_question('alice', job.run_id, pause, [], 'Confirmed prefix. ')
    store.answer_question('alice', job.run_id, pause['actionId'], {'answer': 'markdown'})
    store.append('alice', job.run_id, {'event': 'on_message_delta',
        'data': {'delta': {'content': {'type': 'text', 'text': 'Abandoned uncheckpointed text.'}}}})
    restarted = GenerationStore(SQLiteDatabase(root))
    assert restarted.recover_claimed_resumes() == 1
    snapshot, _ = restarted.resume_snapshot('alice', job.run_id)
    assert ''.join(p['text'] for p in snapshot['aggregatedContent'] if p['type'] == 'text') == 'Confirmed prefix. '
    restarted.restart_claimed_resume('alice', job.run_id, pause['actionId'], {'answer': 'markdown'})
    restarted.append('alice', job.run_id, {'event': 'on_message_delta',
        'data': {'delta': {'content': {'type': 'text', 'text': 'Recovered continuation.'}}}})
    assert restarted.finish('alice', job.run_id, status='complete',
                             text='Confirmed prefix. Recovered continuation.')
    terminal = restarted.events('alice', job.run_id)[-1][1]['responseMessage']
    assert ''.join(p['text'] for p in terminal['content'] if p['type'] == 'text') == (
        'Confirmed prefix. Recovered continuation.')
    assert 'Abandoned' not in json.dumps(terminal)


def test_crashed_human_resume_rewind_retains_newer_confirmed_checkpoint_text(tmp_path):
    from local_shell_mcp.webui.checkpoints import SQLiteCheckpointSaver

    root, store, job = store_and_run(tmp_path)
    store.append('alice', job.run_id, {'event': 'on_message_delta',
        'data': {'delta': {'content': {'type': 'text', 'text': 'Before question. '}}}})
    pause = question_pause(job)
    assert store.pause_for_question('alice', job.run_id, pause, [], 'Before question. ')
    store.answer_question('alice', job.run_id, pause['actionId'], {'answer': 'markdown'})
    store.append('alice', job.run_id, {'event': 'on_message_delta',
        'data': {'delta': {'content': {'type': 'text', 'text': 'Committed next turn. '}}}})
    saver = SQLiteCheckpointSaver(store.database, 'alice')
    saver.put(saver.config(job.conversation_id, job.run_id, event_actor=True),
              {'v': 1, 'id': '0000000000000001',
               'channel_values': {'partial_text': 'Before question. Committed next turn.'},
               'channel_versions': {}, 'versions_seen': {}},
              {'source': 'loop', 'step': 1})
    store.append('alice', job.run_id, {'event': 'on_message_delta',
        'data': {'delta': {'content': {'type': 'text', 'text': ' Abandoned partial.'}}}})
    reopened = GenerationStore(SQLiteDatabase(root))
    assert reopened.recover_claimed_resumes() == 1
    snapshot, _ = reopened.resume_snapshot('alice', job.run_id)
    assert ''.join(p['text'] for p in snapshot['aggregatedContent'] if p['type'] == 'text') == (
        'Before question. Committed next turn.')
    reopened.restart_claimed_resume('alice', job.run_id, pause['actionId'], {'answer': 'markdown'})
    reopened.append('alice', job.run_id, {'event': 'on_message_delta',
        'data': {'delta': {'content': {'type': 'text', 'text': ' Final answer.'}}}})
    assert reopened.finish('alice', job.run_id, status='complete',
        text='Before question. Committed next turn. Final answer.')
    result = reopened.events('alice', job.run_id)[-1][1]['responseMessage']
    assert ''.join(p['text'] for p in result['content'] if p['type'] == 'text') == (
        'Before question. Committed next turn. Final answer.')
