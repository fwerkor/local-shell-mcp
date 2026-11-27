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
        "session_manage", "plan_manage", "web_search", "web_fetch", "sleep",
    }
    runner.web_search_enabled = False
    restricted = runner._context(agent, profile=profile, selected_tools=[])
    assert {item["function"]["name"] for item in restricted.tools} == {"session_manage", "plan_manage", "sleep"}


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
    with pytest.raises(registry.ToolPermissionDenied, match="read-only"):
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


@pytest.mark.parametrize(("mcp_config", "expected"), [
    ({}, False), ({"mcp_servers": []}, False),
    ({"mcp_servers": ["external-one"]}, True), ({"mcp_servers": None}, True),
])
def test_external_mcp_available_without_machine_policy(machine_agent, mcp_config, expected):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    repo, _, agents, _ = machine_agent
    legacy = agents.create("local", {"name": "External only", "provider": "openAI",
                                      "model": "test", "tools": ["file_read"], **mcp_config})
    store = GenerationStore(repo.database)
    generation, _ = store.begin("local", {"text": "External MCP"}, legacy)
    profile = ProviderConfig("openai", "test", "https://test.invalid", "")
    runner = AgentRunner(
        "local", generation, repo.database, store, scopes=SCOPES, grant_expires=None,
        stream_tools=None, stream_text=None, on_text=None, profile=profile,
        agent=legacy, mcp_enabled=True,
    )
    for selected in (None, ("file_read",)):
        context = runner._context(legacy, profile=profile, selected_tools=selected)
        names = {item["function"]["name"] for item in context.tools}
        assert ({"mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call"} <= names) is expected
        assert "file_read" in names
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

@pytest.mark.asyncio
async def test_agent_default_machine_permission_inheritance(machine_agent, monkeypatch):
    _, cid, agents, agent = machine_agent
    from local_shell_mcp.webui.machine_permissions import agent_access_policy

    updated = agents.update("local", agent["id"], {
        "machine_permissions": {"local": "write"},
        "machine_default_permission": "none",
    })
    assert agent_access_policy(updated) == ({"local": "write"}, "none")
    for invalid in ("global", "*", None, []):
        with pytest.raises(ValueError):
            agents.update("local", agent["id"], {"machine_default_permission": invalid})
    monkeypatch.setattr(
        "local_shell_mcp.webui.machine_permissions._registered_defaults",
        lambda: {"local": "write", "worker1": "write", "new-worker": "write"},
    )
    async def invoke(*args, **kwargs):
        return '{"ok":true}'
    monkeypatch.setattr(registry, "_invoke_registered", invoke)

    async def call(name, machine, **kwargs):
        return await registry.call_tool(
            "local", cid, ModelToolCall("default-test", name, {"machine": machine, **kwargs}),
            granted_scopes=SCOPES, agent_id=agent["id"],
        )

    with pytest.raises(PermissionError, match="Agent has no read"):
        await call("file_read", "new-worker", path="file.txt")
    assert await call("file_read", "local", path="file.txt") == '{"ok":true}'
    agents.update("local", agent["id"], {"machine_default_permission": "read"})
    assert await call("file_read", "new-worker", path="file.txt") == '{"ok":true}'
    with pytest.raises(registry.ToolPermissionDenied, match="read-only"):
        await call("file_write", "new-worker", path="file.txt", content="x")
    agents.update("local", agent["id"], {"machine_default_permission": "write"})
    with pytest.raises(PermissionError, match="read-only"):
        await call("file_write", "worker1", path="file.txt", content="x")
    with pytest.raises(PermissionError, match="not granted"):
        await call("file_read", "unknown", path="file.txt")
    assert await call("file_write", "new-worker", path="file.txt", content="x") == '{"ok":true}'


def test_default_machine_permission_filters_tools_and_revokes_jobs(machine_agent):
    from local_shell_mcp.webui import durable_tasks as durable

    repo, cid, agents, agent = machine_agent
    with repo.database.connect() as db:
        db.execute("INSERT INTO runs(id,conversation_id,status,state,created_at,updated_at) "
                   "VALUES('default-run',?,'running','{}',1,1)", (cid,))
    agents.update("local", agent["id"], {
        "machine_permissions": {}, "machine_default_permission": "write",
    })
    intent = durable.reserve("local", cid, "default-run", "default-lease", "job_start",
                            {"command": "echo ok"}, SCOPES, None, agent_id=agent["id"])
    assert durable.mark_revoked("local") == 0
    agents.update("local", agent["id"], {"machine_default_permission": "none"})
    assert durable.mark_revoked("local") == 1
    with pytest.raises(PermissionError, match="revoked"):
        durable.check_intent(intent)
    for default, readable, writable in [("none", False, False), ("read", True, False), ("write", True, True)]:
        tools = registry.available_tools("local", cid, scopes=SCOPES, agent_permissions={},
                                         agent_default_permission=default)
        names = {tool["function"]["name"] for tool in tools}
        assert ("file_read" in names) is readable
        assert ("file_write" in names) is writable
        assert {"session_manage", "plan_manage"} <= names


