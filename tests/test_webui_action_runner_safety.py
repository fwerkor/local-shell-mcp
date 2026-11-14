"""Action dispatch revocation and stale in-flight Agent graph boundary tests."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.action_spec import normalize_action_tool_name, tool_name
from local_shell_mcp.webui.actions import ActionRepository
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, RuntimeSafetyError
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.mark.asyncio
async def test_inflight_action_never_executes_with_revoked_token_or_deleted_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    try:
        database = shared_database(get_settings().state_dir)
        agents = AgentRepository(database)
        actions = ActionRepository(database)
        owner = "local"
        agent = agents.create(owner, {"provider": "openAI", "model": "fake", "name": "Revocation"})
        domain = "https://api.example.org"
        spec = {"openapi": "3.0.3", "servers": [{"url": domain}], "paths": {
            "/read": {"get": {"operationId": "readData", "responses": {"200": {"description": "ok"}}}},
        }}
        agent, action = actions.save(owner, agent["id"], {"metadata": {
            "domain": domain, "raw_spec": json.dumps(spec), "auth": {
                "type": "oauth", "authorization_url": "https://id.example.org/authorize",
                "client_url": "https://id.example.org/token", "scope": "read",
                "token_exchange_method": "default_post"},
            "oauth_client_id": "client", "oauth_client_secret": "secret"},
            "functions": [{"type": "function", "function": {"name": "readData"}}],
        })
        name = normalize_action_tool_name(tool_name("readData", domain))
        generation, _ = GenerationStore(database).begin(owner, {"text": "use Action"}, agent)
        profile = ProviderConfig("openai", "fake", "https://model.invalid", "")

        async def model(*_args, **_kwargs):
            yield "unused"

        async def emit(_text):
            pass

        runner = AgentRunner(owner, generation, database, GenerationStore(database), scopes=set(),
                             grant_expires=None, stream_tools=model, stream_text=model,
                             on_text=emit, profile=profile, agent=agent)
        state = AgentLoopState(runner._context(agent, profile=profile), [])
        call = ModelToolCall("call", name, {})
        assert name in {tool["function"]["name"] for tool in state.context.tools}
        with pytest.raises(RuntimeSafetyError, match="revoked before dispatch"):
            await runner._invoke(call, state)
        assert actions.delete(owner, agent["id"], action["action_id"])
        with pytest.raises(RuntimeSafetyError, match="not bound"):
            await runner._invoke(call, state)
        with pytest.raises(RuntimeSafetyError, match="not bound"):
            await runner._prepare_oauth([call], state)
        with pytest.raises(RuntimeSafetyError, match="not enabled"):
            await runner._invoke(ModelToolCall("unselected", "file_write", {}), state)
        # A manually constructed source graph cannot introduce an Action when
        # the active context is anonymous rather than an owned stored Agent.
        no_agent = AgentLoopState(AgentContext(profile, [{"type": "function", "function": {
            "name": name, "parameters": {"type": "object"}}}]), [])
        with pytest.raises(RuntimeSafetyError, match="saved Agent"):
            await runner._invoke(call, no_agent)
    finally:
        get_settings.cache_clear()
