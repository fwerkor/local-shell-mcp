"""Composer switches persist with conversations and fence nested MCP dispatch."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp import dynamic_mcp
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import agent_routes, misc_routes, nested_mcp
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo


@pytest.mark.asyncio
async def test_composer_feature_defaults_chat_override_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()

    class Registry:
        async def manage(self, **kwargs):
            assert kwargs == {"action": "list"}
            return {"servers": [{"name": "demo", "enabled": True, "tool_count": 2, "transport": "stdio",
                                  "command": "secret", "env_keys": ["PASSWORD"]}]}

    monkeypatch.setattr(dynamic_mcp, "DynamicMCPManager", lambda *_args, **_kwargs: Registry())
    app = Starlette(routes=[*misc_routes.misc_routes(), *agent_routes.agent_routes()])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        defaults = await client.get('/api/lsm/feature-defaults')
        assert defaults.json() == {"web": True, "memory": True, "mcp": True, "mcpServers": None}
        listing = await client.get('/api/lsm/mcp/servers')
        assert listing.json() == {"servers": [{"name": "demo", "enabled": True, "tool_count": 2, "transport": "stdio"}]}
        assert (await client.put('/api/lsm/feature-defaults', json={
            'mcpServers': ['invalid:name']})).status_code == 400
        assert (await client.put('/api/lsm/feature-defaults', json={
            'mcp': False, 'mcpServers': ['demo']})).status_code == 200
        cid = _repo().create_conversation('local', {'title': 'New'})['conversationId']
        inherited = (await client.get(f'/api/lsm/preferences/{cid}')).json()
        assert inherited['mcp'] is False and inherited['mcpServers'] == ['demo']
        assert (await client.put(f'/api/lsm/preferences/{cid}', json={
            'mcp': True, 'mcpServers': []})).status_code == 200
        updated = (await client.put(f'/api/lsm/preferences/{cid}', json={
            'machines': {}})).json()
        assert updated['mcp'] is True and updated['mcpServers'] == []
        assert updated['memory'] is True
        assert (await client.put(f'/api/lsm/preferences/{cid}', json={
            'mcpServers': ["demo", "demo"]})).status_code == 400
        assert (await client.get('/api/lsm/preferences/unknown')).status_code == 404
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_selected_servers_fence_search_inspect_and_approved_call(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    repo = _repo()
    cid = repo.create_conversation('local', {'title': 'Selected MCP'})['conversationId']
    repo.save_setting('local', 'conversation.permissions.' + cid,
                      {'mcp': True, 'mcpServers': ['allowed']})
    observed = []

    async def invoke(_owner, _cid, name, arguments, *, scopes):
        observed.append((name, arguments, dynamic_mcp._AGENT_ALLOWED_SERVERS.get()))
        return '{}'

    monkeypatch.setattr(nested_mcp, '_invoke_registered', invoke)
    scopes = {'shell:read', 'shell:execute'}
    await nested_mcp.discover('local', cid, scopes, ModelToolCall('1', 'mcp_tool_search', {'query': 'x'}))
    assert observed[-1][-1] == frozenset({'allowed'})
    assert dynamic_mcp._AGENT_ALLOWED_SERVERS.get() is None
    for call in (
        ModelToolCall('2', 'mcp_tool_search', {'server': 'blocked'}),
        ModelToolCall('3', 'mcp_tool_inspect', {'name': 'blocked:read'}),
    ):
        with pytest.raises(PermissionError, match='disabled'):
            await nested_mcp.discover('local', cid, scopes, call)
    with pytest.raises(PermissionError, match='disabled'):
        await nested_mcp.approved_call('local', cid, scopes, ModelToolCall('4', 'mcp_tool_call',
                                          {'name': 'blocked:write', 'arguments': {}}))
    assert len(observed) == 1

    manager = dynamic_mcp.DynamicMCPManager(tmp_path)
    records = {
        name: dynamic_mcp.DynamicMCPServer(name=name, transport='stdio', command='echo',
                                           tools=[{'name': 'read', 'description': 'read'}])
        for name in ('allowed', 'blocked')
    }
    monkeypatch.setattr(manager, '_load', lambda: records)
    token = dynamic_mcp._AGENT_ALLOWED_SERVERS.set(frozenset({'allowed'}))
    try:
        result = await manager.search()
        assert [tool['server'] for tool in result['tools']] == ['allowed']
        with pytest.raises(ValueError, match='not available'):
            await manager.search(server='blocked')
        with pytest.raises(PermissionError, match='disabled'):
            await manager.inspect('blocked:read')
        with pytest.raises(PermissionError, match='disabled'):
            await manager.call('blocked:read')
    finally:
        dynamic_mcp._AGENT_ALLOWED_SERVERS.reset(token)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_agent_mcp_ceiling_is_persisted_and_rechecked(tmp_path, monkeypatch):
    from local_shell_mcp.webui.agents import AgentRepository

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    try:
        repo = _repo()
        agents = AgentRepository(repo.database)
        agent = agents.create("local", {"name": "Restricted", "provider": "openAI",
                                       "model": "test", "mcp_servers": ["a", "b"]})
        aid = agent["id"]
        cid = repo.create_conversation("local", {"title": "MCP"})["conversationId"]
        repo.save_setting("local", "conversation.permissions." + cid, {"mcpServers": ["b", "c"]})
        assert nested_mcp._allowed("local", cid, {}, aid) == frozenset({"b"})
        assert agents.get("local", aid)["mcp_servers"] == ["a", "b"]
        with pytest.raises(ValueError):
            agents.update("local", aid, {"mcp_servers": ["b", "b"]})
        with pytest.raises(PermissionError, match="disabled"):
            await nested_mcp.discover("local", cid, {"shell:read"},
                ModelToolCall("inspect", "mcp_tool_inspect", {"name": "c:read"}), agent_id=aid)
        agents.update("local", aid, {"mcp_servers": []})
        with pytest.raises(PermissionError, match="disabled"):
            await nested_mcp.approved_call("local", cid, {"shell:read", "shell:execute"},
                ModelToolCall("call", "mcp_tool_call", {"name": "b:read"}), agent_id=aid)
        agents.update("local", aid, {"mcp_servers": None})
        assert nested_mcp._allowed("local", cid, {}, aid) == frozenset({"b", "c"})
        agents.delete("local", aid)
        with pytest.raises(PermissionError, match="no longer exists"):
            nested_mcp._allowed("local", cid, {}, aid)
    finally:
        get_settings.cache_clear()
