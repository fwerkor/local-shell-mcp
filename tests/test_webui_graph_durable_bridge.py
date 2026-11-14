"""Integration: source Graph child run identity versus inherited parent machine ACL."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import durable_tasks
from local_shell_mcp.webui import lsm_tool_registry as native
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo


@pytest.mark.asyncio
async def test_child_native_job_records_actual_run_but_obeys_parent_conversation_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "sqlite")
    get_settings.cache_clear()
    repository = _repo()
    root = repository.create_conversation("owner", {"title": "root"})["conversationId"]
    child = repository.create_conversation("owner", {"title": "child"})["conversationId"]
    repository.save_setting("owner", "agent.machine_policy.conversation." + root, {"local": "write"})
    repository.save_setting("owner", "agent.machine_policy.conversation." + child, {"local": "none"})
    generation, _ = GenerationStore(repository.database).begin("owner", {
        "conversationId": child, "text": "delegate a job"})
    monkeypatch.setattr(native, "_tool", lambda name: SimpleNamespace(
        name=name, parameters={"properties": {"machine": {"type": "string"}}}))
    invocations = []

    async def fake_native(owner, conversation_id, name, arguments, **kwargs):
        invocations.append((owner, conversation_id, name, arguments, kwargs))
        return json.dumps({"ok": True})

    monkeypatch.setattr(native, "_invoke_registered", fake_native)
    call = ModelToolCall("tool-call-1", "job_start", {"command": "echo authorized"})
    scopes = {"shell:read", "shell:write", "shell:execute"}
    with pytest.raises(PermissionError, match="Access to machine"):
        await native.call_tool("owner", child, call, granted_scopes=scopes,
                               run_id=generation.run_id)
    assert await native.call_tool("owner", child, call, granted_scopes=scopes,
                                  run_id=generation.run_id,
                                  authorization_conversation_id=root) == '{"ok": true}'
    with repository.database.connect() as conn:
        saved = conn.execute("SELECT * FROM agent_durable_tasks").fetchone()
        assert (saved["conversation_id"], saved["run_id"], saved["owner"], saved["state"]) == (
            child, generation.run_id, "owner", "reserved")
        assert saved["authorization_conversation_id"] == root
        assert durable_tasks._revoked(dict(saved)) is False
    assert invocations[0][1] == child  # Child owns native execution identity
    repository.save_setting("owner", "agent.machine_policy.conversation." + root, {"local": "none"})
    with pytest.raises(PermissionError, match="Access to machine"):
        await native.call_tool("owner", child, ModelToolCall("tool-call-2", "job_start", {
            "command": "echo revoked"}), granted_scopes=scopes,
            run_id=generation.run_id, authorization_conversation_id=root)
    assert len(invocations) == 1
    assert durable_tasks.mark_revoked("owner") == 1
    with repository.database.connect() as conn:
        assert conn.execute("SELECT state FROM agent_durable_tasks").fetchone()[0] == "cancel_pending"
    get_settings.cache_clear()


def test_existing_pre_graph_durable_job_table_migrates_in_place(tmp_path):
    import sqlite3

    from local_shell_mcp.sqlite_store import SQLiteDatabase

    state_dir = tmp_path / ".local-shell-mcp"
    state_dir.mkdir()
    with sqlite3.connect(state_dir / "lsm.sqlite3") as conn:
        conn.execute("CREATE TABLE agent_durable_tasks ("
                     "id TEXT PRIMARY KEY,owner TEXT NOT NULL,conversation_id TEXT NOT NULL,"
                     "run_id TEXT,call_id TEXT NOT NULL,tool TEXT NOT NULL,kind TEXT NOT NULL,"
                     "machine TEXT NOT NULL,requirements TEXT NOT NULL,fingerprint TEXT NOT NULL,"
                     "idempotency_key TEXT,key_hash TEXT,scopes TEXT NOT NULL,grant_expires INTEGER,"
                     "native_id TEXT,state TEXT NOT NULL,created_at INTEGER NOT NULL,"
                     "updated_at INTEGER NOT NULL,next_attempt_at INTEGER,last_error TEXT)")
    db = SQLiteDatabase(state_dir)
    with db.connect() as conn:
        names = [row["name"] for row in conn.execute("PRAGMA table_info(agent_durable_tasks)")]
        assert "authorization_conversation_id" in names
    # A second parallel-safe schema initialization must not duplicate ALTER.
    again = SQLiteDatabase(state_dir)
    with again.connect() as conn:
        assert [row["name"] for row in conn.execute("PRAGMA table_info(agent_durable_tasks)")].count(
            "authorization_conversation_id") == 1
