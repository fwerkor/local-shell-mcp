"""Real saved Agent graph admission must not silently discard configured edges."""
from __future__ import annotations

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir)
    monkeypatch.setattr(agent_runner, "provider_config", lambda kind, model: ProviderConfig(
        "openai", model, "https://source-test.invalid", ""))
    yield AgentRepository(database), GenerationStore(database), database
    get_settings.cache_clear()


def create(repo, name):
    return repo.create("local", {"name": name, "provider": "openAI", "model": name, "tools": []})


async def quiet(text):
    pass


@pytest.mark.asyncio
async def test_default_single_edge_exposes_source_transfer_and_executes_owned_destination(runtime):
    repo, store, database = runtime
    child, parent = create(repo, "child"), create(repo, "parent")
    parent = repo.update("local", parent["id"], {"edges": [{"from": parent["id"], "to": child["id"]}]})
    assert "edgeType" not in parent["edges"][0]
    generation, _ = store.begin("local", {"text": "Use the configured handoff"}, parent)
    seen = []

    async def model(profile, history, **kwargs):
        seen.append(profile.model)
        if profile.model == "parent":
            name = "transfer_to_" + child["id"]
            assert name in {tool["function"]["name"] for tool in kwargs["tools"]}
            yield ModelToolCall("handoff", name, {})
        else:
            yield "Owned child completed the source handoff."

    runner = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    messages = await runner.run(store.history("local", generation.conversation_id))
    assert seen == ["parent", "child"]
    assert messages[-1]["content"] == "Owned child completed the source handoff."


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["direct", "default_fanout"])
async def test_unsupported_direct_graph_is_refused_before_any_provider_or_tool(runtime, kind):
    repo, store, database = runtime
    parent, left, right = [create(repo, name) for name in ("parent", "left", "right")]
    edge = {"from": parent["id"], "to": left["id"], "edgeType": "direct"} if kind == "direct" else {
        "from": parent["id"], "to": [left["id"], right["id"]]}
    parent = repo.update("local", parent["id"], {"edges": [edge]})
    generation, _ = store.begin("local", {"text": "Do not ignore a configured branch"}, parent)
    requests = []

    async def model(*args, **kwargs):
        requests.append(args)
        yield "A partial graph must never run"

    runner = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    with pytest.raises(ValueError, match="direct edges require the source StateGraph"):
        await runner.run(store.history("local", generation.conversation_id))
    assert requests == []


@pytest.mark.asyncio
async def test_parallel_handoff_proposals_fail_before_mutating_routing_or_completing_tools(runtime):
    repo, store, database = runtime
    parent, left, right = [create(repo, name) for name in ("parent", "left", "right")]
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": left["id"], "edgeType": "handoff"},
        {"from": parent["id"], "to": right["id"], "edgeType": "handoff"}]})
    generation, _ = store.begin("local", {"text": "Do not execute a partial handoff batch"}, parent)

    async def model(*args, **kwargs):
        yield ModelToolCall("left", "transfer_to_" + left["id"], {})
        yield ModelToolCall("right", "transfer_to_" + right["id"], {})

    runner = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    with pytest.raises(RuntimeSafetyError, match="source StateGraph executor"):
        await runner.run(store.history("local", generation.conversation_id))
    assert runner.route.snapshot()["transitions"] == []
    assert runner.cache == {}
    assert not any(event.get("event") == "on_run_step_completed" for _, event in store.events("local", generation.run_id))
