"""Owner-fenced, bounded delegated Agents use the shared SQLite state."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.delegation import delegation_tools, run_subagent
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.mark.asyncio
async def test_agent_delegation_and_handoff_reuse_child_profile_without_machine_tools(tmp_path, monkeypatch):
    from local_shell_mcp.webui import delegation

    db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    store = AgentRepository(db)
    child = store.create("alice", {"name": "Research", "provider": "openAI",
                                   "model": "mock", "instructions": "No tool access"})
    parent = store.create("alice", {"name": "Lead", "provider": "openAI",
                                    "model": "mock", "subagents": [child["id"]]})
    run, _ = GenerationStore(db).begin("alice", {"text": "Start"})
    seen = []

    async def fake_stream(profile, messages, **kwargs):
        seen.append((profile.model, messages))
        yield "delegated "
        yield "result"

    monkeypatch.setattr(delegation, "stream_model", fake_stream)
    monkeypatch.setattr(delegation, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    exposed = {item["function"]["name"] for item in delegation_tools(parent)}
    assert exposed == {"delegate_agent", "handoff_agent"}
    for action in sorted(exposed):
        result = json.loads(await run_subagent("alice", run, parent, ModelToolCall("tool", action, {
            "agent_id": child["id"], "task": "Explain the finding",
        }), db))
        assert result["agent_id"] == child["id"]
        assert result["output"] == "delegated result"
    assert seen == [
        ("mock", [{"role": "system", "content": "No tool access"},
                  {"role": "user", "content": "Explain the finding"}]),
    ] * 2
    with db.connect() as conn:
        entries = conn.execute("SELECT kind,status,result FROM agent_delegations ORDER BY created_at").fetchall()
    assert sorted(row["kind"] for row in entries) == ["delegate", "handoff"]
    assert all(row["status"] == "complete" and row["result"] == "delegated result" for row in entries)
    with pytest.raises(PermissionError, match="not approved"):
        await run_subagent("alice", run, {"id": "other", "subagents": []}, ModelToolCall(
            "tool", "delegate_agent", {"agent_id": child["id"], "task": "Disallowed"}), db)
    with pytest.raises(PermissionError, match="not owned"):
        await run_subagent("bob", run, {"id": "other", "subagents": [child["id"]]}, ModelToolCall(
            "tool", "delegate_agent", {"agent_id": child["id"], "task": "Disallowed"}), db)


@pytest.mark.asyncio
async def test_delegation_output_budget_records_error_without_partial_success(tmp_path, monkeypatch):
    from local_shell_mcp.webui import delegation

    db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    child = AgentRepository(db).create("alice", {"name": "Long", "provider": "openAI", "model": "mock"})
    parent = {"id": "parent", "subagents": [child["id"]]}
    run, _ = GenerationStore(db).begin("alice", {"text": "task"})

    async def enormous(*args, **kwargs):
        yield "X" * 33000

    monkeypatch.setattr(delegation, "stream_model", enormous)
    monkeypatch.setattr(delegation, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    with pytest.raises(ValueError, match="limit"):
        await run_subagent("alice", run, parent, ModelToolCall("x", "delegate_agent", {
            "agent_id": child["id"], "task": "large output",
        }), db)
    with db.connect() as conn:
        row = conn.execute("SELECT status,result FROM agent_delegations").fetchone()
    assert row["status"] == "error"
    assert row["result"] == ""


@pytest.mark.asyncio
async def test_delegation_rejects_invalid_target_and_task_before_dispatch(tmp_path):
    db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    child = AgentRepository(db).create("alice", {"name": "Child", "provider": "openAI", "model": "mock"})
    run, _ = GenerationStore(db).begin("alice", {"text": "Begin"})
    parent = {"id": "parent", "subagents": [child["id"]]}
    for name, args, expected in [
        ("file_write", {"agent_id": child["id"], "task": "read"}, "Unknown"),
        ("delegate_agent", {"agent_id": child["id"]}, "identity and task"),
        ("delegate_agent", {"agent_id": child["id"], "task": ""}, "1–8192"),
        ("handoff_agent", {"agent_id": child["id"], "task": "x" * 9000}, "1–8192"),
    ]:
        with pytest.raises(ValueError, match=expected):
            await run_subagent("alice", run, parent, ModelToolCall("x", name, args), db)
    with pytest.raises(PermissionError, match="delegate to itself"):
        await run_subagent("alice", run, {"id": child["id"], "subagents": [child["id"]]},
                           ModelToolCall("x", "delegate_agent", {"agent_id": child["id"], "task": "loop"}), db)
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM agent_delegations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_delegation_cancellation_is_durable_and_never_completes(tmp_path, monkeypatch):
    import asyncio

    from local_shell_mcp.webui import delegation

    db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    child = AgentRepository(db).create("alice", {"name": "Child", "provider": "openAI", "model": "mock"})
    run, _ = GenerationStore(db).begin("alice", {"text": "Begin"})
    entered = asyncio.Event()
    held = asyncio.Event()

    async def blocked(*args, **kwargs):
        yield 42  # malformed model nontext chunks are ignored
        entered.set()
        yield "partial"
        await held.wait()
        yield "never stored"

    monkeypatch.setattr(delegation, "stream_model", blocked)
    monkeypatch.setattr(delegation, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    task = asyncio.create_task(run_subagent("alice", run, {"id": "parent", "subagents": [child["id"]]},
                   ModelToolCall("x", "delegate_agent", {"agent_id": child["id"], "task": "slow"}), db))
    await asyncio.wait_for(entered.wait(), timeout=3)
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with db.connect() as connection:
        stored = connection.execute("SELECT status,result FROM agent_delegations").fetchone()
    assert stored["status"] == "interrupted"
    assert stored["result"] == ""
