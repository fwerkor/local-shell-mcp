"""Source-pinned durable subagent completion wakeup integration tests."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from wakeup_helpers import begin_automatic, completed, make_task, wait_admission
from wakeup_helpers import environment as environment

from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks
from local_shell_mcp.webui.subagent_wakeup import process_wakeups


@pytest.mark.parametrize("terminal,expected", [
    ("complete", "done"), ("requires_action", "done"),
    ("error", "dead"), ("aborted", "dead"), ("interrupted", "dead"),
])
@pytest.mark.asyncio
async def test_dispatched_queue_reconciles_root_terminal_and_releases_failed_claim(environment,
                                                                                   terminal, expected):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent done")
    await wait_admission()
    root = []

    async def dispatch(owner, generation, profile, agent, **kwargs):
        root.append(generation)

    assert await process_wakeups(db, dispatch=dispatch) == 1
    if terminal == "requires_action":
        with db.connect() as conn:
            conn.execute("UPDATE runs SET status='requires_action' WHERE id=?", (root[0].run_id,))
    else:
        store.finish("local", root[0].run_id, status=terminal, text="Auto delivery status")
    # Reconcile settled root without waiting for an unnecessary 30s lease expiry.
    assert await process_wakeups(db, dispatch=dispatch) == 0
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] == expected
        claim = conn.execute("SELECT result_claimed FROM subagent_tasks WHERE id=?", (task_id,)).fetchone()[0]
        assert claim == (1 if expected == "done" else 0)
    if expected == "dead":
        assert json.loads(await host.check({"background_task_id": task_id}))["result"] == "child result"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_dispatch_crash_before_start_replays_exact_same_generation(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent done")
    await wait_admission()
    seen = []

    async def broken(owner, generation, *args, **kwargs):
        seen.append(generation.run_id)
        raise RuntimeError("Crash between persisted generation and local scheduler")

    assert await process_wakeups(db, dispatch=broken) == 0
    with db.connect() as conn:
        failure = conn.execute("SELECT attempts, next_attempt_at,failure_history "
                               "FROM subagent_wakeups WHERE task_id=?", (task_id,)).fetchone()
        assert failure["attempts"] == 1
        assert failure["next_attempt_at"] > 0
        assert json.loads(failure["failure_history"])[0]["errorType"] == "RuntimeError"
    from local_shell_mcp.webui.subagent_task_host import active_child_generations

    assert seen[0] in active_child_generations(db)
    assert store.recover_orphans(active_child_generations(db)) == 0
    with db.connect() as conn:
        conn.execute("UPDATE subagent_wakeups SET lease_until=0,next_attempt_at=0 "
                     "WHERE task_id=?", (task_id,))

    async def recover(owner, generation, profile, agent, **kwargs):
        seen.append(generation.run_id)
        assert kwargs["resume_history"] is not None

    assert await process_wakeups(db, dispatch=recover) == 1
    assert seen == [seen[0], seen[0]]
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?",
                            (parent_run.conversation_id,)).fetchone()[0] == 2
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_repeated_queue_scans_do_not_duplicate_first_claim(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent done")
    await wait_admission()
    seen = []

    async def dispatch(owner, generation, profile, agent, **kwargs):
        seen.append(generation.run_id)

    attempts = await asyncio.gather(process_wakeups(db, dispatch=dispatch),
                                    process_wakeups(db, dispatch=dispatch))
    assert sum(attempts) == 1
    assert len(seen) == 1
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?",
                            (parent_run.conversation_id,)).fetchone()[0] == 2
    await shutdown_subagent_tasks()


@pytest.mark.parametrize("mutation", [
    "deleted_generation", "expired_authorization", "removed_parent_agent",
    "revoked_machine_scope", "provider_unavailable",
])
@pytest.mark.asyncio
async def test_failed_dispatched_continuation_releases_manual_result(environment, monkeypatch, mutation):
    from local_shell_mcp.webui import providers

    db, repo, store, child, parent, parent_run = environment
    host, task_id, generation = await begin_automatic(environment)
    with db.connect() as conn:
        conn.execute("UPDATE subagent_wakeups SET lease_until=0 WHERE task_id=?", (task_id,))
        if mutation == "deleted_generation":
            conn.execute("DELETE FROM runs WHERE id=?", (generation.run_id,))
        elif mutation == "expired_authorization":
            conn.execute("UPDATE subagent_tasks SET grant_expires=? WHERE id=?", (time.time() - 1, task_id))
        elif mutation == "removed_parent_agent":
            conn.execute("DELETE FROM agents WHERE id=?", (parent["id"],))
        elif mutation == "revoked_machine_scope":
            conn.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?)",
                         ("local", "agent.machine_policy.global", '{"local":"read"}'))
    if mutation == "provider_unavailable":
        monkeypatch.setattr(providers, "provider_config", lambda *args: (_ for _ in ()).throw(
            ValueError("No provider")))
    assert await process_wakeups(db, dispatch=lambda *args, **kwargs: None) == 0
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] == "dead"
    assert json.loads(await host.check({"background_task_id": task_id}))["result"] == "child result"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_queue_waits_for_other_active_generation_and_uses_later_branch(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Root")
    other, _ = store.begin("local", {"conversationId": parent_run.conversation_id,
                                     "parentMessageId": parent_run.response_message_id,
                                     "text": "One more question"}, parent)
    await wait_admission()

    async def no_run(*args, **kwargs):
        raise AssertionError("The queue must not dispatch during another active generation")

    assert await process_wakeups(db, dispatch=no_run) == 0
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] == "pending"
    store.finish("local", other.run_id, status="complete", text="Later root")
    resumed = []

    async def dispatch(owner, generation, profile, agent, **kwargs):
        resumed.append(generation)
        assert kwargs["resume_history"] is None  # fresh root emits source on_run_step

    assert await process_wakeups(db, dispatch=dispatch) == 1
    with db.connect() as conn:
        assert conn.execute("SELECT parent_id FROM messages WHERE id=?",
                            (resumed[0].user_message_id,)).fetchone()[0] == other.response_message_id
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_active_wakeup_lease_is_renewed_and_does_not_dispatch_twice(environment):
    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.subagent_wakeup import _OWNED_LEASES, _now

    db, repo, store, child, parent, parent_run = environment
    host, task_id, generation = await begin_automatic(environment)
    blocker = asyncio.create_task(asyncio.sleep(30))
    generation_routes._TASKS[generation.run_id] = blocker
    with db.connect() as conn:
        token = conn.execute("SELECT lease_owner FROM subagent_wakeups WHERE task_id=?",
                             (task_id,)).fetchone()[0]
    _OWNED_LEASES[task_id] = (generation.run_id, token)
    try:
        with db.connect() as conn:
            conn.execute("UPDATE subagent_wakeups SET lease_until=? WHERE task_id=?",
                         (_now() + 100, task_id))
        assert await process_wakeups(db) == 0
        with db.connect() as conn:
            row = conn.execute("SELECT lease_until,status FROM subagent_wakeups WHERE task_id=?",
                               (task_id,)).fetchone()
            assert row["lease_until"] >= _now() + 20_000
            assert row["status"] == "dispatched"
    finally:
        generation_routes._TASKS.pop(generation.run_id, None)
        blocker.cancel()
        await asyncio.gather(blocker, return_exceptions=True)
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_worker_is_singleton_per_sqlite_and_shutdown_cancels_loop(environment):
    from local_shell_mcp.webui.subagent_wakeup import _WORKERS, start_wakeup_worker

    db = environment[0]
    await start_wakeup_worker(db)
    current = _WORKERS[str(db.path)]
    await start_wakeup_worker(db)
    assert _WORKERS[str(db.path)] is current and not current.done()
    await shutdown_subagent_tasks()
    assert current.done() and not _WORKERS


@pytest.mark.asyncio
async def test_delegation_respects_source_optout_and_rejects_untrusted_parent_binding(environment):
    from local_shell_mcp.webui.subagent_wakeup import register_wakeup

    db, repo, store, child, parent, parent_run = environment
    with db.connect() as conn, pytest.raises(PermissionError, match="trusted parent"):
        register_wakeup(conn, task_id="fake", owner="local",
                        conversation_id=parent_run.conversation_id,
                        parent_run_id="untrusted", agent_id=parent["id"],
                        thread_id="fake", subagent_type=child["id"], created_at=1)
    with db.connect() as conn:
        state = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (parent_run.run_id,)).fetchone()[0])
        state.pop("responseMessageId")
        conn.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), parent_run.run_id))
        register_wakeup(conn, task_id="fake", owner="local", conversation_id=parent_run.conversation_id,
                        parent_run_id=parent_run.run_id, agent_id=parent["id"],
                        thread_id="fake", subagent_type=child["id"], created_at=1)
        assert conn.execute("SELECT count(*) FROM subagent_wakeups").fetchone()[0] == 0
    await shutdown_subagent_tasks()




@pytest.mark.asyncio
async def test_manual_result_claim_and_automatic_delivery_race_has_one_winner(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent finished")
    await wait_admission()
    delivered = []

    async def dispatch(owner, generation, profile, agent, **kwargs):
        delivered.append(generation.run_id)

    scan, receipt = await asyncio.gather(
        process_wakeups(db, dispatch=dispatch),
        host.check({"background_task_id": task_id}),
    )
    claim = json.loads(receipt)
    assert scan in {0, 1}
    if scan == 1:
        assert claim["status"] == "delivery_scheduled" and "result" not in claim
    else:
        assert claim["result"] == "child result"
    with db.connect() as conn:
        wakeup = conn.execute("SELECT status FROM subagent_wakeups WHERE task_id=?",
                              (task_id,)).fetchone()[0]
        rows = conn.execute("SELECT result_claimed,result_claim_key FROM subagent_tasks WHERE id=?",
                            (task_id,)).fetchone()
        assert rows["result_claimed"] == 1
        assert wakeup == ("dispatched" if scan else "retired")
        assert (rows["result_claim_key"] == "wakeup:" + task_id) == bool(scan)
        assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?",
                            (parent_run.conversation_id,)).fetchone()[0] == 1 + scan
    assert len(delivered) == scan
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_sibling_child_completions_serialize_on_newest_parent_assistant(environment):
    db, repo, store, child, parent, parent_run = environment
    host, first_id, _ = await make_task(environment, call_id="sibling-1")
    host, second_id, _ = await make_task(environment, call_id="sibling-2")
    await completed(host, first_id)
    await completed(host, second_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent finished")
    await wait_admission()
    seen = []

    async def dispatch(owner, generation, profile, agent, **kwargs):
        seen.append(generation)

    assert await process_wakeups(db, dispatch=dispatch) == 1
    assert len(seen) == 1  # sibling cannot overtake in-flight continuation
    with db.connect() as conn:
        initially_running = conn.execute("SELECT task_id FROM subagent_wakeups WHERE "
                                         "status='dispatched'").fetchone()[0]
    store.finish("local", seen[0].run_id, status="complete", text="First delivered")
    assert await process_wakeups(db, dispatch=dispatch) == 1
    with db.connect() as conn:
        latest_input = conn.execute("SELECT parent_id FROM messages WHERE id=?",
                                    (seen[1].user_message_id,)).fetchone()
        assert latest_input["parent_id"] == seen[0].response_message_id
        assert conn.execute("SELECT count(*) FROM subagent_wakeups WHERE "
                            "status IN ('done','dispatched')").fetchone()[0] == 2
    assert {first_id, second_id} >= {initially_running}
    store.finish("local", seen[1].run_id, status="complete", text="Second delivered")
    assert await process_wakeups(db, dispatch=dispatch) == 0
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM subagent_wakeups WHERE "
                            "status='done'").fetchone()[0] == 2
    await shutdown_subagent_tasks()
