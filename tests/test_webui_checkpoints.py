"""Real SQLite checkpoint/restart behavior and original saver differential probes."""

import concurrent.futures
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.checkpoints import (
    EVENT_ACTOR_KEY,
    NAMESPACE_KEY,
    OWNER_KEY,
    CheckpointTooLargeError,
    SQLiteCheckpointSaver,
    has_resumable_write,
)


@pytest.fixture
def saver(tmp_path):
    return SQLiteCheckpointSaver(SQLiteDatabase(tmp_path), "alice")


def checkpoint(identity, **values):
    return {"v": 1, "id": identity, "channel_values": values,
            "channel_versions": {"messages": 1}, "versions_seen": {"tools": {"messages": 1}}}


def test_original_resumable_anchor_and_namespace_functions_match_node(saver):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for the original-source oracle")
    fixture = Path(__file__).parent / "fixtures/librechat/checkpoint_reference.cjs"
    channels = ["messages", "routing", "__interrupt__", "__no_writes__", "__error__", "__resume__", "__scheduled__"]
    cases = [[(channel, {"id": "interrupt-1"}) for channel in group]
             for size in range(3) for group in itertools.product(channels, repeat=size)]
    configs = [saver.config("thread", "generation", checkpoint_ns=ns)
               for ns in ["", "subgraph:task", "tools:agent"]]
    script = """
const fs=require('fs');const r=require(process.argv[1]);const d=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify({anchors:d.cases.map(x=>r.hasResumableWrite(x)),
 configs:d.configs.map(x=>{const stored=r.toStorageCheckpointConfig(x);return [stored,
 r.fromStorageCheckpointConfig(stored,x)];})}));
"""
    expected = json.loads(subprocess.check_output([node, "-e", script, str(fixture.resolve())],
                         input=json.dumps({"cases": cases, "configs": configs}).encode()))
    assert [has_resumable_write(writes) for writes in cases] == expected["anchors"]
    for original, (stored, restored) in zip(configs, expected["configs"], strict=True):
        assert saver._identity(original)[1] == stored["configurable"]["checkpoint_ns"]
        assert restored == original


def test_interrupt_preserves_completed_siblings_after_process_restart(tmp_path):
    db = SQLiteDatabase(tmp_path)
    saver = SQLiteCheckpointSaver(db, "alice")
    config = saver.config("conversation", "generation", checkpoint_id="0001")
    saver.put_writes(config, [("__no_writes__", None)], "completed-sibling")
    assert saver.get_tuple(config) is None
    saver.put_writes(config, [("__interrupt__", [{"id": "question"}])], "paused-sibling")
    saver.put(saver.config("conversation", "generation"), checkpoint("0001", messages=["proposal"]), {"step": 1})
    recovered = SQLiteCheckpointSaver(SQLiteDatabase(tmp_path), "alice")
    result = recovered.get_tuple(config)
    assert result["checkpoint"]["channel_values"] == {"messages": ["proposal"]}
    assert result["pendingWrites"] == [("completed-sibling", "__no_writes__", None),
                                      ("paused-sibling", "__interrupt__", [{"id": "question"}])]
    assert recovered.has_durable_interrupt(config, "question")
    assert not recovered.has_durable_interrupt(config, "other")
    assert not recovered.has_durable_interrupt(config, "")
    assert not recovered.has_durable_interrupt(recovered.config("conversation", "generation"), "question")
    assert not recovered.has_durable_interrupt(recovered.config("conversation", "other", checkpoint_id="0001"), "question")


def test_completed_tool_result_slots_are_first_write_wins_and_actor_proposal_is_durable(saver):
    base = saver.config("conversation", "run", event_actor=True)
    stored = saver.put(base, checkpoint("0001", messages=[{"tool_calls": [{"id": "call1"}]}]), {"source": "loop"})
    saver.put_writes(stored, [("messages", {"tool_call_id": "call1", "content": "original result"})], "call1")
    saver.put_writes(stored, [("messages", {"tool_call_id": "call1", "content": "replacement"})], "call1")
    assert saver.get_tuple(stored)["pendingWrites"][0][2]["content"] == "original result"
    saver.put_writes(stored, [("__resume__", "first")], "resume")
    saver.put_writes(stored, [("__resume__", "new")], "resume")
    assert saver.get_tuple(stored)["pendingWrites"][-1] == ("resume", "__resume__", "new")
    # A mixed batch retains every slot on retry, including its special slot.
    saver.put_writes(stored, [("messages", "first"), ("__error__", "first")], "mixed")
    saver.put_writes(stored, [("messages", "second"), ("__error__", "second")], "mixed")
    assert [value for task, _, value in saver.get_tuple(stored)["pendingWrites"] if task == "mixed"] == ["first", "first"]


