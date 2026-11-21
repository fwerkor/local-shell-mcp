"""Source-pinned durable subagent completion wakeup integration tests."""
from __future__ import annotations

import asyncio
import json

import pytest
from wakeup_helpers import completed, make_task, wait_admission
from wakeup_helpers import environment as environment

from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks
from local_shell_mcp.webui.subagent_wakeup import process_wakeups


@pytest.mark.asyncio
async def test_source_event_pre_registered_and_parent_waits_then_auto_dispatches(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, gate = await make_task(environment)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM subagent_wakeups WHERE task_id=?", (task_id,)).fetchone()
        envelope = json.loads(row["envelope"])
        assert row["status"] == "pending"
        assert envelope["mode"] == "continue" and envelope["deliveryId"] == task_id
        assert envelope["event"]["source"] == {"id": "subagent-completion", "type": "internal"}
        assert envelope["target"] == {"agentId": parent["id"],
                                       "conversationId": parent_run.conversation_id,
                                       "parentMessageId": parent_run.response_message_id}
    await completed(host, task_id)
    dispatched = []

    async def dispatch(owner, generation, profile, agent, **kwargs):
        dispatched.append((owner, generation, profile, agent, kwargs))

    await wait_admission()
    assert await process_wakeups(db, dispatch=dispatch) == 0  # parent still running
    store.finish("local", parent_run.run_id, status="complete", text="I delegated research")
    assert await process_wakeups(db, dispatch=dispatch) == 1
    assert len(dispatched) == 1
    owner, wakeup, profile, agent, kw = dispatched[0]
    assert owner == "local" and agent["id"] == parent["id"]
    assert kw["granted_scopes"] == frozenset()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM subagent_wakeups WHERE task_id=?", (task_id,)).fetchone()
        assert row["status"] == "dispatched" and row["run_id"] == wakeup.run_id
        claimed = conn.execute("SELECT result_claimed,result_claim_key FROM subagent_tasks WHERE id=?",
                               (task_id,)).fetchone()
        assert claimed["result_claimed"] == 1 and claimed["result_claim_key"] == "wakeup:" + task_id
        prompt = conn.execute("SELECT text,parent_id FROM messages WHERE id=?",
                              (wakeup.user_message_id,)).fetchone()
        assert prompt["parent_id"] == parent_run.response_message_id
        assert "child result" in prompt["text"]
        assert "Host-authored bounded orchestration snapshot" in prompt["text"]
    assert json.loads(await host.check({"background_task_id": task_id}))["status"] == "delivery_scheduled"
    store.finish("local", wakeup.run_id, status="complete", text="responded automatically")
    with db.connect() as conn:
        conn.execute("UPDATE subagent_wakeups SET lease_until=0 WHERE task_id=?", (task_id,))
    assert await process_wakeups(db, dispatch=dispatch) == 0
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] == "done"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_manual_claim_retires_undelivered_trigger_atomically(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, gate = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="delegation complete")
    first = json.loads(await host.check({"background_task_id": task_id}))
    assert first["result"] == "child result"
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] == "retired"
    await wait_admission()
    assert await process_wakeups(db, dispatch=lambda *args, **kwargs: None) == 0
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?",
                            (parent_run.conversation_id,)).fetchone()[0] == 1
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_cancelled_task_does_not_wake_parent(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, gate = await make_task(environment, slow=True)
    assert json.loads(await host.check({"background_task_id": task_id, "action": "cancel"}))["status"] in {
        "cancelled", "cancellation_requested"}
    for _ in range(120):
        if host._get(task_id)["status"] == "cancelled":
            break
        await asyncio.sleep(.025)
    store.finish("local", parent_run.run_id, status="complete", text="delegation cancelled")
    await wait_admission()
    assert await process_wakeups(db, dispatch=lambda *args, **kwargs: None) == 0
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] == "retired"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_optional_admin_optout_skips_pre_enqueued_wakeup(environment):
    db, repo, store, child, parent, parent_run = environment
    with db.connect() as conn:
        conn.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?)",
                     ("local", "backgroundTasks.completionWakeups", "false"))
    host, task_id, gate = await make_task(environment)
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] == 0
    await completed(host, task_id)
    assert json.loads(await host.check({"background_task_id": task_id}))["result"] == "child result"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_full_wakeup_uses_real_parent_agent_runner_and_persists_sse(environment, monkeypatch):
    """No synthetic dispatch: the genuine Controller AgentRunner owns this turn."""
    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.subagent_wakeup import start_wakeup_worker

    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="I delegated research")
    observed = []

    async def model(profile, history, **kwargs):
        observed.append(history)
        yield "Parent received the automatic child completion"

    monkeypatch.setattr(generation_routes, "_database", lambda: db)
    monkeypatch.setattr(generation_routes, "stream_model", model)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    await start_wakeup_worker(db)
    latest = None
    for _ in range(240):
        latest = store.latest("local", parent_run.conversation_id)
        if latest and latest.run_id != parent_run.run_id and latest.status == "complete":
            break
        await asyncio.sleep(.04)
    assert latest is not None and latest.run_id != parent_run.run_id and latest.status == "complete"
    assert observed and any("child result" in message.get("content", "")
                            for history in observed for message in history)
    with db.connect() as conn:
        reply = conn.execute("SELECT text FROM messages WHERE id=?",
                             (latest.response_message_id,)).fetchone()
        assert reply["text"] == "Parent received the automatic child completion"
        events = [json.loads(row["data"]) for row in conn.execute(
            "SELECT data FROM generation_events WHERE run_id=? ORDER BY seq", (latest.run_id,))]
        assert any(event.get("event") == "on_run_step" for event in events)
        assert any(event.get("final") is True for event in events)
    await shutdown_subagent_tasks()