def test_live_machine_context_is_provider_only(machine_agent):
    from types import SimpleNamespace

    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    repo, _, agents, agent = machine_agent
    store = GenerationStore(repo.database)
    generation, _ = store.begin("local", {"text": "Inspect"}, agent)
    cid = generation.conversation_id
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "write", "worker1": "none"})
    profile = ProviderConfig("openai", "test", "https://test.invalid", "")
    runner = AgentRunner(
        "local", generation, repo.database, store, scopes=SCOPES, grant_expires=None,
        stream_tools=None, stream_text=None, on_text=None, profile=profile, agent=agent,
    )
    history = [{"role": "system", "content": "Custom instructions"},
               {"role": "user", "content": "Inspect"}]
    state = SimpleNamespace(messages=history, context=SimpleNamespace(agent=agent))
    projected = runner._project_model_messages(state)
    assert projected[0]["role"] == "system"
    assert "Read-only: local" in projected[0]["content"]
    assert "No access: worker1" in projected[0]["content"]
    assert projected[1] == runner._conversation_context()[0]
    assert projected[2:] == history
    assert len(history) == 2

    # Edits to both ceilings must take effect even with the original Agent
    # object and canonical history still held by the running graph.
    agents.update("local", agent["id"], {"machine_permissions": {}})
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {})
    assert runner._project_model_messages(state) == [*runner._conversation_context(), *history]

    agents.update("local", agent["id"], {"machine_default_permission": "read"})
    projected = runner._project_model_messages(state)
    assert "Read-only: local, worker1" in projected[0]["content"]
    assert "Agent default for newly registered machines: read-only" in projected[0]["content"]
    assert len(history) == 2


def test_machine_context_respects_principal_scopes(machine_agent):
    from local_shell_mcp.webui.machine_permissions import machine_access_context

    repo, cid, _, _ = machine_agent
    context = machine_access_context("local", cid, agent=None,
                                     scopes={"shell:read"}, repo=repo)
    assert "Read-only: local" in context
    assert "No access: worker1" in context
    context = machine_access_context("local", cid, agent=None,
                                     scopes=SCOPES - {"shell:execute"}, repo=repo)
    assert "Read/write: local" in context
    assert "execution-class operations are not authorized" in context


@pytest.mark.asyncio
async def test_remote_discovery_reports_effective_machine_access(machine_agent, monkeypatch):
    import json

    _, cid, agents, agent = machine_agent
    agents.update("local", agent["id"], {"machine_permissions": {"worker1": "write"}})

    async def invoke(*args, **kwargs):
        return json.dumps({"ok": True, "data": {"machines": [{"name": "worker1"}]}})

    monkeypatch.setattr(registry, "_invoke_registered", invoke)
    result = await registry.call_tool(
        "local", cid, ModelToolCall("discovery", "remote_manage", {"action": "list"}),
        granted_scopes=SCOPES, agent_id=agent["id"],
    )
    assert json.loads(result)["data"]["machines"] == [
        {"name": "worker1", "effective_access": "read"},
    ]


@pytest.mark.asyncio
async def test_agent_inherits_global_ceiling_live(machine_agent, monkeypatch):
    from local_shell_mcp.webui import durable_tasks as durable
    from local_shell_mcp.webui.machine_permissions import (
        agent_access_policy,
        effective_machine_access,
        machine_access_context,
    )

    repo, cid, agents, agent = machine_agent
    key = "agent.machine_policy.global"
    repo.save_setting("local", key, {"local": "read", "worker1": "none"})
    agent = agents.update("local", agent["id"], {
        "machine_permissions": {}, "machine_default_permission": "inherit",
    })
    assert agent_access_policy(agent) == ({}, "inherit")
    assert agents.get("local", agent["id"])["machine_default_permission"] == "inherit"

    def exposed():
        return {t["function"]["name"] for t in registry.available_tools(
            "local", cid, scopes=SCOPES, agent_permissions={},
            agent_default_permission="inherit",
        )}

    assert "file_read" in exposed()
    assert "file_write" not in exposed()
    assert effective_machine_access("local", cid, agent=agent, scopes=SCOPES, repo=repo) == (
        {"local": "read", "worker1": "none"}, "inherit",
    )
    assert "inherit global machine permissions" in machine_access_context(
        "local", cid, agent=agent, scopes=SCOPES, repo=repo,
    )

    async def invoke(*args, **kwargs):
        return '{"ok":true}'

    monkeypatch.setattr(registry, "_invoke_registered", invoke)

    async def call(name, machine, **kwargs):
        return await registry.call_tool(
            "local", cid, ModelToolCall("inherit-test", name, {"machine": machine, **kwargs}),
            granted_scopes=SCOPES, agent_id=agent["id"],
        )

    with pytest.raises(PermissionError, match="read-only"):
        await call("file_write", "local", path="file.txt", content="x")
    with pytest.raises(PermissionError, match="Agent has no read"):
        await call("file_read", "worker1", path="file.txt")
    agents.update("local", agent["id"], {"machine_permissions": {"worker1": "write"}})
    assert await call("file_read", "worker1", path="file.txt") == '{"ok":true}'
    with pytest.raises(PermissionError, match="read-only"):
        await call("file_write", "worker1", path="file.txt", content="x")

    repo.save_setting("local", key, {"local": "write", "worker1": "none"})
    assert "file_write" in exposed()
    assert await call("file_write", "local", path="file.txt", content="x") == '{"ok":true}'
    with repo.database.connect() as db:
        db.execute("INSERT INTO runs(id,conversation_id,status,state,created_at,updated_at) "
                   "VALUES('inherit-run',?,'running','{}',1,1)", (cid,))
    intent = durable.reserve("local", cid, "inherit-run", "inherit-lease", "job_start",
                            {"command": "echo ok"}, SCOPES, None, agent_id=agent["id"])
    assert durable.mark_revoked("local") == 0
    repo.save_setting("local", key, {"local": "read", "worker1": "none"})
    assert durable.mark_revoked("local") == 1
    with pytest.raises(PermissionError, match="revoked"):
        durable.check_intent(intent)