def test_clean_exit_and_error_only_exit_leave_no_checkpoint_or_orphan_writes(saver):
    config = saver.config("conversation", "run", checkpoint_id="0001")
    saver.put_writes(config, [("__error__", "failure")], "task")
    assert saver.put(saver.config("conversation", "run"), checkpoint("0001"), {})["configurable"]["checkpoint_id"] == "0001"
    assert saver.get_tuple(config) is None
    with saver.database.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_checkpoint_writes").fetchone()[0] == 0
    saver.put(saver.config("conversation", "run"), checkpoint("0002"), {})
    assert list(saver.list(saver.config("conversation", "run"))) == []


def test_owner_generation_nested_namespaces_parent_chain_and_cleanup(saver):
    db = saver.database
    other = SQLiteCheckpointSaver(db, "bob")
    base = saver.config("thread", "generation", event_actor=True)
    first = saver.put(base, checkpoint("0001"), {"step": 1})
    second = saver.put(first, checkpoint("0002"), {"step": 2})
    assert saver.get_tuple(second)["parentConfig"]["configurable"]["checkpoint_id"] == "0001"
    assert saver.get_tuple(base)["checkpoint"]["id"] == "0002"
    assert list(saver.list(base, before=second))[0]["checkpoint"]["id"] == "0001"
    assert list(saver.list(base, limit=1))[0]["checkpoint"]["id"] == "0002"
    assert list(saver.list(base, limit=0)) == []
    assert list(saver.list(base, filter={"step": 1}))[0]["checkpoint"]["id"] == "0001"
    assert other.get_tuple(other.config("thread", "generation")) is None
    with pytest.raises(PermissionError):
        other.get_tuple(base)
    for owner, generation, namespace in [(saver, "generation", "tools:child"),
                                          (saver, "generation-next", ""), (other, "generation", "")]:
        owner.put(owner.config("thread", generation, checkpoint_ns=namespace, event_actor=True), checkpoint("0003"), {})
    assert saver.delete_generation(base) == 3
    assert saver.get_tuple(base) is None
    assert saver.get_tuple(saver.config("thread", "generation-next")) is not None
    assert other.get_tuple(other.config("thread", "generation")) is not None


def test_transaction_rollback_and_racing_result_writes(tmp_path):
    saver = SQLiteCheckpointSaver(SQLiteDatabase(tmp_path), "alice")
    base = saver.config("thread", "run", event_actor=True)
    current = saver.put(base, checkpoint("0001"), {})
    with pytest.raises(TypeError):
        saver.put_writes(current, [("messages", "would be partial"), ("routing", object())], "bad")
    assert saver.get_tuple(current)["pendingWrites"] == []
    def write(value):
        worker = SQLiteCheckpointSaver(SQLiteDatabase(tmp_path), "alice")
        worker.put_writes(current, [("messages", value)], "same-task")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(12)))
    assert len(saver.get_tuple(current)["pendingWrites"]) == 1
    assert saver.get_tuple(current)["pendingWrites"][0][2] in range(12)


def test_size_limits_expiry_and_input_validation(saver, monkeypatch, caplog):
    base = saver.config("thread", "run", event_actor=True)
    small = SQLiteCheckpointSaver(saver.database, "alice", hard_limit_bytes=400, warn_bytes=10)
    with caplog.at_level("WARNING"):
        current = small.put(base, checkpoint("0001"), {})
    assert "soft size threshold" in caplog.text
    with pytest.raises(CheckpointTooLargeError) as error:
        small.put(base, checkpoint("0002", messages="x" * 500), {})
    assert error.value.code == "CHECKPOINT_TOO_LARGE" and error.value.bytes > error.value.limit
    assert small.get_tuple(small.config("thread", "run", checkpoint_id="0002")) is None
    monkeypatch.setattr("local_shell_mcp.webui.checkpoints.time.time", lambda: 10**15)
    assert small.get_tuple(current) is None
    assert small.prune_expired() == 1
    with pytest.raises(ValueError):
        SQLiteCheckpointSaver(saver.database, "")
    with pytest.raises(ValueError):
        SQLiteCheckpointSaver(saver.database, "alice", ttl_seconds=0)
    for field, value in [("thread_id", 3), ("checkpoint_ns", 3), (NAMESPACE_KEY, ""), ("checkpoint_id", 3)]:
        invalid = {"configurable": {**base["configurable"], field: value}}
        with pytest.raises(ValueError):
            saver.get_tuple(invalid)
    with pytest.raises(ValueError):
        saver.put(base, {}, {})
    with pytest.raises(ValueError):
        saver.put_writes(base, [("messages", "value")], "task")
    with pytest.raises(ValueError):
        saver.put_writes(current, [("messages", "value")], "")
    with pytest.raises(ValueError):
        saver.put_writes(current, [(1, "value")], "task")
    for args in [{"limit": -1}, {"limit": True}, {"filter": {"field": {}}}, {"before": base}]:
        with pytest.raises(ValueError):
            list(saver.list(base, **args))
    assert OWNER_KEY in base["configurable"] and EVENT_ACTOR_KEY in base["configurable"]
