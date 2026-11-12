"""Failure, capacity, idempotent control and authorization branches of the detached host."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.subagent_task_host import SQLiteSubagentTaskHost, shutdown_subagent_tasks
from local_shell_mcp.webui.subagents import build_subagent_configs


@pytest.fixture
def host_environment(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import agent_runner

    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    database = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    monkeypatch.setattr(agent_runner, "provider_config", lambda kind, model: ProviderConfig(
        "openai", model, "https://stub.invalid", ""))
    repo = AgentRepository(database)
    child = repo.create("local", {"name": "child", "provider": "openAI", "model": "child", "tools": []})
    parent = repo.create("local", {"name": "parent", "provider": "openAI", "model": "parent", "tools": [],
                                   "subagents": {"enabled": True, "allowSelf": False,
                                                 "agent_ids": [child["id"]]}})
    store = GenerationStore(database)
    generation, _ = store.begin("local", {"text": "delegate"}, parent)
    yield database, repo, store, child, parent, generation
    get_settings.cache_clear()


async def start_task(env, model, *, call_id="task-1", text="description",
                     thread_id=None, grant_expires=None, scopes=frozenset(), start=True):
    from local_shell_mcp.webui.subagents import SubagentInvocation

    database, repo, store, child, parent, generation = env
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    config = build_subagent_configs("local", parent, database)[0]
    invocation = SubagentInvocation(
        agent=config.agent, messages=[{"role": "user", "content": text}],
        selected_tools=tuple(config.agent.get("tools") or []),
        max_turns=config.max_turns, recursion_limit=config.max_turns * 3,
        remaining_depth=0, scopes=scopes, grant_expires=grant_expires,
        owner="local", conversation_id=generation.conversation_id,
        parent_run_id=generation.run_id, parent_tool_call_id=call_id,
        subagent_type=child["id"], child_configs=(),
    )
    if start:
        return host, json.loads(await host.start(invocation, thread_id=thread_id))
    return host, invocation


async def settle(host, task_id, *, timeout=4):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        record = host._get(task_id)
        if record and record["status"] != "running":
            return record
        await asyncio.sleep(.02)
    raise AssertionError("Task did not settle")


@pytest.mark.asyncio
async def test_check_background_call_replay_fences_poll_and_control(host_environment):
    async def model(profile, history, **kwargs):
        yield "result"

    host, handle = await start_task(host_environment, model)
    task_id = handle["background_task_id"]
    await settle(host, task_id)
    generation = host_environment[-1]
    args = {"background_task_id": task_id}
    kw = {"tool_call_id": "poll-1", "parent_run_id": generation.run_id,
          "parent_agent_id": host_environment[-2]["id"]}
    first = await host.check(args, **kw)
    again = await host.check(args, **kw)
    assert first == again and json.loads(first)["result"] == "result"
    assert json.loads(await host.check(args, tool_call_id="poll-2", **{
        k: v for k, v in kw.items() if k != "tool_call_id"}))["status"] == "claimed"
    changed = json.loads(await host.check({"background_task_id": task_id, "action": "cancel"}, **kw))
    assert changed["status"] == "invalid"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_control_invocation_idempotent_and_invalid_inputs(host_environment):
    entered = asyncio.Event()

    async def model(profile, history, **kwargs):
        entered.set()
        await asyncio.Event().wait()
        yield "never"

    host, handle = await start_task(host_environment, model)
    task_id = handle["background_task_id"]
    await asyncio.wait_for(entered.wait(), 5)
    generation = host_environment[-1]
    args = {"background_task_id": task_id, "action": "queue", "message": "next"}
    kw = {"tool_call_id": "ctrl-1", "parent_run_id": generation.run_id,
          "parent_agent_id": host_environment[-2]["id"]}
    first = json.loads(await host.check(args, **kw))
    second = json.loads(await host.check(args, **kw))
    assert first == second and first["control_id"]
    assert first["status"] == "accepted"
    assert json.loads(await host.check({**args, "message": "changed"}, **kw))["status"] == "invalid"
    assert json.loads(await host.check({"action": "queue", "message": "x"}))["status"] == "invalid"
    assert json.loads(await host.check({"background_task_id": "x" * 257}))["status"] == "invalid"
    assert json.loads(await host.check({"background_task_id": "missing"}))["status"] == "not_found"
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "queue", "message": "  "}))["status"] == "invalid"
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "steer", "message": "x" * 65537}))["status"] == "invalid"
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "cancel_message", "control_id": "x" * 257}))["status"] == "invalid"
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "cancel_message", "control_id": "unknown"}))["status"] == "control_not_found"
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "cancel_message", "control_id": first["control_id"]}))["status"] == "accepted"
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "cancel_message", "control_id": first["control_id"]}))["status"] == "control_not_found"
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "cancel"}))["status"] == "cancellation_requested"
    await settle(host, task_id)
    assert json.loads(await host.check({"background_task_id": task_id,
                                      "action": "cancel"}))["status"] == "not_running"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_task_rejects_foreign_parent_lineage_expired_grant_and_capacity(host_environment, monkeypatch):
    entered = asyncio.Event()

    async def model(profile, history, **kwargs):
        entered.set()
        await asyncio.Event().wait()
        yield "never"

    host, request = await start_task(host_environment, model, start=False)
    from dataclasses import replace

    with pytest.raises(PermissionError, match="Parent run"):
        await host.start(replace(request, parent_run_id="run_not_owned"))
    with pytest.raises(PermissionError, match="scope"):
        await host.start(replace(request, conversation_id="not_here"))
    with pytest.raises(PermissionError, match="scope"):
        await host.start(replace(request, owner="other"))
    with pytest.raises(PermissionError, match="grant expired"):
        await host.start(replace(request, grant_expires=int(time.time()) - 5))
    # Same tool-call id/fingerprint remains deduped; it cannot mint a fresh grant.
    import local_shell_mcp.webui.subagent_task_host as task_module

    monkeypatch.setattr(task_module, "_RUNNING_PER_SCOPE", 1)
    accepted = json.loads(await host.start(request))
    assert accepted["status"] == "running"
    denied = json.loads(await host.start(replace(request, parent_tool_call_id="different")))
    assert denied["status"] == "rejected"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_unhandled_model_error_and_task_timeout_are_stored_without_secrets(host_environment, monkeypatch):
    async def failing(profile, history, **kwargs):
        raise ValueError("secret-token-must-not-be-returned")
        yield "unused"  # pragma: no cover

    host, handle = await start_task(host_environment, failing, call_id="error")
    await settle(host, handle["background_task_id"])
    failure = json.loads(await host.check({"background_task_id": handle["background_task_id"]}))
    assert failure["status"] == "error" and "ValueError" in failure["error"]
    assert "secret-token" not in failure["error"]
    import local_shell_mcp.webui.subagent_task_host as task_module

    monkeypatch.setattr(task_module, "_TIMEOUT_SECONDS", .01)
    async def hanging(profile, history, **kwargs):
        await asyncio.Event().wait()
        yield "never"

    host, second = await start_task(host_environment, hanging, call_id="timeout")
    await settle(host, second["background_task_id"])
    result = json.loads(await host.check({"background_task_id": second["background_task_id"]}))
    assert result["status"] == "error" and "TimeoutError" in result["error"]
    await shutdown_subagent_tasks()

@pytest.mark.asyncio
async def test_start_parent_actor_lineage_and_rejected_bad_inputs(host_environment):
    from dataclasses import replace

    async def model(profile, history, **kwargs):
        yield "done"

    host, invocation = await start_task(host_environment, model, start=False)
    repo = host_environment[1]
    other_parent = repo.create("local", {"name": "peer", "provider": "openAI",
                                         "model": "peer", "tools": []})
    empty = json.loads(await host.start(replace(invocation, parent_tool_call_id="")))
    assert empty["status"] == "rejected"
    with pytest.raises(PermissionError, match="owned"):
        await host.start(replace(invocation, parent_agent_id="agent_unknown"))
    first = json.loads(await host.start(replace(invocation, parent_agent_id=host_environment[-2]["id"])))
    second = json.loads(await host.start(replace(invocation, parent_agent_id=other_parent["id"])))
    assert first["background_task_id"] != second["background_task_id"]
    await settle(host, first["background_task_id"])
    await settle(host, second["background_task_id"])
    with host.db.connect() as db:
        keys = db.execute("SELECT parent_agent_id FROM subagent_tasks ORDER BY created_at").fetchall()
    assert {row[0] for row in keys} == {host_environment[-2]["id"], other_parent["id"]}
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_pending_stale_task_claim_and_remote_cancel_do_not_report_stopped(host_environment, monkeypatch):
    import local_shell_mcp.webui.subagent_task_host as subtask

    started = asyncio.Event()
    async def model(profile, history, **kwargs):
        started.set()
        await asyncio.Event().wait()
        yield "not returned"

    host, handle = await start_task(host_environment, model)
    task_id = handle["background_task_id"]
    await asyncio.wait_for(started.wait(), 4)
    # Simulate a different Controller instance handling the cancellation.
    running = subtask._TASKS.pop(task_id)
    try:
        requested = json.loads(await host.check({"background_task_id": task_id, "action": "cancel"}))
        assert requested["status"] == "cancellation_requested"
        assert host._get(task_id)["status"] == "running"
    finally:
        subtask._TASKS[task_id] = running
    running.cancel()
    await settle(host, task_id)
    assert host.has_interrupt(task_id) is False
    assert host.pending(task_id, "turn", set()) == []
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_crash_replay_of_reserved_poll_and_control_has_durable_receipts(host_environment):
    async def model(profile, history, **kwargs):
        yield "result"

    host, handle = await start_task(host_environment, model)
    task_id = handle["background_task_id"]
    await settle(host, task_id)
    generation = host_environment[-1]
    kw = {"tool_call_id": "receipt-id", "parent_run_id": generation.run_id,
          "parent_agent_id": host_environment[-2]["id"]}
    first = json.loads(await host.check({"background_task_id": task_id}, **kw))
    assert first["result"] == "result"
    with host.db.connect() as db:
        db.execute("UPDATE subagent_task_invocations SET status='reserved',result=NULL WHERE tool_call_id=?",
                   ("receipt-id",))
    recovered = json.loads(await host.check({"background_task_id": task_id}, **kw))
    assert recovered["result"] == "result"
    with host.db.connect() as db:
        db.execute("UPDATE subagent_task_invocations SET status='reserved' WHERE tool_call_id=?",
                   ("receipt-id",))
        db.execute("UPDATE subagent_tasks SET result_claim_key=NULL WHERE id=?", (task_id,))
    uncertain = json.loads(await host.check({"background_task_id": task_id}, **kw))
    assert uncertain["status"] == "unavailable"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_expired_claim_cancel_before_dispatch_and_oversize_transcript(host_environment, monkeypatch):
    from dataclasses import replace

    import local_shell_mcp.webui.subagent_task_host as module

    async def model(profile, history, **kwargs):
        yield "some result"

    host, invocation = await start_task(host_environment, model, start=False)
    original = host._ensure_active

    async def no_launch(_task_id):
        return None

    monkeypatch.setattr(host, "_ensure_active", no_launch)
    to_expire = json.loads(await host.start(replace(invocation, parent_tool_call_id="grant")))
    to_cancel = json.loads(await host.start(replace(invocation, parent_tool_call_id="cancel")))
    with host.db.connect() as db:
        db.execute("UPDATE subagent_tasks SET grant_expires=? WHERE id=?",
                   (time.time() - 1, to_expire["background_task_id"]))
        db.execute("UPDATE subagent_tasks SET cancel_requested=1 WHERE id=?",
                   (to_cancel["background_task_id"],))
    monkeypatch.setattr(host, "_ensure_active", original)
    assert json.loads(await host.check({"background_task_id": to_expire["background_task_id"]}))["status"] == "error"
    assert json.loads(await host.check({"background_task_id": to_cancel["background_task_id"]}))["status"] == "cancelled"
    monkeypatch.setattr(module, "_MAX_THREAD_HISTORY", 10)
    oversized = json.loads(await host.start(replace(invocation, parent_tool_call_id="too-large")))
    await settle(host, oversized["background_task_id"])
    assert json.loads(await host.check({"background_task_id": oversized["background_task_id"]}))["status"] == "error"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_pending_control_capacity_and_task_capacity_rejection(host_environment, monkeypatch):
    from dataclasses import replace

    import local_shell_mcp.webui.subagent_task_host as module

    async def model(profile, history, **kwargs):
        await asyncio.Event().wait()
        yield "never"

    host, request = await start_task(host_environment, model, start=False)
    monkeypatch.setattr(module, "_RUNNING_PER_SCOPE", 1)
    first = json.loads(await host.start(request))
    task_id = first["background_task_id"]
    with host.db.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for n in range(32):
            stamp = module._now()
            db.execute("INSERT INTO subagent_task_controls "
                       "(id,task_id,action,message,status,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?)", (f"ctrl-{n}", task_id, "queue", f"msg-{n}",
                                                "accepted", stamp, stamp))
    rejected = json.loads(await host.check({"background_task_id": task_id,
                                            "action": "queue", "message": "extra"}))
    assert rejected["status"] == "invalid"
    assert host.list()[0]["pendingControls"] == 32
    with host.db.connect() as db:
        db.execute("UPDATE subagent_task_controls SET status='rejected' WHERE task_id=?", (task_id,))
    cap = json.loads(await host.start(replace(request, parent_tool_call_id="second")))
    assert cap["status"] == "rejected"
    await host.check({"background_task_id": task_id, "action": "cancel"})
    await settle(host, task_id)
    await shutdown_subagent_tasks()

@pytest.mark.asyncio
async def test_actual_agents_401_background_store_differential(host_environment):
    """Real pinned npm runtime + actual LangChain messages, not an ad-hoc JS stub."""
    import os
    import shutil
    import subprocess
    from dataclasses import replace
    from pathlib import Path

    root = os.getenv("LSM_JS_ORACLE_ROOT")
    node = shutil.which("node")
    if not root or not node:
        assert os.getenv("LSM_REQUIRE_SOURCE_ORACLES") != "1", "Pinned agents 4.0.1 oracle is required"
        pytest.skip("Set LSM_JS_ORACLE_ROOT to the exact integrated npm test installation")
    fixture = Path(__file__).parent / "fixtures/librechat/subagent_task_real_reference.cjs"
    output = subprocess.check_output([node, str(fixture)], cwd=root, timeout=15, env=os.environ)
    source = json.loads(output)
    assert source["source"] == "@librechat/agents@4.0.1"
    expected = source["trace"]

    entered, release = asyncio.Event(), asyncio.Event()

    async def model(profile, history, **kwargs):
        entered.set()
        await release.wait()
        yield "reviewed"

    host, invocation = await start_task(host_environment, model, text="Review source", start=False)
    first = json.loads(await host.start(invocation))
    duplicate = json.loads(await host.start(invocation))
    conflict = json.loads(await host.start(replace(invocation, messages=[
        {"role": "user", "content": "different"},
    ])))
    task_id = first["background_task_id"]
    await asyncio.wait_for(entered.wait(), 5)
    queued = json.loads(await host.check({"background_task_id": task_id,
                                          "action": "queue", "message": "ignore this"}))
    withdrawn = json.loads(await host.check({"background_task_id": task_id,
                                             "action": "cancel_message",
                                             "control_id": queued["control_id"]}))
    steered = json.loads(await host.check({"background_task_id": task_id,
                                           "action": "steer", "message": "focus on safety"}))
    pending = host.pending(task_id, "tool", set())
    actual_injected = [{"role": entry["role"], "content": entry["content"],
                        "source": entry["additional_kwargs"]["source"]} for entry in pending]
    host.acknowledge(task_id, "tool", {entry["id"] for entry in pending})
    actual_turn = host.pending(task_id, "turn", {entry["id"] for entry in pending})
    release.set()
    finished = await settle(host, task_id)
    with host.db.connect() as db:
        receipts = db.execute("SELECT action,status,boundary,reason FROM subagent_task_controls "
                              "WHERE task_id=? ORDER BY created_at,id", (task_id,)).fetchall()
    foreign = SQLiteSubagentTaskHost(host.db, "local", "different-conversation",
                                     stream_tools=model, stream_text=model)
    foreign_poll = json.loads(await foreign.check({"background_task_id": task_id}))
    claim = json.loads(await host.check({"background_task_id": task_id}))
    again = json.loads(await host.check({"background_task_id": task_id}))
    got = {
        "start": first["status"], "duplicate": duplicate["background_task_id"] == task_id,
        "conflict": "conflict" if conflict["status"] == "rejected" else "missing",
        "queue": queued["status"], "withdraw": withdrawn["status"],
        "steer": steered["status"], "pending": len(pending),
        "foreign": foreign_poll["status"], "injectedAtTool": actual_injected,
        "injectedAtTurn": actual_turn, "settled": finished["status"],
        "receipts": [[row["action"], row["status"], row["boundary"] or "", row["reason"] or ""]
                     for row in receipts],
        "claim": claim["status"], "claimResult": claim["result"],
        "claimedFlag": claim.get("result_claimed", False),
        "claimAvailable": claim.get("result_available", False),
        "claimAgain": again["status"], "snapshotAfter": host._get(task_id)["status"],
    }
    assert got == expected, (got, expected)
    await shutdown_subagent_tasks()

@pytest.mark.asyncio
async def test_startup_automatically_recovers_subagent_with_original_child_generation(host_environment):
    from local_shell_mcp.webui.subagent_task_host import (
        active_child_generations,
        recover_subagent_tasks,
    )

    entered, continue_model = asyncio.Event(), asyncio.Event()
    child_calls = []

    async def model(profile, history, **kwargs):
        child_calls.append([entry.get("content") for entry in history])
        if not continue_model.is_set():
            entered.set()
            await continue_model.wait()
        yield "recovered reply"

    host, result = await start_task(host_environment, model)
    task_id = result["background_task_id"]
    await asyncio.wait_for(entered.wait(), 5)
    row = host._get(task_id)
    child_run_id = row["child_run_id"]
    assert child_run_id in active_child_generations(host.db)
    await shutdown_subagent_tasks()
    assert host._get(task_id)["status"] == "running"
    assert child_run_id in active_child_generations(host.db)
    store = host_environment[2]
    assert store.recover_orphans(active_child_generations(host.db)) == 1
    assert store.get("local", child_run_id).status == "running"
    continue_model.set()
    restarted = SQLiteDatabase(host.db.root)
    accepted = await recover_subagent_tasks(restarted, stream_tools=model, stream_text=model)
    assert accepted == 1
    again = SQLiteSubagentTaskHost(restarted, "local", host.conversation_id,
                                   stream_tools=model, stream_text=model)
    await settle(again, task_id)
    assert len(child_calls) == 2
    assert store.get("local", child_run_id).status == "complete"
    assert json.loads(await again.check({"background_task_id": task_id}))["result"] == "recovered reply"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_stolen_live_lease_never_persists_terminal_or_executes_more_tools(host_environment):
    from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError

    entered, continue_model = asyncio.Event(), asyncio.Event()

    async def model(profile, history, **kwargs):
        entered.set()
        await continue_model.wait()
        yield "must not complete"

    host, result = await start_task(host_environment, model)
    task_id = result["background_task_id"]
    await asyncio.wait_for(entered.wait(), 5)
    with host.db.connect() as db:
        db.execute("UPDATE subagent_tasks SET lease_owner=?,lease_until=? WHERE id=?",
                   ("other-controller", int(time.time() * 1000) + 30_000, task_id))
    with pytest.raises(RuntimeSafetyError, match="lease"):
        host.assert_execution_lease(task_id)
    continue_model.set()
    await asyncio.sleep(.1)
    row = host._get(task_id)
    assert row["status"] == "running" and row["lease_owner"] == "other-controller"
    assert row["result"] is None
    # Do not forge an owner lease; simply close its old terminal slot locally.
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_child_subagent_budget_never_resets_after_nested_delegation(host_environment):
    from local_shell_mcp.webui.agent_runner import AgentRunner

    database, repo, store, child, parent, generation = host_environment
    async def model(profile, history, **kwargs):
        yield "unused"

    nested = repo.create("local", {"name": "nested", "provider": "openAI",
                                   "model": "nested", "tools": []})
    child = repo.update("local", child["id"], {"subagents": {
        "enabled": True, "allowSelf": False, "agent_ids": [nested["id"]],
    }})
    # Force a zero-depth child while retaining a configured nested catalog.
    runner = AgentRunner("local", generation, database, store, scopes=frozenset(),
                         grant_expires=None, stream_tools=model, stream_text=model,
                         on_text=lambda _text: asyncio.sleep(0), agent=child,
                         subagent_depth=0)
    context = runner._context(child)
    assert not any(tool["function"]["name"] == "subagent" for tool in context.tools)
    assert not any(tool["function"]["name"] == "check_background_task" for tool in context.tools)
    assert runner.configs[child["id"]] == []
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_owner_lease_stolen_after_model_cannot_finish_generation(host_environment, monkeypatch):
    """A stale Controller must not publish completion after the last model step."""
    from local_shell_mcp.webui import subagent_task_host as module

    async def model(profile, history, **kwargs):
        yield "old process result must be ignored"

    host, invocation = await start_task(host_environment, model, start=False)
    unmodified = host._settle_child_registration
    stolen = asyncio.Event()

    def steal_at_finish(task_id, **kwargs):
        if kwargs.get("before_terminal") and kwargs.get("lease_token"):
            with host.db.connect() as db:
                db.execute("UPDATE subagent_tasks SET lease_owner=?,lease_until=? "
                           "WHERE id=? AND status='running'",
                           ("new-controller-token", module._now() + 30_000, task_id))
            stolen.set()
        return unmodified(task_id, **kwargs)

    monkeypatch.setattr(host, "_settle_child_registration", steal_at_finish)
    handle = json.loads(await host.start(invocation))
    task_id = handle["background_task_id"]
    await asyncio.wait_for(stolen.wait(), 5)
    for _ in range(100):
        if task_id not in module._TASKS:
            break
        await asyncio.sleep(.01)
    row = host._get(task_id)
    assert row["status"] == "running" and row["lease_owner"] == "new-controller-token"
    assert row["result"] is None
    assert row["child_run_id"] is not None
    assert host_environment[2].get("local", row["child_run_id"]).status == "running"
    await shutdown_subagent_tasks()
