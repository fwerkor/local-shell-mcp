"""PR #352 integration seam: child identity is reserved before visibility.

The separate Artifacts PR owns ActiveChildThreads/its SQL table. This harness
injects that exact API contract without copying its implementation into the
graph runtime or requiring PR #352 to be merged before this isolated PR runs.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

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
async def test_graph_host_artifact_guard_reserves_child_before_creation_and_settles(host_environment, monkeypatch):
    from local_shell_mcp.webui.child_thread_activity import ActiveChildThreads

    database = host_environment[0]
    original_activate = ActiveChildThreads.activate
    original_settle = ActiveChildThreads.settle
    events = []

    def checked_activate(self, owner, child, parent):
        with self.database.connect() as db:
            active = db.execute("SELECT r.status FROM runs r JOIN conversations c "
                                "ON c.id=r.conversation_id WHERE r.id=? AND c.owner=?",
                                (parent, owner)).fetchone()
            assert active is not None and active["status"] == "running"
            assert db.execute("SELECT 1 FROM conversations WHERE id=?", (child,)).fetchone() is None
        events.append(('activate', child))
        return original_activate(self, owner, child, parent)

    def checked_settle(self, owner, child, parent):
        with self.database.connect() as db:
            task = db.execute("SELECT status FROM subagent_tasks WHERE "
                              "child_conversation_id=? AND owner=? AND parent_run_id=?",
                              (child, owner, parent)).fetchone()
            assert task is not None and task["status"] == "running"
        events.append(('settle', child))
        return original_settle(self, owner, child, parent)

    monkeypatch.setattr(ActiveChildThreads, "activate", checked_activate)
    monkeypatch.setattr(ActiveChildThreads, "settle", checked_settle)

    async def model(profile, history, **kwargs):
        yield "result"

    host, handle = await start_task(host_environment, model)
    task_id = handle["background_task_id"]
    task = await settle(host, task_id)
    with database.connect() as db:
        registry = db.execute("SELECT * FROM active_subagent_threads WHERE thread_id=?",
                              (task["child_conversation_id"],)).fetchone()
        assert registry is not None and registry["active"] == 0
        assert registry["parent_run_id"] == task["parent_run_id"]
        assert events == [('activate', task["child_conversation_id"]),
                          ('settle', task["child_conversation_id"])]
        convo = db.execute("SELECT c.id FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                           "WHERE r.id=?", (task["child_run_id"],)).fetchone()
        assert convo["id"] == task["child_conversation_id"]
    assert json.loads(await host.check({"background_task_id": task_id}))["result"] == "result"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_registered_child_remains_guarded_after_parent_cancel(host_environment, monkeypatch):
    # Simulate an already integrated PR352 guard, registering by exact method
    # name and refusing to delete a settled child marker.
    events = []

    class Marker:
        def __init__(self, db):
            self.db = db

        def activate(self, owner, thread, run):
            events.append(("activate", owner, thread, run))

        def settle(self, owner, thread, run):
            events.append(("settle", owner, thread, run))
            return True

    module = types.ModuleType("local_shell_mcp.webui.child_thread_activity")
    module.ActiveChildThreads = Marker
    monkeypatch.setitem(sys.modules, module.__name__, module)
    started = asyncio.Event()

    async def model(profile, history, **kwargs):
        started.set()
        await asyncio.Event().wait()
        yield "never"

    host, handle = await start_task(host_environment, model)
    await asyncio.wait_for(started.wait(), 5)
    task_id = handle["background_task_id"]
    requested = json.loads(await host.check({"background_task_id": task_id, "action": "cancel"}))
    assert requested["status"] == "cancellation_requested"
    terminal = await settle(host, task_id)
    assert terminal["status"] == "cancelled"
    assert events[0][0] == "activate"
    assert ("settle", host.owner, terminal["child_conversation_id"],
            terminal["parent_run_id"]) in events
    await shutdown_subagent_tasks()

@pytest.mark.asyncio
async def test_repeated_background_request_cannot_start_before_registered_marker(host_environment, monkeypatch):
    """Crash between marker commit and local admission bit is fail-closed."""
    from local_shell_mcp.webui.child_thread_activity import ActiveChildThreads

    database = host_environment[0]

    async def model(profile, history, **kwargs):
        yield "result"

    host, invocation = await start_task(host_environment, model, start=False)
    real_activate = host._ensure_active

    async def no_start(_task_id):
        return None

    monkeypatch.setattr(host, "_ensure_active", no_start)
    first = json.loads(await host.start(invocation))
    task_id = first["background_task_id"]
    with database.connect() as db:
        db.execute("UPDATE subagent_tasks SET child_registered=0 WHERE id=?", (task_id,))
        db.execute("DELETE FROM active_subagent_threads WHERE thread_id=?",
                   (host._get(task_id)["child_conversation_id"],))
    monkeypatch.setattr(host, "_ensure_active", real_activate)
    assert json.loads(await host.start(invocation))["background_task_id"] == task_id
    assert host._get(task_id)["child_run_id"] is None  # fenced, not dispatched
    assert host._get(task_id)["child_registered"] == 0
    row = host._get(task_id)
    ActiveChildThreads(database).activate("local", row["child_conversation_id"], row["parent_run_id"])
    await host._ensure_active(task_id)
    terminal = await settle(host, task_id)
    assert terminal["status"] == "completed" and terminal["child_registered"] == 1
    await shutdown_subagent_tasks()


def test_trusted_child_uuid_allocation_never_accepts_model_conversation_field(host_environment):
    import uuid

    database, repo, store, child, parent, generation = host_environment
    with pytest.raises(ValueError, match="Invalid reserved child"):
        store.begin("local", {"text": "bad"}, child,
                    trusted_new_conversation_id="arbitrary-model-input")
    with pytest.raises(ValueError, match="must be a new conversation"):
        store.begin("local", {"text": "bad", "conversationId": generation.conversation_id},
                    child, trusted_new_conversation_id=str(uuid.uuid4()))
    reserved = str(uuid.uuid4())
    child_generation, is_new = store.begin(
        "local", {"text": "host allocated"}, child,
        trusted_new_conversation_id=reserved,
    )
    assert is_new and child_generation.conversation_id == reserved
    with database.connect() as db:
        assert db.execute("SELECT owner FROM conversations WHERE id=?", (reserved,)).fetchone()[0] == "local"


@pytest.mark.asyncio
async def test_artifact_guard_denied_registration_fails_child_closed(host_environment, monkeypatch):
    class Reject:
        def __init__(self, database):
            self.database = database

        def activate(self, owner, child, run):
            raise PermissionError("Original child owner is no longer active")

        def settle(self, owner, child, run):
            raise AssertionError("An unregistered child cannot be settled")

    module = types.ModuleType("local_shell_mcp.webui.child_thread_activity")
    module.ActiveChildThreads = Reject
    monkeypatch.setitem(sys.modules, module.__name__, module)

    async def model(profile, history, **kwargs):
        raise AssertionError("Denied registration cannot launch a model")
        yield "never"  # pragma: no cover

    host, invocation = await start_task(host_environment, model, start=False)
    with pytest.raises(PermissionError, match="owner"):
        await host.start(invocation)
    tasks = host.list()
    assert len(tasks) == 1 and tasks[0]["status"] == "error"
    row = host._get(tasks[0]["taskId"])
    assert row["child_run_id"] is None and row["child_registered"] == 0
    assert row["error"] == "Child-thread registration rejected"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_artifact_guard_settles_preexecution_cancel_outside_sqlite_lock(host_environment, monkeypatch):
    calls = []

    class Marker:
        def __init__(self, database):
            self.database = database

        def activate(self, owner, child, run):
            calls.append(("activate", child, run))

        def settle(self, owner, child, run):
            calls.append(("settle", child, run))
            return True

    module = types.ModuleType("local_shell_mcp.webui.child_thread_activity")
    module.ActiveChildThreads = Marker
    monkeypatch.setitem(sys.modules, module.__name__, module)

    async def model(profile, history, **kwargs):
        raise AssertionError("No child model should run after preexecution cancel")
        yield "never"  # pragma: no cover

    host, invocation = await start_task(host_environment, model, start=False)
    real_ensure = host._ensure_active

    async def delayed(_task_id):
        return None

    monkeypatch.setattr(host, "_ensure_active", delayed)
    handle = json.loads(await host.start(invocation))
    task_id = handle["background_task_id"]
    monkeypatch.setattr(host, "_ensure_active", real_ensure)
    with host.db.connect() as db:
        db.execute("UPDATE subagent_tasks SET cancel_requested=1 WHERE id=?", (task_id,))
    await asyncio.wait_for(host._ensure_active(task_id), timeout=5)
    row = host._get(task_id)
    assert row["status"] == "cancelled" and row["child_run_id"] is None
    assert [call[0] for call in calls] == ["activate", "settle"]
    await shutdown_subagent_tasks()
