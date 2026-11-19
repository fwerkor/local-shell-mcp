"""Source-pinned durable subagent completion wakeup integration tests."""
from __future__ import annotations

import json
import time

import pytest
from wakeup_helpers import completed, make_task, wait_admission
from wakeup_helpers import environment as environment

from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks
from local_shell_mcp.webui.subagent_wakeup import process_wakeups


@pytest.mark.parametrize("condition,expected", [
    ("child_cancelled", "retired"),
    ("already_claimed", "retired"),
    ("expired_grant", "retired"),
    ("parent_aborted", "retired"),
    ("bad_target", "retired"),
    ("agent_removed", "retired"),
    ("missing_reply", "retired"),
    ("scope_revoked", "retired"),
    ("provider_unavailable", "retired"),
    ("parent_paused", "pending"),
])
@pytest.mark.asyncio
async def test_auto_wakeup_fail_closed_without_claiming_unrelated_result(environment, monkeypatch,
                                                                        condition, expected):
    from local_shell_mcp.webui import providers

    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    if condition == "parent_aborted":
        store.finish("local", parent_run.run_id, status="aborted")
    elif condition == "parent_paused":
        with db.connect() as conn:
            conn.execute("UPDATE runs SET status='requires_action' WHERE id=?", (parent_run.run_id,))
    else:
        store.finish("local", parent_run.run_id, status="complete", text="Parent finished")
    with db.connect() as conn:
        if condition == "child_cancelled":
            conn.execute("UPDATE subagent_tasks SET status='cancelled' WHERE id=?", (task_id,))
        elif condition == "already_claimed":
            conn.execute("UPDATE subagent_tasks SET result_claimed=1 WHERE id=?", (task_id,))
        elif condition == "expired_grant":
            conn.execute("UPDATE subagent_tasks SET grant_expires=? WHERE id=?", (time.time() - 1, task_id))
        elif condition == "bad_target":
            row = conn.execute("SELECT envelope FROM subagent_wakeups WHERE task_id=?", (task_id,)).fetchone()
            envelope = json.loads(row["envelope"])
            envelope["target"]["parentMessageId"] = "untrusted-parent-reply"
            conn.execute("UPDATE subagent_wakeups SET envelope=? WHERE task_id=?",
                         (json.dumps(envelope), task_id))
        elif condition == "agent_removed":
            conn.execute("DELETE FROM agents WHERE id=?", (parent["id"],))
        elif condition == "missing_reply":
            conn.execute("DELETE FROM messages WHERE id=?", (parent_run.response_message_id,))
        elif condition == "scope_revoked":
            conn.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?)",
                         ("local", "agent.machine_policy.global", '{"local":"write"}'))
    if condition == "provider_unavailable":
        monkeypatch.setattr(providers, "provider_config", lambda *args: (_ for _ in ()).throw(
            ValueError("No usable model provider")))
    await wait_admission()
    assert await process_wakeups(db, dispatch=lambda *args, **kwargs: None) == 0
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?", (task_id,)).fetchone()
        assert row["status"] == expected
        assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?",
                            (parent_run.conversation_id,)).fetchone()[0] == 1
        if condition != "already_claimed":
            assert conn.execute("SELECT result_claimed FROM subagent_tasks WHERE id=?",
                                (task_id,)).fetchone()[0] == 0
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_source_wakeup_uses_latest_persisted_assistant_descendant(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Initial parent result")
    later, _ = store.begin("local", {"conversationId": parent_run.conversation_id,
                                     "parentMessageId": parent_run.response_message_id,
                                     "text": "Another question"}, parent)
    store.finish("local", later.run_id, status="complete", text="Most recent assistant reply")
    await wait_admission()
    seen = []

    async def dispatch(owner, generation, profile, agent, **kwargs):
        seen.append(generation)

    assert await process_wakeups(db, dispatch=dispatch) == 1
    with db.connect() as conn:
        reply = conn.execute("SELECT parent_id FROM messages WHERE id=?",
                             (seen[0].user_message_id,)).fetchone()
        assert reply["parent_id"] == later.response_message_id
    await shutdown_subagent_tasks()




@pytest.mark.parametrize("mutation", [
    "deleted_child", "changed_owner_lineage", "malformed_lineage", "pending_child_finish",
])
@pytest.mark.asyncio
async def test_missing_or_incomplete_child_transcript_cannot_trigger_parent(environment, mutation):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    child_record = await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent complete")
    with db.connect() as conn:
        if mutation == "deleted_child":
            conn.execute("DELETE FROM conversations WHERE id=?",
                         (child_record["child_conversation_id"],))
        elif mutation == "changed_owner_lineage":
            conn.execute("UPDATE conversations SET metadata=? WHERE id=?",
                         ('{"subagentTask":"untrusted","parentConversationId":"foreign"}',
                          child_record["child_conversation_id"]))
        elif mutation == "malformed_lineage":
            conn.execute("UPDATE conversations SET metadata=? WHERE id=?",
                         ('not-json', child_record["child_conversation_id"]))
        else:
            conn.execute("UPDATE runs SET status='running' WHERE id=?",
                         (child_record["child_run_id"],))
    await wait_admission()
    assert await process_wakeups(db, dispatch=lambda *args, **kwargs: None) == 0
    with db.connect() as conn:
        state = conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                             (task_id,)).fetchone()[0]
        assert state == ("pending" if mutation == "pending_child_finish" else "retired")
        assert conn.execute("SELECT result_claimed FROM subagent_tasks WHERE id=?",
                            (task_id,)).fetchone()[0] == 0
    await shutdown_subagent_tasks()
