"""Agent-native machine ACL boundary and external MCP registry view."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import agent_routes
from local_shell_mcp.webui import lsm_tool_registry as registry
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo

SCOPES = {"shell:read", "shell:write", "shell:execute", "remote:use"}


@pytest.fixture
def machine_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "local_shell_mcp.webui.machine_permissions._registered_defaults",
        lambda: {"local": "write", "worker1": "write"},
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()
    registry._registry_for_state.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("local", {"title": "Scoped agent"})["conversationId"]
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "write", "worker1": "read"})
    agents = AgentRepository(repo.database)
    agent = agents.create("local", {"name": "Scoped", "provider": "openAI",
                                    "model": "test", "machine_permissions": {
                                        "local": "read", "worker1": "write",
                                    }})
    yield repo, cid, agents, agent
    registry._registry_for_state.cache_clear()
    get_settings.cache_clear()


def test_agent_machine_permissions_validate_persist_and_bound_tools(machine_agent):
    _, cid, agents, agent = machine_agent
    assert agent["machine_permissions"] == {"local": "read", "worker1": "write"}
    tools = registry.available_tools("local", cid, scopes=SCOPES,
                                     agent_permissions=agent["machine_permissions"])
    names = {tool["function"]["name"] for tool in tools}
    assert {"file_read", "file_list", "session_manage", "plan_manage"} <= names
    assert not {"file_write", "run_shell", "shell_start", "mcp_manage"} & names

    none = registry.available_tools("local", cid, scopes=SCOPES, agent_permissions={})
    assert {"file_read", "file_write", "session_manage", "plan_manage"} <= {
        tool["function"]["name"] for tool in none
    }

    with pytest.raises(ValueError):
        agents.update("local", agent["id"], {"machine_permissions": {"*": "write"}})
    assert agents.get("local", agent["id"])["machine_permissions"]["local"] == "read"
    updated = agents.update("local", agent["id"], {"machine_permissions": {"local": "write"}})
    assert updated["machine_permissions"] == {"local": "write"}


def test_agent_runner_automatically_exposes_machine_scoped_tools(machine_agent):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    repo, _, _, agent = machine_agent
    store = GenerationStore(repo.database)
    generation, _ = store.begin("local", {"text": "Use native tools"}, agent)
    repo.save_setting("local", "agent.machine_policy.conversation." + generation.conversation_id,
                      {"local": "write", "worker1": "read"})
    profile = ProviderConfig("openai", "test", "https://test.invalid", "")
    runner = AgentRunner(
        "local", generation, repo.database, store, scopes=SCOPES, grant_expires=None,
        stream_tools=None, stream_text=None, on_text=None, profile=profile, agent=agent,
    )
    context = runner._context(agent, profile=profile)
    exposed = {item["function"]["name"] for item in context.tools}
    assert "file_read" in exposed
    assert "file_write" not in exposed
    # A child with an explicit tool subset must not inherit all of its parent's
    # native capabilities merely because the parent has a machine ACL.
    restricted = runner._context(agent, profile=profile, selected_tools=[])
    assert {item["function"]["name"] for item in restricted.tools} == {
        "session_manage", "plan_manage", "web_search", "web_fetch",
    }
    runner.web_search_enabled = False
    restricted = runner._context(agent, profile=profile, selected_tools=[])
    assert {item["function"]["name"] for item in restricted.tools} == {"session_manage", "plan_manage"}


@pytest.mark.asyncio
async def test_machine_acl_enforced_on_dispatch_and_revocation(machine_agent, monkeypatch):
    _, cid, agents, agent = machine_agent
    invoked = []

    async def invoke(*args, **kwargs):
        invoked.append(args)
        return '{"ok": true}'

    monkeypatch.setattr(registry, "_invoke_registered", invoke)

    async def call(name, args):
        return await registry.call_tool(
            "local", cid, ModelToolCall("test", name, args),
            granted_scopes=SCOPES, agent_id=agent["id"],
        )

    assert await call("file_read", {"machine": "local", "path": "test.txt"}) == '{"ok": true}'
    with pytest.raises(PermissionError, match="Agent has no write"):
        await call("file_write", {"machine": "local", "path": "a.txt", "content": "x"})
    with pytest.raises(PermissionError, match="read-only"):
        await call("file_write", {"machine": "worker1", "path": "a.txt", "content": "x"})
    agents.update("local", agent["id"], {"machine_permissions": {"local": "none"}})
    with pytest.raises(PermissionError, match="Agent has no read"):
        await call("file_read", {"machine": "local", "path": "test.txt"})
    assert len(invoked) == 1


@pytest.mark.asyncio
async def test_inflight_native_tool_rechecks_agent_acl(machine_agent, monkeypatch):
    _, cid, agents, agent = machine_agent
    started = asyncio.Event()
    finished = False

    async def invoke(*args, **kwargs):
        nonlocal finished
        started.set()
        await asyncio.sleep(2)
        finished = True
        return '{"ok": true}'

    monkeypatch.setattr(registry, "_invoke_registered", invoke)
    task = asyncio.create_task(registry.call_tool(
        "local", cid, ModelToolCall("long", "file_read", {"path": "test.txt"}),
        granted_scopes=SCOPES, agent_id=agent["id"],
    ))
    await asyncio.wait_for(started.wait(), 1)
    agents.update("local", agent["id"], {"machine_permissions": {"local": "none"}})
    with pytest.raises(PermissionError, match="Agent has no read"):
        await asyncio.wait_for(task, 2)
    assert not finished


@pytest.mark.asyncio
async def test_external_mcp_list_strips_connection_secrets(machine_agent, monkeypatch):
    from local_shell_mcp.dynamic_mcp import DynamicMCPManager

    async def fake_list(self, *, action, **kwargs):
        assert action == "list"
        return {"servers": [{"name": "external-one", "transport": "streamable_http",
                             "enabled": True, "tool_count": 8,
                             "command": "sensitive", "headers": {"Authorization": "secret"},
                             "url": "http://private.example/secret"}]}

    monkeypatch.setattr(DynamicMCPManager, "manage", fake_list)
    app = Starlette(routes=agent_routes.agent_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        response = await client.get("/api/lsm/mcp/servers")
        assert response.status_code == 200, response.text
        servers = response.json()["servers"]
        assert servers == [{"name": "external-one", "transport": "streamable_http",
                            "enabled": True, "tool_count": 8}]
        response = await client.get("/api/agents/tools")
        assert response.status_code == 200
        assert all(item["pluginKey"] not in {"file_read", "file_write"}
                   for item in response.json())


def test_durable_task_lease_tracks_agent_and_revokes_machine_changes(machine_agent):
    from local_shell_mcp.webui import durable_tasks as durable

    repo, cid, agents, agent = machine_agent
    with repo.database.connect() as db:
        db.execute("INSERT INTO runs(id,conversation_id,status,state,created_at,updated_at) "
                   "VALUES('agent-run',?,'running','{}',1,1)", (cid,))
    agents.update("local", agent["id"], {"machine_permissions": {"local": "write"}})
    intent = durable.reserve("local", cid, "agent-run", "lease-1", "job_start",
                            {"command": "echo ok"}, SCOPES, None, agent_id=agent["id"])
    with repo.database.connect() as db:
        row = db.execute("SELECT agent_id,state FROM agent_durable_tasks WHERE id=?", (intent.id,)).fetchone()
        assert row["agent_id"] == agent["id"] and row["state"] == "reserved"
    assert durable.mark_revoked("local") == 0
    with pytest.raises(PermissionError, match="another Agent"):
        durable.reserve("local", cid, "agent-run", "lease-1", "job_start",
                        {"command": "echo ok"}, SCOPES, None, agent_id="other-agent")
    agents.update("local", agent["id"], {"machine_permissions": {"local": "none"}})
    assert durable.mark_revoked("local") == 1
    with repo.database.connect() as db:
        assert db.execute("SELECT state FROM agent_durable_tasks WHERE id=?", (intent.id,)).fetchone()[0] == "cancel_pending"


def test_durable_task_lease_revokes_deleted_agent(machine_agent):
    from local_shell_mcp.webui import durable_tasks as durable

    repo, cid, agents, agent = machine_agent
    with repo.database.connect() as db:
        db.execute("INSERT INTO runs(id,conversation_id,status,state,created_at,updated_at) "
                   "VALUES('deleted-agent-run',?,'running','{}',1,1)", (cid,))
    intent = durable.reserve("local", cid, "deleted-agent-run", "lease-2", "job_start",
                            {"command": "echo ok"}, SCOPES, None, agent_id=agent["id"])
    agents.delete("local", agent["id"])
    assert durable.mark_revoked("local") == 1
    with pytest.raises(PermissionError, match="revoked"):
        durable.check_intent(intent)


@pytest.mark.asyncio
async def test_detached_native_execution_keeps_agent_identity(machine_agent, monkeypatch):
    from types import SimpleNamespace

    from local_shell_mcp.webui import background_tools
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    repo, cid, _, agent = machine_agent
    store = GenerationStore(repo.database)
    generation, _ = store.begin("local", {"text": "Background"}, agent)
    profile = ProviderConfig("openai", "test", "https://test.invalid", "")
    runner = AgentRunner(
        "local", generation, repo.database, store, scopes=SCOPES, grant_expires=None,
        stream_tools=None, stream_text=None, on_text=None, profile=profile, agent=agent,
    )
    runner._injected_background_names[agent["id"]] = frozenset({"run_shell"})
    exposed = [{"function": {"name": "run_shell", "parameters": {"properties": {
        "run_in_background": {"type": "boolean"},
    }}}}]
    state = SimpleNamespace(context=SimpleNamespace(tools=exposed, agent=agent))
    recorded = {}

    async def fake_native(owner, conversation_id, call, **kwargs):
        recorded.update(kwargs)
        recorded["arguments"] = call.arguments
        return '{"ok":true}'

    async def fake_start(*args, scopes, grant_expires, dispatch, **kwargs):
        return await dispatch(args[5], scopes, grant_expires, args[3])

    monkeypatch.setattr(registry, "call_tool", fake_native)
    monkeypatch.setattr(background_tools, "start_tool_task", fake_start)
    result = await runner._invoke(ModelToolCall("bg-1", "run_shell", {
        "command": "echo hi", "run_in_background": True,
    }), state)
    assert result == '{"ok":true}'
    assert recorded["agent_id"] == agent["id"]
    assert "run_in_background" not in recorded["arguments"]


def test_external_mcp_available_without_machine_policy(machine_agent):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    repo, _, agents, _ = machine_agent
    legacy = agents.create("local", {"name": "External only", "provider": "openAI",
                                      "model": "test", "tools": []})
    store = GenerationStore(repo.database)
    generation, _ = store.begin("local", {"text": "External MCP"}, legacy)
    profile = ProviderConfig("openai", "test", "https://test.invalid", "")
    runner = AgentRunner(
        "local", generation, repo.database, store, scopes=SCOPES, grant_expires=None,
        stream_tools=None, stream_text=None, on_text=None, profile=profile,
        agent=legacy, mcp_enabled=True,
    )
    context = runner._context(legacy, profile=profile)
    names = {item["function"]["name"] for item in context.tools}
    assert {"mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call"} <= names
    assert "file_write" not in names  # No implicit migration of legacy tool grants.


@pytest.mark.asyncio
async def test_subagent_machine_policy_is_not_replaced_by_empty_legacy_list(machine_agent):
    from local_shell_mcp.webui.subagents import SubagentConfig, invoke_subagent

    repo, cid, _, agent = machine_agent
    observed = []

    async def child(invocation):
        observed.append(invocation.selected_tools)
        return "completed"

    config = SubagentConfig(type="worker", name="worker", description="worker", agent=agent,
                            max_turns=5, owner="local")
    await invoke_subagent(
        ModelToolCall("delegated", "subagent", {"subagent_type": "worker", "description": "test"}),
        [config], execute_child=child, owner="local", conversation_id=cid,
        parent_run_id="test-run", database=repo.database, scopes=frozenset(SCOPES),
        grant_expires=None,
    )
    assert observed == [None]
