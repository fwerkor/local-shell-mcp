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
        "session_manage", "plan_manage",
    }


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
