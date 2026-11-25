"""True detached AgentRunner runs, on-disk task creation, restart and thread isolation."""
from __future__ import annotations

import asyncio
import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.subagent_task_host import SQLiteSubagentTaskHost, shutdown_subagent_tasks


@pytest.fixture
def runtime(tmp_path, monkeypatch):
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
    yield database, repo, GenerationStore(database), child, parent
    get_settings.cache_clear()


async def _noop(_text):
    pass


def make_runner(runtime, model):
    database, _, store, child, parent = runtime
    generation, _ = store.begin("local", {"text": "delegate a task"}, parent)
    runner = AgentRunner("local", generation, database, store, scopes=frozenset(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=_noop, agent=parent)
    return runner, generation


async def poll_until(host, task_id, wanted="completed"):
    for _ in range(80):
        row = host._get(task_id)
        if row and row["status"] == wanted:
            return row
        await asyncio.sleep(.04)
    raise AssertionError("Detached subagent never settled")


@pytest.mark.asyncio
async def test_background_subagent_persists_task_before_running_and_claims_once(runtime):
    database, _, store, child, parent = runtime
    ready, release = asyncio.Event(), asyncio.Event()
    observed = []

    async def model(profile, history, **kwargs):
        observed.append(profile.model)
        if profile.model == "parent":
            if any(item.get("role") == "tool" for item in history):
                yield "parent continues before child finishes"
            else:
                yield ModelToolCall("bg-1", "subagent", {
                    "subagent_type": child["id"], "description": "Inspect source", "run_in_background": True})
        else:
            ready.set()
            await release.wait()
            yield "child final"

    runner, generation = make_runner(runtime, model)
    results = await runner.run(store.history("local", generation.conversation_id))
    handles = [json.loads(msg["content"]) for msg in results if msg.get("role") == "tool"]
    assert len(handles) == 1 and handles[0]["status"] == "running"
    task_id, thread_id = handles[0]["background_task_id"], handles[0]["subagent_thread_id"]
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    await asyncio.wait_for(ready.wait(), 10)
    row = host._get(task_id)
    assert row["parent_run_id"] == generation.run_id and row["parent_tool_call_id"] == "bg-1"
    assert row["status"] == "running" and row["child_run_id"]
    assert observed == ["parent", "child", "parent"] or observed == ["parent", "parent", "child"]
    assert results[-1]["content"] == "parent continues before child finishes"
    store.finish("local", generation.run_id, status="complete", text="parent complete")
    release.set()
    await poll_until(host, task_id)
    first = json.loads(await host.check({"background_task_id": task_id}))
    assert first["status"] == "completed" and first["result"] == "child final"
    second = json.loads(await host.check({"background_task_id": task_id}))
    assert second["status"] == "claimed" and "result" not in second
    assert len(host.list()) == 1 and host.list()[0]["threadId"] == thread_id
    assert host._get(task_id)["result_claimed"] == 1
    foreign = SQLiteSubagentTaskHost(database, "other", generation.conversation_id,
                                     stream_tools=model, stream_text=model)
    assert json.loads(await foreign.check({"background_task_id": task_id}))["status"] == "not_found"
    assert foreign.list() == []
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_restart_replays_only_incomplete_child_on_original_thread(runtime):
    database, _, store, child, parent = runtime
    waiting, release = asyncio.Event(), asyncio.Event()
    child_calls = []

    async def model(profile, history, **kwargs):
        if profile.model == "parent":
            if any(item.get("role") == "tool" for item in history):
                yield "complete"
            else:
                yield ModelToolCall("bg", "subagent", {"subagent_type": child["id"],
                                                       "description": "first", "run_in_background": True})
        else:
            child_calls.append([item.get("content") for item in history])
            if not release.is_set():
                waiting.set()
                await release.wait()
            yield "reply"

    runner, generation = make_runner(runtime, model)
    results = await runner.run(store.history("local", generation.conversation_id))
    handle = json.loads(next(item["content"] for item in results if item.get("role") == "tool"))
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    await asyncio.wait_for(waiting.wait(), 10)
    await shutdown_subagent_tasks()
    assert host._get(handle["background_task_id"])["status"] == "running"
    assert host._get(handle["background_task_id"])["lease_owner"] is None
    release.set()
    # Simulates a brand new Runner using only saved SQLite state.
    other = SQLiteSubagentTaskHost(SQLiteDatabase(database.root), "local", generation.conversation_id,
                                   stream_tools=model, stream_text=model)
    assert json.loads(await other.check({"background_task_id": handle["background_task_id"]}))["status"] == "running"
    await poll_until(other, handle["background_task_id"])
    assert len(child_calls) == 2
    assert json.loads(await other.check({"background_task_id": handle["background_task_id"]}))["result"] == "reply"
    await shutdown_subagent_tasks()

@pytest.mark.asyncio
async def test_background_thread_continuation_preserves_prior_child_context(runtime):
    database, _, store, child, parent = runtime
    seen = []

    async def model(profile, history, **kwargs):
        if profile.model == "parent":
            yield "parent"
        else:
            seen.append([entry.get("content") for entry in history])
            yield "reply " + str(len(seen))

    original, first_run = make_runner(runtime, model)
    first_host = SQLiteSubagentTaskHost(database, "local", first_run.conversation_id,
                                       stream_tools=model, stream_text=model)
    from local_shell_mcp.webui.subagents import build_subagent_configs, invoke_subagent

    configs = build_subagent_configs("local", parent, database)
    async def start_with(invocation, thread):
        return await first_host.start(invocation, thread_id=thread)
    opts = {"execute_child": original._child, "start_background": start_with,
            "owner": "local", "conversation_id": first_run.conversation_id,
            "parent_run_id": first_run.run_id, "database": database,
            "scopes": frozenset(), "grant_expires": None}
    first = json.loads(await invoke_subagent(ModelToolCall("first", "subagent", {
        "subagent_type": child["id"], "description": "first request", "run_in_background": True,
    }), configs, **opts))
    await poll_until(first_host, first["background_task_id"])
    await first_host.check({"background_task_id": first["background_task_id"]})
    store.finish("local", first_run.run_id, status="complete", text="parent")
    second_run, _ = store.begin("local", {"conversationId": first_run.conversation_id,
                                          "text": "continue child"}, parent)
    opts["parent_run_id"] = second_run.run_id
    second = json.loads(await invoke_subagent(ModelToolCall("second", "subagent", {
        "subagent_type": child["id"], "description": "second request", "run_in_background": True,
        "subagent_thread_id": first["subagent_thread_id"],
    }), configs, **opts))
    assert second["subagent_thread_id"] == first["subagent_thread_id"]
    await poll_until(first_host, second["background_task_id"])
    result = json.loads(await first_host.check({"background_task_id": second["background_task_id"]}))
    assert result["result"] == "reply 2"
    assert any(message == "reply 1" for message in seen[1])
    assert "second request" in seen[1]
    assert "first request" in seen[1]
    assert len(first_host.list()) == 2
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_background_task_idempotency_argument_conflict_and_cross_scope_thread(runtime):
    database, repo, store, child, parent = runtime
    async def model(profile, history, **kwargs):
        yield "fine"
    original, generation = make_runner(runtime, model)
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    from local_shell_mcp.webui.subagents import build_subagent_configs, invoke_subagent

    config = build_subagent_configs("local", parent, database)
    kw = {"execute_child": original._child,
          "start_background": lambda invocation, thread: host.start(invocation, thread_id=thread),
          "owner": "local", "conversation_id": generation.conversation_id,
          "parent_run_id": generation.run_id, "database": database,
          "scopes": frozenset(), "grant_expires": None}
    base = {"subagent_type": child["id"], "description": "stable", "run_in_background": True}
    first = json.loads(await invoke_subagent(ModelToolCall("id", "subagent", base), config, **kw))
    again = json.loads(await invoke_subagent(ModelToolCall("id", "subagent", base), config, **kw))
    assert first["background_task_id"] == again["background_task_id"]
    assert f'Task handle: background_task_id "{first["background_task_id"]}"' in again["message"]
    conflict = json.loads(await invoke_subagent(ModelToolCall("id", "subagent", {
        **base, "description": "changed"}), config, **kw))
    assert conflict["status"] == "rejected"
    foreign_generation, _ = store.begin("local", {"text": "other conversation"}, parent)
    another = SQLiteSubagentTaskHost(database, "local", foreign_generation.conversation_id,
                                     stream_tools=model, stream_text=model)
    kw["conversation_id"] = foreign_generation.conversation_id
    kw["parent_run_id"] = foreign_generation.run_id
    kw["start_background"] = lambda invocation, thread: another.start(invocation, thread_id=thread)
    foreign = json.loads(await invoke_subagent(ModelToolCall("foreign", "subagent", {
        **base, "subagent_thread_id": first["subagent_thread_id"]}), config, **kw))
    assert foreign["status"] == "rejected"
    assert len(another.list()) == 0
    assert json.loads(await another.check({"background_task_id": first["background_task_id"]}))["status"] == "not_found"
    await shutdown_subagent_tasks()

@pytest.mark.asyncio
async def test_queued_message_applies_after_turn_and_receipt_is_durable(runtime):
    database, _, store, child, parent = runtime
    entered, release = asyncio.Event(), asyncio.Event()
    child_histories = []

    async def model(profile, history, **kwargs):
        if profile.model == "child":
            child_histories.append([msg.get("content") for msg in history])
            if len(child_histories) == 1:
                entered.set()
                await release.wait()
                yield "initial"
            else:
                yield "after queue"
        else:
            yield "parent"

    caller, generation = make_runner(runtime, model)
    from local_shell_mcp.webui.subagents import build_subagent_configs, invoke_subagent

    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    opts = {"execute_child": caller._child,
            "start_background": lambda inv, thread: host.start(inv, thread_id=thread),
            "owner": "local", "conversation_id": generation.conversation_id,
            "parent_run_id": generation.run_id, "database": database,
            "scopes": frozenset(), "grant_expires": None}
    handles = json.loads(await invoke_subagent(ModelToolCall("queue-test", "subagent", {
        "subagent_type": child["id"], "description": "start", "run_in_background": True,
    }), build_subagent_configs("local", parent, database), **opts))
    task_id = handles["background_task_id"]
    await asyncio.wait_for(entered.wait(), 10)
    receipt = json.loads(await host.check({"background_task_id": task_id,
                                           "action": "queue", "message": "queued follow-up"}))
    assert receipt["status"] == "accepted" and receipt["control_id"]
    with database.connect() as conn:
        row = conn.execute("SELECT status FROM subagent_task_controls WHERE id=?",
                           (receipt["control_id"],)).fetchone()
    assert row["status"] == "accepted"
    release.set()
    await poll_until(host, task_id)
    answer = json.loads(await host.check({"background_task_id": task_id}))
    assert answer["result"] == "after queue"
    assert len(child_histories) == 2 and "queued follow-up" in child_histories[1]
    with database.connect() as conn:
        row = conn.execute("SELECT status,boundary FROM subagent_task_controls WHERE id=?",
                           (receipt["control_id"],)).fetchone()
    assert (row["status"], row["boundary"]) == ("applied", "turn")
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_interrupt_preempts_model_and_cancel_message_withdraws_control(runtime):
    database, _, store, child, parent = runtime
    entered, release = asyncio.Event(), asyncio.Event()
    child_histories = []

    async def model(profile, history, **kwargs):
        if profile.model != "child":
            yield "parent"
            return
        child_histories.append([msg.get("content") for msg in history])
        if len(child_histories) == 1:
            entered.set()
            await release.wait()
            yield "partial stream"
            yield "must not be output"
        else:
            yield "after interrupt"

    caller, generation = make_runner(runtime, model)
    from local_shell_mcp.webui.subagents import build_subagent_configs, invoke_subagent

    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    opts = {"execute_child": caller._child,
            "start_background": lambda inv, thread: host.start(inv, thread_id=thread),
            "owner": "local", "conversation_id": generation.conversation_id,
            "parent_run_id": generation.run_id, "database": database,
            "scopes": frozenset(), "grant_expires": None}
    handles = json.loads(await invoke_subagent(ModelToolCall("interrupt-test", "subagent", {
        "subagent_type": child["id"], "description": "start", "run_in_background": True,
    }), build_subagent_configs("local", parent, database), **opts))
    task_id = handles["background_task_id"]
    await asyncio.wait_for(entered.wait(), 10)
    stale = json.loads(await host.check({"background_task_id": task_id,
                                         "action": "steer", "message": "withdraw this"}))
    withdrawn = json.loads(await host.check({"background_task_id": task_id,
                                             "action": "cancel_message", "control_id": stale["control_id"]}))
    assert withdrawn["status"] == "accepted"
    receipt = json.loads(await host.check({"background_task_id": task_id,
                                           "action": "interrupt", "message": "urgent change"}))
    release.set()
    await poll_until(host, task_id)
    result = json.loads(await host.check({"background_task_id": task_id}))
    assert result["result"] == "after interrupt"
    assert "urgent change" in child_histories[1]
    assert "withdraw this" not in child_histories[1]
    with database.connect() as conn:
        rows = conn.execute("SELECT id,status,boundary,reason FROM subagent_task_controls "
                            "WHERE task_id=?", (task_id,)).fetchall()
    receipts = {r["id"]: dict(r) for r in rows}
    assert receipts[stale["control_id"]]["status"] == "rejected"
    assert receipts[stale["control_id"]]["reason"] == "withdrawn"
    assert receipts[receipt["control_id"]]["status"] == "applied"
    assert receipts[receipt["control_id"]]["boundary"] == "preempt"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_cancel_running_child_settles_without_claiming_unfinished_result(runtime):
    database, _, store, child, parent = runtime
    entered = asyncio.Event()

    async def model(profile, history, **kwargs):
        if profile.model == "child":
            entered.set()
            await asyncio.Event().wait()
            yield "should never finish"
        else:
            yield "parent"

    caller, generation = make_runner(runtime, model)
    from local_shell_mcp.webui.subagents import build_subagent_configs, invoke_subagent

    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    opts = {"execute_child": caller._child,
            "start_background": lambda inv, thread: host.start(inv, thread_id=thread),
            "owner": "local", "conversation_id": generation.conversation_id,
            "parent_run_id": generation.run_id, "database": database,
            "scopes": frozenset(), "grant_expires": None}
    handle = json.loads(await invoke_subagent(ModelToolCall("cancel-test", "subagent", {
        "subagent_type": child["id"], "description": "block", "run_in_background": True,
    }), build_subagent_configs("local", parent, database), **opts))
    task_id = handle["background_task_id"]
    await asyncio.wait_for(entered.wait(), 10)
    requested = json.loads(await host.check({"background_task_id": task_id, "action": "cancel"}))
    assert requested["status"] == "cancellation_requested"
    await poll_until(host, task_id, "cancelled")
    claimed = json.loads(await host.check({"background_task_id": task_id}))
    assert claimed["status"] == "cancelled" and "cancelled" in claimed["error"]
    assert json.loads(await host.check({"background_task_id": task_id}))["status"] == "claimed"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_same_background_thread_busy_and_reserved_child_survives_orphan_scan(runtime):
    from local_shell_mcp.webui.subagent_task_host import active_child_generations
    from local_shell_mcp.webui.subagents import build_subagent_configs, invoke_subagent

    database, _, store, child, parent = runtime
    entered, release = asyncio.Event(), asyncio.Event()

    async def model(profile, history, **kwargs):
        if profile.model == 'child':
            entered.set()
            await release.wait()
            yield 'child finished'
        else:
            yield 'parent finished'

    runner, generation = make_runner(runtime, model)
    host = SQLiteSubagentTaskHost(database, 'local', generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    configs = build_subagent_configs('local', parent, database)
    kw = {'execute_child': runner._child,
          'start_background': lambda invocation, thread: host.start(invocation, thread_id=thread),
          'owner': 'local', 'conversation_id': generation.conversation_id,
          'parent_run_id': generation.run_id, 'database': database,
          'scopes': frozenset(), 'grant_expires': None}
    args = {'subagent_type': child['id'], 'description': 'Long-running work',
            'run_in_background': True}
    first = json.loads(await invoke_subagent(ModelToolCall('first-task', 'subagent', args), configs, **kw))
    await asyncio.wait_for(entered.wait(), timeout=9)
    second = json.loads(await invoke_subagent(ModelToolCall('second-task', 'subagent', {
        **args, 'subagent_thread_id': first['subagent_thread_id'],
    }), configs, **kw))
    assert second['status'] == 'rejected' and 'busy' in second['message']
    task = host._get(first['background_task_id'])
    with database.connect() as sql:
        # Reproduce a crash exactly after Generation.begin, before the task
        # references its child_run_id. Orphan finalization must not kill it.
        sql.execute('UPDATE subagent_tasks SET child_run_id=NULL WHERE id=?',
                    (first['background_task_id'],))
    active = active_child_generations(database)
    assert task['child_run_id'] in active
    assert store.recover_orphans(active | {generation.run_id}) == 0
    with database.connect() as sql:
        sql.execute('UPDATE subagent_tasks SET child_run_id=? WHERE id=?',
                    (task['child_run_id'], first['background_task_id']))
    release.set()
    await poll_until(host, first['background_task_id'])
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_ordinary_chat_self_subagent_inherits_model_without_recursive_spawn(runtime, monkeypatch):
    database, _, store, _, parent = runtime
    from local_shell_mcp.webui import lsm_tool_registry

    profile = ProviderConfig("openai", "selected-model", "https://named.invalid", "")
    acl_calls = []
    def native(owner, conversation, **kwargs):
        acl_calls.append((owner, conversation, kwargs))
        return []
    monkeypatch.setattr(lsm_tool_registry, "available_tools", native)
    generation, _ = store.begin("local", {"text": "parent-only history", "provider": "named",
                                          "model": profile.model, "web_search": False})
    observed = []

    async def model(active_profile, history, **kwargs):
        observed.append((active_profile, list(history), kwargs))
        if any(item.get("content") == "isolated task" for item in history):
            names = {t["function"]["name"] for t in kwargs.get("tools", [])}
            assert "subagent" not in names and "ask_user_question" not in names
            assert not names.intersection({"web_search", "web_fetch"})
            assert kwargs.get("temperature") == 0.3
            yield "child answer"
        elif any(item.get("role") == "tool" for item in history):
            yield "parent answer"
        else:
            yield ModelToolCall("self-sync", "subagent", {
                "description": "isolated task", "subagent_type": "self"})

    runner = AgentRunner("local", generation, database, store, scopes=frozenset(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=_noop, profile=profile,
                         parameters={"temperature": 0.3}, web_search_enabled=False)
    ctx = runner._context(None, profile=profile)
    tool = next(t["function"] for t in ctx.tools if t["function"]["name"] == "subagent")
    assert tool["parameters"]["properties"]["subagent_type"]["enum"] == ["self"]
    assert "run_in_background" in tool["parameters"]["properties"]
    result = await runner.run(store.history("local", generation.conversation_id))
    assert result[-1]["content"] == "parent answer"
    assert next(m["content"] for m in result if m["role"] == "tool") == "child answer"
    assert all(active == profile for active, _, _ in observed)
    child_history = next(history for _, history, _ in observed
                         if any(m.get("content") == "isolated task" for m in history))
    assert not any(m.get("content") == "parent-only history" for m in child_history)
    assert all(conversation == generation.conversation_id and not options["scopes"]
               for _, conversation, options in acl_calls)
    assert all(not options["agent_permissions"] for _, _, options in acl_calls)
    # Saved Agents' existing explicit configuration is unchanged.
    disabled = {**parent, "subagents": {"enabled": False}}
    assert not any(t["function"]["name"] == "subagent"
                   for t in runner._context(disabled, profile=profile).tools)
    restricted = runner._context(None, profile=profile, selected_tools=[])
    assert not any(t["function"]["name"] == "subagent" for t in restricted.tools)


@pytest.mark.asyncio
async def test_ordinary_chat_background_recovery_and_wakeup(runtime, monkeypatch):
    from local_shell_mcp.webui import providers, subagent_wakeup
    database, _, store, _, _ = runtime
    profile = ProviderConfig("openai", "chosen-model", "https://named.invalid", "")
    resolved = []
    def resolve(channel, model):
        resolved.append((channel, model))
        return profile
    monkeypatch.setattr(providers, "provider_config", resolve)
    monkeypatch.setattr(subagent_wakeup, "_DELAY_MS", 0)
    ready, release = asyncio.Event(), asyncio.Event()
    child_histories = []

    async def model(active_profile, history, **kwargs):
        assert active_profile == profile
        if any(m.get("content") == "detached task" for m in history):
            child_histories.append(list(history))
            ready.set()
            await release.wait()
            yield "detached result"
        elif any(m.get("role") == "tool" for m in history):
            yield "parent continues"
        else:
            yield ModelToolCall("self-bg", "subagent", {
                "description": "detached task", "subagent_type": "self", "run_in_background": True})

    generation, _ = store.begin("local", {"text": "parent only", "provider": "named-channel",
                                          "model": profile.model, "web_search": False})
    runner = AgentRunner("local", generation, database, store, scopes=frozenset(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=_noop, profile=profile,
                         parameters={"temperature": 0.2}, web_search_enabled=False)
    results = await runner.run(store.history("local", generation.conversation_id))
    handle = json.loads(next(m["content"] for m in results if m["role"] == "tool"))
    assert handle["status"] == "running"
    task_id = handle["background_task_id"]
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    try:
        await asyncio.wait_for(ready.wait(), 5)
        row = host._get(task_id)
        assert row["parent_agent_id"] == "default"
        options = json.loads(row["execution_options"])
        assert options["ordinary_chat"] and options["remaining_depth"] == 0
        assert options["parameters"] == {"temperature": 0.2}
        assert not options["web_search_enabled"] and not options["mcp_enabled"]
        assert store.get("local", row["child_run_id"]).agent_id is None
        await shutdown_subagent_tasks()
        assert host._get(task_id)["status"] == "running"
        release.set()
        await host.check({"background_task_id": task_id})
        await poll_until(host, task_id)
        assert len(child_histories) == 2
        store.finish("local", generation.run_id, status="complete", text="parent continues")
        dispatched = []

        async def dispatch(owner, wakeup, active_profile, agent, **kwargs):
            dispatched.append((owner, wakeup, active_profile, agent))

        assert await subagent_wakeup.process_wakeups(database, dispatch=dispatch) == 1
        assert len(dispatched) == 1
        owner, wakeup, active_profile, agent = dispatched[0]
        assert owner == "local" and active_profile == profile and agent is None
        assert wakeup.agent_id is None and not wakeup.web_search_enabled
        assert all(pair == ("named-channel", profile.model) for pair in resolved)
        assert len(resolved) >= 3
        assert any("detached result" in (m.get("content") or "")
                   for m in store.history("local", wakeup.conversation_id, message_id=wakeup.user_message_id))
    finally:
        release.set()
        await shutdown_subagent_tasks()
