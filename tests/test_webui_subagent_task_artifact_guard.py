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

from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks
from tests.test_webui_subagent_task_host_edges import settle, start_task

pytest_plugins = ("tests.test_webui_subagent_task_host_edges",)


@pytest.mark.asyncio
async def test_graph_host_artifact_guard_reserves_child_before_creation_and_settles(host_environment, monkeypatch):
    database = host_environment[0]
    with database.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS active_subagent_threads "
                   "(owner TEXT,thread_id TEXT,parent_run_id TEXT,active INTEGER, "
                   "PRIMARY KEY(owner,thread_id))")

    class ActiveChildThreads:
        def __init__(self, db):
            self.db = db

        def activate(self, owner, child, parent):
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                active = db.execute("SELECT r.status FROM runs r JOIN conversations c "
                                    "ON c.id=r.conversation_id WHERE r.id=? AND c.owner=?",
                                    (parent, owner)).fetchone()
                assert active is not None and active["status"] == "running"
                assert db.execute("SELECT 1 FROM conversations WHERE id=?", (child,)).fetchone() is None
                db.execute("INSERT INTO active_subagent_threads VALUES(?,?,?,1)",
                           (owner, child, parent))

        def settle(self, owner, child, parent):
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute("UPDATE active_subagent_threads SET active=0 "
                                     "WHERE owner=? AND thread_id=? AND parent_run_id=? AND active=1",
                                     (owner, child, parent)).rowcount
                assert changed in {0, 1}
                return bool(changed)

    module = types.ModuleType("local_shell_mcp.webui.child_thread_activity")
    module.ActiveChildThreads = ActiveChildThreads
    monkeypatch.setitem(sys.modules, module.__name__, module)

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
    database = host_environment[0]
    with database.connect() as db:
        db.execute("CREATE TABLE active_subagent_threads "
                   "(owner TEXT,thread_id TEXT,parent_run_id TEXT,active INTEGER, "
                   "PRIMARY KEY(owner,thread_id))")

    class Marker:
        def __init__(self, db):
            self.db = db

        def activate(self, owner, child, parent):
            with self.db.connect() as db:
                db.execute("INSERT INTO active_subagent_threads VALUES(?,?,?,1)",
                           (owner, child, parent))

        def settle(self, owner, child, parent):
            with self.db.connect() as db:
                return db.execute("UPDATE active_subagent_threads SET active=0 WHERE "
                                  "owner=? AND thread_id=? AND parent_run_id=?",
                                  (owner, child, parent)).rowcount == 1

    module = types.ModuleType("local_shell_mcp.webui.child_thread_activity")
    module.ActiveChildThreads = Marker
    monkeypatch.setitem(sys.modules, module.__name__, module)

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
    with database.connect() as db:
        row = host._get(task_id)
        db.execute("INSERT INTO active_subagent_threads VALUES(?,?,?,1)",
                   ("local", row["child_conversation_id"], row["parent_run_id"]))
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
