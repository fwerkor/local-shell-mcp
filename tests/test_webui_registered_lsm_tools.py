"""Agent access uses the existing LSM MCP schemas and original executors."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.lsm_tool_registry import (
    _registry,
    _registry_for_state,
    available_tools,
    call_tool,
)
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo


@pytest.fixture
def enabled_machine_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()
    _registry_for_state.cache_clear()
    repository = _repo()
    cid = repository.create_conversation("local", {"title": "Native registered tools"})["conversationId"]
    yield repository, cid, tmp_path
    _registry_for_state.cache_clear()
    get_settings.cache_clear()


def test_schema_is_original_mcp_schema_without_internal_context(enabled_machine_policy):
    repo, cid, _ = enabled_machine_policy
    assert {t["function"]["name"] for t in available_tools(
        "local", cid, scopes={"shell:read", "shell:write", "shell:execute"},
    )} == {"session_manage", "plan_manage"}
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
    result = available_tools("local", cid, scopes={"shell:read"})
    advertised = {row["function"]["name"]: row["function"] for row in result}
    existing = {tool.name: tool for tool in _registry()._tool_manager.list_tools()}
    assert {"job_list", "job_get", "job_tail", "file_list", "file_tree", "file_grep",
            "file_read", "environment_get", "shell_read", "shell_list"} <= set(advertised)
    assert "run_shell" not in advertised
    assert "job_start" not in advertised
    assert "file_write" not in advertised
    assert "mcp_manage" not in advertised
    assert "remote_manage" not in advertised
    assert "mcp_tool_call" not in advertised
    for name in ("job_list", "job_tail", "file_read", "file_grep"):
        schema = advertised[name]["parameters"]
        original = existing[name].parameters
        assert advertised[name]["description"] == existing[name].description[:2048]
        assert schema["properties"]["machine"] == original["properties"]["machine"]
        assert "logical_session_id" not in schema.get("properties", {})
        assert "logical_session_id" not in schema.get("required", [])
        assert schema["properties"]["job_id"] == original["properties"]["job_id"] if name == "job_tail" else True

    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    writable = {row["function"]["name"] for row in available_tools(
        "local", cid, scopes={"shell:read", "shell:write", "shell:execute"},
    )}
    assert {"run_shell", "run_python", "job_start", "job_stop", "job_retry",
            "file_write", "file_edit", "file_delete", "file_patch",
            "shell_start", "shell_send", "shell_stop"} <= writable
    assert {"mcp_manage", "session_manage", "plan_manage"} <= writable
    assert "remote_manage" not in writable  # remote:use OAuth scope required
    assert "mcp_tool_call" not in writable


@pytest.mark.asyncio
async def test_actual_mcp_file_tool_and_original_job_function(enabled_machine_policy, monkeypatch):
    from local_shell_mcp import tools

    repo, cid, workspace = enabled_machine_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
    (workspace / "file.txt").write_text("Original LSM file_read text", encoding="utf-8")
    contents = json.loads(await call_tool(
        "local", cid, ModelToolCall("read-1", "file_read", {"path": "file.txt", "machine": "local"}),
        granted_scopes={"shell:read"},
    ))
    assert contents.get("ok") is True, contents
    assert "Original LSM file_read text" in str(contents["data"])

    calls = []

    async def fake_get_job(job_id):
        calls.append(job_id)
        return {"job": {"job_id": job_id, "status": "running", "original": True}}

    monkeypatch.setattr(tools, "get_job", fake_get_job)
    meta = json.loads(await call_tool(
        "local", cid, ModelToolCall("metadata", "job_get", {"job_id": "real-id"}),
        granted_scopes={"shell:read"},
    ))
    assert calls == ["real-id"]
    assert meta["data"]["job"]["original"] is True
    with pytest.raises(PermissionError, match="read-only"):
        await call_tool("local", cid, ModelToolCall("mutate", "job_start", {"command": "echo demo"}),
                        granted_scopes={"shell:read", "shell:execute", "shell:write"})


@pytest.mark.asyncio
async def test_local_alias_does_not_route_to_a_remote_worker(enabled_machine_policy, monkeypatch):
    from local_shell_mcp import tools

    repo, cid, _ = enabled_machine_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {
        "local": "write", "worker1": "read",
    })
    local_calls = []
    remote_calls = []

    async def fake_start_job(command, cwd=".", name=None, idempotency_key=None):
        local_calls.append((command, cwd, name, idempotency_key))
        return {"job_id": "local-started", "kind": "shell"}

    async def fake_remote(settings, machine, tool, args, **kwargs):
        remote_calls.append((machine, tool, args))
        return {"ok": True, "data": {"job": {"job_id": "remote-job"}}}

    monkeypatch.setattr(tools, "start_job", fake_start_job)
    monkeypatch.setattr(tools, "_remote_call", fake_remote)
    result = json.loads(await call_tool(
        "local", cid,
        ModelToolCall("start", "job_start", {"command": "echo test", "machine": "local"}),
        granted_scopes={"shell:read", "shell:write", "shell:execute"},
    ))
    assert result["data"]["job_id"] == "local-started"
    assert local_calls == [("echo test", ".", None, None)]
    assert remote_calls == []
    metadata = json.loads(await call_tool(
        "local", cid, ModelToolCall("tail", "job_get", {"machine": "worker1", "job_id": "j1"}),
        granted_scopes={"shell:read", "remote:use"},
    ))
    assert metadata["data"]["job"]["job_id"] == "remote-job"
    assert remote_calls[0][0:2] == ("worker1", "job_get")
    with pytest.raises(PermissionError, match="read-only"):
        await call_tool("local", cid, ModelToolCall("bad", "job_start", {
            "machine": "worker1", "command": "echo no",
        }), granted_scopes={"shell:read", "shell:write", "shell:execute", "remote:use"})
    assert len(remote_calls) == 1


@pytest.mark.asyncio
async def test_original_tool_calls_are_fenced_by_scopes_and_revocation(enabled_machine_policy):
    repo, cid, workspace = enabled_machine_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    read = ModelToolCall("call1", "job_list", {"limit": 1})
    write = ModelToolCall("call2", "file_write", {"path": "blocked.txt", "content": "No"})
    with pytest.raises(PermissionError, match="shell:read"):
        await call_tool("local", cid, read, granted_scopes=set())
    with pytest.raises(PermissionError, match="shell:write"):
        await call_tool("local", cid, write, granted_scopes={"shell:read"})
    with pytest.raises(PermissionError, match="expired"):
        await call_tool("local", cid, write, granted_scopes={"shell:read", "shell:write"},
                        grant_expires=1)
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "none"})
    with pytest.raises(PermissionError, match="not granted"):
        await call_tool("local", cid, write,
                        granted_scopes={"shell:read", "shell:write", "shell:execute"})
    assert not (workspace / "blocked.txt").exists()
    with pytest.raises(PermissionError, match="not granted"):
        await call_tool("local", cid, ModelToolCall("admin", "mcp_manage", {"action": "list"}),
                        granted_scopes={"shell:read", "shell:write", "shell:execute"})
    with pytest.raises(PermissionError, match="internal session"):
        repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
        await call_tool("local", cid, ModelToolCall("escape", "job_list", {
            "logical_session_id": "forged-session",
        }), granted_scopes={"shell:read"})


@pytest.mark.asyncio
async def test_read_only_local_and_remote_job_tail_uses_existing_registered_rpc(
    enabled_machine_policy, monkeypatch,
):
    from local_shell_mcp import tools

    repo, cid, _ = enabled_machine_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {
        "local": "read", "worker1": "read",
    })
    dispatched = []

    async def fake_local_tail(job_id, lines):
        dispatched.append(("local", "job_tail", job_id, lines))
        return {"job": {"job_id": job_id}, "output": "training in progress"}

    async def fake_remote(settings, machine, tool, args, **kwargs):
        dispatched.append((machine, tool, args["job_id"], args["lines"]))
        return {"ok": True, "data": {"job": {"job_id": args["job_id"]}, "output": "remote training"}}

    monkeypatch.setattr(tools, "tail_job", fake_local_tail)
    monkeypatch.setattr(tools, "_remote_call", fake_remote)
    scopes = {"shell:read", "remote:use"}
    a = json.loads(await call_tool("local", cid, ModelToolCall("1", "job_tail", {
        "machine": "local", "job_id": "job-test", "lines": 25,
    }), granted_scopes=scopes))
    b = json.loads(await call_tool("local", cid, ModelToolCall("2", "job_tail", {
        "machine": "worker1", "job_id": "job-other", "lines": 5,
    }), granted_scopes=scopes))
    assert "training in progress" in str(a)
    assert "remote training" in str(b)
    assert dispatched == [("local", "job_tail", "job-test", 25),
                          ("worker1", "job_tail", "job-other", 5)]
    with pytest.raises(PermissionError, match="read-only"):
        await call_tool("local", cid, ModelToolCall("3", "job_start", {
            "machine": "worker1", "command": "echo forbidden",
        }), granted_scopes={"shell:read", "shell:write", "shell:execute", "remote:use"})
    assert len(dispatched) == 2


@pytest.mark.asyncio
async def test_existing_file_write_uses_its_original_validation_and_scope(
    enabled_machine_policy,
):
    repo, cid, workspace = enabled_machine_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
    call = ModelToolCall("write", "file_write", {
        "path": "notes.txt", "content": "Written via registered LSM implementation",
    })
    with pytest.raises(PermissionError, match="read-only"):
        await call_tool("local", cid, call, granted_scopes={"shell:read", "shell:write"})
    assert not (workspace / "notes.txt").exists()
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    response = json.loads(await call_tool("local", cid, call, granted_scopes={"shell:read", "shell:write"}))
    assert response["ok"] is True
    assert (workspace / "notes.txt").read_text() == "Written via registered LSM implementation"
    with pytest.raises(PermissionError, match="remote:use"):
        await call_tool("local", cid, ModelToolCall("admin", "remote_manage", {"action": "revoke"}),
                        granted_scopes={"shell:read", "shell:write"})


@pytest.mark.asyncio
async def test_transfer_enforces_both_source_and_destination_machine_policy(
    enabled_machine_policy, monkeypatch,
):
    from local_shell_mcp import tools

    repo, cid, _ = enabled_machine_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {
        "local": "read", "worker1": "read",
    })
    transferred = []

    async def fake_transfer(*args, **kwargs):
        transferred.append((args, kwargs))
        return {"job_id": "transfer-1"}

    monkeypatch.setattr(tools, "_start_transfer_job", fake_transfer)
    payload = {"source_path": "readme.md", "destination_path": "readme.md",
               "source_machine": "local", "destination_machine": "worker1"}
    with pytest.raises(PermissionError, match="read-only"):
        await call_tool("local", cid, ModelToolCall("transfer", "remote_transfer", payload),
                        granted_scopes={"shell:read", "shell:write", "remote:use"})
    assert transferred == []
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {
        "local": "read", "worker1": "write",
    })
    assert "remote_transfer" in {row["function"]["name"] for row in available_tools(
        "local", cid, scopes={"shell:read", "shell:write", "remote:use"},
    )}
    result = json.loads(await call_tool("local", cid, ModelToolCall("transfer", "remote_transfer", payload),
                                        granted_scopes={"shell:read", "shell:write", "remote:use"}))
    assert result["data"]["job_id"] == "transfer-1"
    assert len(transferred) == 1
    assert transferred[0][0][2] is None  # Controller-local endpoint, not a remote worker.
    assert transferred[0][0][3] == "worker1"
    with pytest.raises(PermissionError, match="remote:use"):
        await call_tool("local", cid, ModelToolCall("transfer", "remote_transfer", payload),
                        granted_scopes={"shell:read", "shell:write"})
    assert len(transferred) == 1


@pytest.mark.asyncio
async def test_original_mcp_audit_identity_uses_chat_owner_and_restores_context(
    enabled_machine_policy, monkeypatch,
):
    from local_shell_mcp import tools
    from local_shell_mcp.auth import _CURRENT_PRINCIPAL, Principal, current_principal

    repo, cid, _ = enabled_machine_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
    subjects = []

    async def fake_get_job(job_id):
        principal = current_principal()
        subjects.append((principal.subject, principal.claims.get("scope")))
        return {"job": {"job_id": job_id}}

    monkeypatch.setattr(tools, "get_job", fake_get_job)
    outer = _CURRENT_PRINCIPAL.set(Principal(
        email="existing@example.test", subject="outer-request",
        claims={"auth": "oauth", "scope": "shell:read shell:write"},
    ))
    try:
        data = json.loads(await call_tool(
            "local", cid, ModelToolCall("1", "job_get", {"job_id": "job-1"}),
            granted_scopes={"shell:read"},
        ))
        assert data["ok"]
        assert subjects == [("local", "shell:read")]
        assert current_principal().subject == "outer-request"
    finally:
        _CURRENT_PRINCIPAL.reset(outer)


@pytest.mark.asyncio
async def test_oauth_read_only_grant_uses_existing_mcp_tools_without_all_public_scopes(
    tmp_path, monkeypatch,
):
    """Public MCP requires bundled scopes; Agent checks the frozen limited grant."""
    from local_shell_mcp.auth import _CURRENT_PRINCIPAL, Principal
    from local_shell_mcp.tools import build_mcp

    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    _registry_for_state.cache_clear()
    repository = _repo()
    conversation = repository.create_conversation("alice", {"title": "Read-only OAuth"})["conversationId"]
    repository.save_setting("alice", "agent.machine_policy.conversation." + conversation, {"local": "read"})
    (tmp_path / "readme.txt").write_text("OAuth read-only access")
    try:
        read = json.loads(await call_tool(
            "alice", conversation, ModelToolCall("read", "file_read", {"path": "readme.txt"}),
            granted_scopes={"shell:read"},
        ))
        assert read.get("ok") is True, read
        assert "OAuth read-only access" in str(read["data"])
        job = json.loads(await call_tool(
            "alice", conversation, ModelToolCall("jobs", "job_list", {"limit": 1}),
            granted_scopes={"shell:read"},
        ))
        assert job["ok"] is True
        with pytest.raises(PermissionError, match="read-only"):
            await call_tool("alice", conversation, ModelToolCall("write", "file_write", {
                "path": "deny.txt", "content": "Not allowed",
            }), granted_scopes={"shell:read"})
        with pytest.raises(PermissionError, match="read-only"):
            await call_tool("alice", conversation, ModelToolCall("shell", "run_shell", {
                "command": "echo forbidden",
            }), granted_scopes={"shell:read"})
        assert not (tmp_path / "deny.txt").exists()
        # Ordinary public MCP still demands its advertised scope bundle.
        regular = build_mcp()
        token = _CURRENT_PRINCIPAL.set(Principal(
            email=None, subject="alice", claims={"auth": "oauth", "scope": "shell:read"},
        ))
        try:
            from mcp.server.fastmcp.exceptions import ToolError
            with pytest.raises(ToolError, match="missing required"):
                await regular._tool_manager.call_tool("job_list", {"limit": 1}, convert_result=True)
        finally:
            _CURRENT_PRINCIPAL.reset(token)
    finally:
        _registry_for_state.cache_clear()
        get_settings.cache_clear()
