"""Real saved Agent graph admission must not silently discard configured edges."""
from __future__ import annotations

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner
from local_shell_mcp.webui.agent_runner import AgentRunner
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
async def test_direct_graph_runs_all_configured_branches(runtime, kind):
    repo, store, database = runtime
    parent, left, right = [create(repo, name) for name in ("parent", "left", "right")]
    edge = {"from": parent["id"], "to": left["id"], "edgeType": "direct"} if kind == "direct" else {
        "from": parent["id"], "to": [left["id"], right["id"]]}
    parent = repo.update("local", parent["id"], {"edges": [edge]})
    generation, _ = store.begin("local", {"text": "Do not ignore a configured branch"}, parent)
    requests = []

    async def model(*args, **kwargs):
        requests.append(args)
        yield args[0].model + " ran"

    runner = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    result = await runner.run(store.history("local", generation.conversation_id))
    assert {item[0].model for item in requests} == ({"parent", "left"} if kind == "direct" else {"parent", "left", "right"})
    assert any(message.get("content") == "left ran" for message in result)


@pytest.mark.asyncio
async def test_parallel_handoff_runs_both_owned_destinations(runtime):
    repo, store, database = runtime
    parent, left, right = [create(repo, name) for name in ("parent", "left", "right")]
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": left["id"], "edgeType": "handoff"},
        {"from": parent["id"], "to": right["id"], "edgeType": "handoff"}]})
    generation, _ = store.begin("local", {"text": "Do not execute a partial handoff batch"}, parent)

    async def model(profile, history, **kwargs):
        if profile.model == "parent":
            yield ModelToolCall("left", "transfer_to_" + left["id"], {})
            yield ModelToolCall("right", "transfer_to_" + right["id"], {})
        else:
            yield profile.model + " completed"

    runner = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    result = await runner.run(store.history("local", generation.conversation_id))
    assert {item.get("content") for item in result if item.get("role") == "assistant"} >= {
        "left completed", "right completed"}
    assert any(event.get("event") == "on_run_step_completed" for _, event in store.events("local", generation.run_id))
