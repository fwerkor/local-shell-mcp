"""Controller management uses the native LSM registry and local write grants."""

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
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()
    _registry_for_state.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("local", {"title": "Controller management"})["conversationId"]
    yield repo, cid
    _registry_for_state.cache_clear()
    get_settings.cache_clear()


def exposed(owner, cid, scopes):
    return {item["function"]["name"] for item in available_tools(owner, cid, scopes=scopes)}


def test_administration_requires_local_write_and_matching_oauth_scopes(policy):
    repo, cid = policy
    scopes = {"shell:read", "shell:write", "shell:execute", "remote:use"}
    controller = {"mcp_manage", "remote_manage"}
    agent_control = {"session_manage", "plan_manage"}
    assert agent_control <= exposed("local", cid, set())
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"worker1": "write"})
    assert not controller & exposed("local", cid, scopes)
    assert agent_control <= exposed("local", cid, scopes)
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "read", "worker1": "write"})
    assert not controller & exposed("local", cid, scopes)
    assert agent_control <= exposed("local", cid, scopes)
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "write", "worker1": "none"})
    assert controller | agent_control <= exposed("local", cid, scopes)
    assert "mcp_manage" not in exposed("local", cid, scopes - {"shell:execute"})
    assert "remote_manage" not in exposed("local", cid, scopes - {"remote:use"})
    assert "mcp_tool_call" not in exposed("local", cid, scopes)
    original = {t.name: t for t in _registry()._tool_manager.list_tools()}
    for item in available_tools("local", cid, scopes=scopes):
        if item["function"]["name"] not in controller | agent_control:
            continue
        tool = original[item["function"]["name"]]
        assert item["function"]["description"] == tool.description[:2048]
        assert "logical_session_id" not in item["function"]["parameters"].get("properties", {})
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "none"})
    assert not controller & exposed("local", cid, scopes)
    assert agent_control <= exposed("local", cid, scopes)


@pytest.mark.asyncio
async def test_native_mcp_manage_and_remote_manage_dispatch_without_worker_grant(policy, monkeypatch):
    from local_shell_mcp import tools

    repo, cid = policy
    scopes = {"shell:read", "shell:write", "shell:execute", "remote:use"}
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    invocations = []

    class FakeNestedManager:
        def __init__(self, *args, **kwargs):
            pass

        async def manage(self, **kwargs):
            invocations.append(("mcp", kwargs))
            return {"servers": [{"name": "sample"}]}

    class FakeRemotes:
        def list_machines(self):
            invocations.append(("remote-list", {}))
            return {"machines": [{"name": "worker1"}]}

        def rename(self, machine, new_name):
            invocations.append(("remote-rename", {"machine": machine, "new_name": new_name}))
            return {"machine": new_name}

    monkeypatch.setattr(tools, "DynamicMCPManager", FakeNestedManager)
    monkeypatch.setattr(tools, "remote_manager", lambda: FakeRemotes())
    _registry_for_state.cache_clear()
    mcp = json.loads(await call_tool("local", cid,
                                     ModelToolCall("mcp1", "mcp_manage", {"action": "list"}),
                                     granted_scopes=scopes))
    assert mcp["ok"] is True
    assert mcp["data"]["servers"][0]["name"] == "sample"
    listed = json.loads(await call_tool("local", cid,
                                        ModelToolCall("remote1", "remote_manage", {"action": "list"}),
                                        granted_scopes=scopes))
    assert listed["ok"] is True
    assert listed["data"]["machines"][0]["name"] == "worker1"
    # `machine` here is a Controller registration argument, not remote RPC.
    renamed = json.loads(await call_tool("local", cid, ModelToolCall(
        "remote2", "remote_manage", {"action": "rename", "machine": "worker1", "new_name": "worker2"},
    ), granted_scopes=scopes))
    assert renamed["ok"] is True
    assert renamed["data"]["machine"] == "worker2"
    assert [name for name, _ in invocations] == ["mcp", "remote-list", "remote-rename"]
    assert invocations[-1][1] == {"machine": "worker1", "new_name": "worker2"}
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
    with pytest.raises(PermissionError, match="read-only"):
        await call_tool("local", cid, ModelToolCall("mcp2", "mcp_manage", {"action": "remove", "name": "sample"}),
                        granted_scopes=scopes)
    with pytest.raises(PermissionError, match="read-only"):
        await call_tool("local", cid, ModelToolCall("remote3", "remote_manage", {
            "action": "rename", "machine": "worker1", "new_name": "worker3",
        }), granted_scopes=scopes)
    assert len(invocations) == 3


