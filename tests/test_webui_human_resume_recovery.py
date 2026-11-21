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
