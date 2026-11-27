"""Goal continuations run in the original Chat actor, not a browser timer."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.session_runtime import get_session_runtime_manager
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import chat_goal, generation_routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.fixture
def goal_context(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir)
    store = GenerationStore(database)
    generation, _ = store.begin("local", {"text": "Complete the goal", "model": "fake"})
    profile = ProviderConfig("openai", "fake", "https://test.invalid", "")
    yield database, store, generation, profile
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["finish", "block", "cancel", "no_progress", "long"])
async def test_goal_continues_in_same_generation(goal_context, monkeypatch, outcome):
    database, store, generation, profile = goal_context
    turns = 0
    sid = None
    continuations = 0

    async def model(profile, history, **kwargs):
        nonlocal turns, sid, continuations
        turns += 1
        assert turns < 50
        last = history[-1]
        if turns == 1:
            yield ModelToolCall("session", "session_manage", {"action": "start", "label": "Goal"})
        elif turns == 2:
            sid = json.loads(last["content"])["data"]["session_id"]
            yield ModelToolCall("plan", "plan_manage", {
                "action": "start", "session_id": sid, "objective": "Complete the goal",
                "steps": [{"id": "work", "text": "Do work"}],
            })
        elif "Automatic Goal continuation" in str(last.get("content")):
            continuations += 1
            snapshot, _ = store.resume_snapshot("local", generation.run_id)
            markers = [p for p in snapshot["aggregatedContent"] if p.get("type") == "goal_continuation"]
            assert len(markers) == continuations
            assert all("goal_continuation" not in str(m.get("content")) for m in history)
            assert chat_goal.bound_session(database, "local", generation.run_id) == sid
            assert store.latest("local", generation.conversation_id).status == "running"
            if outcome == "no_progress":
                yield "Still working."
            elif outcome in {"finish", "long"}:
                if outcome == "long" and continuations < 12:
                    yield ModelToolCall(f"progress-{continuations}", "plan_manage", {
                        "action": "update", "session_id": sid, "step_id": "work",
                        "note": f"Progress {continuations}",
                    })
                else:
                    yield ModelToolCall("update", "plan_manage", {
                        "action": "update", "session_id": sid, "step_id": "work", "status": "completed",
                    })
            else:
                yield ModelToolCall(outcome, "plan_manage", {
                    "action": outcome, "session_id": sid, "note": "Cannot proceed",
                })
        elif turns == 3:
            assert json.loads(last["content"])["ok"] is True
            yield "Still working."
        elif outcome in {"finish", "long"} and last.get("tool_call_id") == "update":
            yield ModelToolCall("finish", "plan_manage", {"action": "finish", "session_id": sid})
        else:
            yield "Done."

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    await generation_routes._run_model("local", generation, profile)
    assert store.latest("local", generation.conversation_id).status == "complete"
    assert continuations == {"no_progress": 3, "long": 12}.get(outcome, 1)
    plan = get_session_runtime_manager().plan_state(sid, subject="local")
    assert plan["status"] == {"finish": "completed", "block": "blocked",
                              "cancel": "cancelled", "no_progress": "blocked",
                              "long": "completed"}[outcome]
    assert plan["continuation_count"] == 0  # Live Workspace's timer is not used.
    assert plan["continuation_driver"] == "chat"
    events = [event for _, event in store.events("local", generation.run_id)]
    markers = [event["data"] for event in events if event.get("event") == "on_goal_continuation"]
    assert len(markers) == continuations
    assert len({marker["id"] for marker in markers}) == continuations
    final_parts = events[-1]["responseMessage"]["content"]
    assert [part["id"] for part in final_parts if part["type"] == "goal_continuation"] == [
        marker["id"] for marker in markers
    ]
    assert events[-1]["responseMessage"]["text"].count("Automatic Goal continuation") == 0
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0] == 1


def test_goal_binding_owner_and_terminal_run_fences(goal_context):
    database, store, generation, _ = goal_context
    manager = get_session_runtime_manager()
    session = manager.manage("local", action="start", label="Goal")
    sid = session["session_id"]
    plan = manager.manage_plan(sid, subject="local", action="start",
                               objective="Goal", steps=[{"text": "Work"}])
    assert chat_goal.bind(database, "local", generation.run_id, sid, plan["plan"]["plan_id"])
    assert chat_goal.active_plan(database, "local", generation.run_id)
    assert chat_goal.active_plan(database, "other", generation.run_id) is None
    assert manager.claim_plan_continuation(sid, subject="local") is None
    store.finish("local", generation.run_id, status="aborted")
    chat_goal.pause(database, "local", generation.run_id, "Stopped by user.")
    assert manager.plan_state(sid, subject="local")["status"] == "blocked"
    assert chat_goal.continuation(database, "local", generation.run_id, []) is None

def test_external_resume_releases_only_terminal_chat_owner(goal_context):
    database, store, generation, _ = goal_context
    manager = get_session_runtime_manager()
    sid = manager.manage("local", action="start", label="Goal")["session_id"]
    plan = manager.manage_plan(sid, subject="local", action="start",
                               objective="Goal", steps=[{"text": "Work"}])
    assert chat_goal.bind(database, "local", generation.run_id, sid, plan["plan"]["plan_id"])
    manager.manage_plan(sid, subject="local", action="block", actor="human", note="Paused")
    resumed = manager.manage_plan(sid, subject="local", action="resume", actor="human")
    assert resumed["plan"]["continuation_driver"] == "chat"
    manager.manage_plan(sid, subject="local", action="block", actor="human", note="Paused again")
    assert store.finish("local", generation.run_id, status="aborted")
    resumed = manager.manage_plan(sid, subject="local", action="resume", actor="human")
    assert resumed["plan"]["status"] == "active"
    assert "continuation_driver" not in resumed["plan"]
    assert chat_goal.active_plan(database, "local", generation.run_id) is None


@pytest.mark.parametrize("payload", [
    {"ok": False},
    {"ok": True, "data": None},
    {"ok": True, "data": {"goal_mode": True, "session_id": "missing"}},
])
def test_observe_ignores_invalid_goal_results(goal_context, payload):
    database, _, generation, _ = goal_context
    raw = json.dumps(payload)
    assert chat_goal.observe_result(database, "local", generation.run_id, "plan_manage",
                                    {"action": "start"}, raw) == raw


def test_goal_cannot_bind_to_ended_generation_or_wrong_plan(goal_context):
    database, store, generation, _ = goal_context
    manager = get_session_runtime_manager()
    sid = manager.manage("local", action="start", label="Goal")["session_id"]
    plan_id = manager.manage_plan(sid, subject="local", action="start",
                                  objective="Goal", steps=[{"text": "Work"}])["plan"]["plan_id"]
    assert not chat_goal.bind(database, "other", generation.run_id, sid, plan_id)
    assert not chat_goal.bind(database, "local", generation.run_id, sid, "wrong-plan")
    raw = json.dumps({"ok": True, "data": {"goal_mode": True,
                     "session_id": sid, "plan": {"plan_id": "wrong-plan"}}})
    result = chat_goal.observe_result(database, "local", generation.run_id, "plan_manage",
                                      {"action": "resume"}, raw)
    assert json.loads(result)["ok"] is False
    assert store.finish("local", generation.run_id, status="aborted")
    assert not chat_goal.bind(database, "local", generation.run_id, sid, plan_id)


@pytest.mark.parametrize("error", [KeyError("gone"), RuntimeError("storage unavailable")])
def test_goal_pause_handles_missing_session_or_storage_failure(goal_context, monkeypatch, error):
    database, _, generation, _ = goal_context
    manager = get_session_runtime_manager()
    sid = manager.manage("local", action="start", label="Goal")["session_id"]
    plan_id = manager.manage_plan(sid, subject="local", action="start",
                                  objective="Goal", steps=[{"text": "Work"}])["plan"]["plan_id"]
    assert chat_goal.bind(database, "local", generation.run_id, sid, plan_id)

    def unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr(manager, "pause_chat_plan", unavailable)
    chat_goal.pause(database, "local", generation.run_id, "Stopped")
    monkeypatch.setattr(manager, "chat_plan_state", unavailable)
    if isinstance(error, KeyError):
        assert chat_goal.active_plan(database, "local", generation.run_id) is None