@pytest.mark.asyncio
async def test_management_execution_enforces_scopes_expiry_and_is_owner_fenced(policy):
    repo, cid = policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    mcp = ModelToolCall("tool", "mcp_manage", {"action": "list"})
    remote = ModelToolCall("tool", "remote_manage", {"action": "list"})
    with pytest.raises(PermissionError, match="shell:execute"):
        await call_tool("local", cid, mcp, granted_scopes={"shell:read", "shell:write"})
    with pytest.raises(PermissionError, match="remote:use"):
        await call_tool("local", cid, remote, granted_scopes={"shell:read", "shell:write"})
    with pytest.raises(PermissionError, match="expired"):
        await call_tool("local", cid, mcp, granted_scopes={"shell:read", "shell:write", "shell:execute"},
                        grant_expires=1)
    with pytest.raises(KeyError, match="Conversation not found"):
        await call_tool("another", cid, mcp, granted_scopes={"shell:read", "shell:write", "shell:execute"})
    with pytest.raises(PermissionError, match="internal session"):
        await call_tool("local", cid, ModelToolCall("tool", "mcp_manage", {
            "action": "list", "logical_session_id": "forged"}),
            granted_scopes={"shell:read", "shell:write", "shell:execute"})


@pytest.mark.asyncio
async def test_registered_logical_session_management_executes_with_local_write(policy):
    repo, cid = policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    scopes = {"shell:read", "shell:write"}
    started = json.loads(await call_tool("local", cid, ModelToolCall("start", "session_manage", {
        "action": "start", "label": "Agent test", "objective": "Verify the existing session runtime",
    }), granted_scopes=scopes))
    assert started["ok"] is True
    session = started["data"]["session_id"]
    assert isinstance(session, str) and session
    try:
        inspected = json.loads(await call_tool("local", cid, ModelToolCall("plan", "plan_manage", {
            "action": "get", "session_id": session,
        }), granted_scopes=scopes))
        assert inspected["ok"] in {True, False}  # The plan may not yet exist.
    finally:
        done = json.loads(await call_tool("local", cid, ModelToolCall("cancel", "session_manage", {
            "action": "cancel", "session_id": session,
        }), granted_scopes=scopes))
        assert done["ok"] is True


@pytest.mark.asyncio
async def test_session_and_plan_management_work_without_any_machine_or_shell_scope(policy):
    repo, cid = policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {
        "local": "none", "worker1": "none",
    })
    names = exposed("local", cid, set())
    assert names == {"session_manage", "plan_manage"}
    start = json.loads(await call_tool("local", cid, ModelToolCall("create", "session_manage", {
        "action": "start", "label": "No machine privileges",
    }), granted_scopes=set()))
    assert start["ok"] is True
    sid = start["data"]["session_id"]
    try:
        plan = json.loads(await call_tool("local", cid, ModelToolCall("inspect", "plan_manage", {
            "action": "get", "session_id": sid,
        }), granted_scopes=set()))
        assert isinstance(plan, dict)
        assert "ok" in plan
        with pytest.raises(KeyError, match="Conversation not found"):
            await call_tool("bob", cid, ModelToolCall("foreign", "session_manage", {
                "action": "get", "session_id": sid,
            }), granted_scopes=set())
        with pytest.raises(PermissionError, match="expired"):
            await call_tool("local", cid, ModelToolCall("expired", "session_manage", {
                "action": "get", "session_id": sid,
            }), granted_scopes=set(), grant_expires=1)
        with pytest.raises(PermissionError, match="not granted"):
            await call_tool("local", cid, ModelToolCall("shell", "job_list", {"limit": 1}),
                            granted_scopes={"shell:read"})
        with pytest.raises(PermissionError, match="not granted"):
            await call_tool("local", cid, ModelToolCall("registry", "mcp_manage", {
                "action": "list",
            }), granted_scopes={"shell:read", "shell:write", "shell:execute"})
    finally:
        cancelled = json.loads(await call_tool("local", cid, ModelToolCall("close", "session_manage", {
            "action": "cancel", "session_id": sid,
        }), granted_scopes=set()))
        assert cancelled["ok"] is True
