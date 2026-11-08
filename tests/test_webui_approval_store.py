"""Atomic batch approval claims retain review evidence across a Controller crash."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.approval_runtime import build_approval_payload
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall


@pytest.fixture
def paused_batch(tmp_path):
    database = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    store = GenerationStore(database)
    generation, _ = store.begin("alice", {"text": "Do two things"})
    calls = [ModelToolCall("a", "file_read", {"path": "one.txt"}),
             ModelToolCall("b", "file_write", {"path": "two.txt", "content": "two"})]
    pending = {"actionId": "batch-1", "payload": build_approval_payload(calls)}
    history = [{"role": "assistant", "content": None, "tool_calls": [
        {"id": call.call_id, "type": "function", "function": {
            "name": call.name, "arguments": json.dumps(call.arguments)}} for call in calls]}]
    assert store.pause_for_approval("alice", generation.run_id, pending, history, "partial")
    return database, store, generation, pending, history


def test_batch_claim_is_atomic_and_retains_snapshot_after_reopen(paused_batch):
    database, store, generation, pending, history = paused_batch
    invalid = [{"tool_call_id": "a", "decision": "approve"},
               {"tool_call_id": "b", "decision": "edit", "editedArguments": []}]
    with pytest.raises(ValueError, match="edit requires"):
        store.claim_approval("alice", generation.run_id, "batch-1", invalid)
    assert store.latest("alice", generation.conversation_id).status == "requires_action"
    assert store.pending_action("alice", generation.run_id) == pending
    assert store.approved_review("alice", generation.run_id) is None
    decisions = [{"tool_call_id": "b", "decision": "edit", "editedArguments": {"path": "edited.txt", "content": "edited"}},
                 {"tool_call_id": "a", "decision": "approve"}]
    resumed, saved_history, partial, batch = store.claim_approval("alice", generation.run_id, "batch-1", decisions)
    assert resumed.status == "running"
    assert saved_history == history and partial == "partial"
    assert [entry.call_id for entry in batch.entries] == ["a", "b"]
    assert store.pending_action("alice", generation.run_id) is None
    decisions[0]["editedArguments"]["path"] = "changed-by-caller"
    reopened = GenerationStore(SQLiteDatabase(database.root))
    review = reopened.approved_review("alice", generation.run_id)
    assert review["actionId"] == "batch-1" and review["payload"] == pending["payload"]
    recovered = reopened.approved_batch("alice", generation.run_id)
    assert recovered.entries[1].tool_call().arguments["path"] == "edited.txt"
    assert reopened.approved_review("bob", generation.run_id) is None
    assert reopened.approved_batch("bob", generation.run_id) is None
    assert reopened.recover_orphans() == 1
    assert reopened.approved_batch("alice", generation.run_id) == recovered


def test_only_one_concurrent_resume_can_claim_the_batch(paused_batch):
    _, store, generation, _, _ = paused_batch
    decisions = [{"tool_call_id": call_id, "decision": "approve"} for call_id in ["a", "b"]]
    def claim():
        try:
            store.claim_approval("alice", generation.run_id, "batch-1", decisions)
            return True
        except KeyError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == [False, True]


def test_completion_saves_full_continuation_and_retires_review_once(paused_batch):
    database, store, generation, _, history = paused_batch
    store.claim_approval("alice", generation.run_id, "batch-1", [
        {"tool_call_id": call_id, "decision": "reject"} for call_id in ["a", "b"]])
    finished = history + [{"role": "tool", "tool_call_id": "a", "content": "Blocked: Rejected by user"},
                          {"role": "tool", "tool_call_id": "b", "content": "Blocked: Rejected by user"}]
    assert not store.complete_approval_batch("bob", generation.run_id, "batch-1", finished, "partial")
    assert not store.complete_approval_batch("alice", generation.run_id, "other", finished, "partial")
    with pytest.raises(ValueError, match="too large"):
        store.complete_approval_batch("alice", generation.run_id, "batch-1", [{"content": "x" * 530000}], "")
    assert store.approved_batch("alice", generation.run_id) is not None
    assert store.complete_approval_batch("alice", generation.run_id, "batch-1", finished, "after batch")
    assert not store.complete_approval_batch("alice", generation.run_id, "batch-1", finished, "after batch")
    assert store.approved_batch("alice", generation.run_id) is None
    with database.connect() as connection:
        state = json.loads(connection.execute("SELECT state FROM runs WHERE id=?", (generation.run_id,)).fetchone()[0])
    assert state["resumeHistory"] == finished
    assert state["partialText"] == "after batch"


@pytest.mark.parametrize("bad_review", [[], {"actionId": ""}, {"actionId": "batch-1", "payload": {}, "resolutions": []}])
def test_corrupt_review_is_not_silently_replayed(paused_batch, bad_review):
    database, store, generation, _, _ = paused_batch
    store.claim_approval("alice", generation.run_id, "batch-1", [
        {"tool_call_id": call_id, "decision": "approve"} for call_id in ["a", "b"]])
    with database.connect() as connection:
        state = json.loads(connection.execute("SELECT state FROM runs WHERE id=?", (generation.run_id,)).fetchone()[0])
        state["approvedToolBatch"] = bad_review
        connection.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), generation.run_id))
    with pytest.raises(ValueError):
        store.approved_batch("alice", generation.run_id)
