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

def attach_agent_context(repo, database, agent, text):
    import json

    from local_shell_mcp.webui import attachments

    identity = "file-" + agent["id"]
    path = attachments._safe_attachment_path("local", identity + ".txt", database.root)
    path.write_text(text)
    with database.connect() as sql:
        sql.execute("INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)", (
            identity, "local", identity + ".txt", str(path), "text/plain",
            json.dumps({"extracted_text": text, "processed": True}),
        ))
    repo.add_resource_file("local", agent["id"], "context", identity)
    return repo.get("local", agent["id"])


@pytest.mark.asyncio
async def test_subagent_receives_own_context_once_and_checkpoint_resume_does_not_reinject(runtime):
    repo, store, database = runtime
    child, parent = create(repo, "child"), create(repo, "parent")
    child = attach_agent_context(repo, database, child, "private child reference")
    parent = repo.update("local", parent["id"], {"subagents": {
        "enabled": True, "allowSelf": False, "agent_ids": [child["id"]],
    }})
    generation, _ = store.begin("local", {"text": "Use subagent"}, parent)
    seen = []

    async def model(profile, history, **_):
        seen.append(profile.model)
        if profile.model == "parent":
            if any(message.get("role") == "tool" for message in history):
                yield "Parent completed"
            else:
                yield ModelToolCall("spawn", "subagent", {
                    "subagent_type": child["id"], "description": "Use your documents",
                })
        else:
            assert profile.model == "child"
            assert history[0]["role"] == "user"
            docs = [message for message in history if "private child reference" in (message.get("content") or "")]
            assert len(docs) == 1
            assert history[-1] == {"role": "user", "content": "Use your documents"}
            yield "Child used its private context"

    runner = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    messages = await runner.run(store.history("local", generation.conversation_id))
    assert messages[-1]["content"] == "Parent completed"
    reopened = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                           stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    await reopened.run([])
    assert seen == ["parent", "child", "parent"]


@pytest.mark.asyncio
async def test_handoff_destination_receives_context_once_even_when_restarted(runtime):
    repo, store, database = runtime
    child, parent = create(repo, "child"), create(repo, "parent")
    attach_agent_context(repo, database, child, "handoff target reference")
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": child["id"], "edgeType": "handoff"},
    ]})
    generation, _ = store.begin("local", {"text": "Delegate"}, parent)
    seen = []

    async def model(profile, history, **_):
        seen.append(profile.model)
        if profile.model == "parent":
            yield ModelToolCall("handoff", "transfer_to_" + child["id"], {})
        else:
            docs = [message for message in history if "handoff target reference" in (message.get("content") or "")]
            assert len(docs) == 1
            assert docs[0]["role"] == "user"
            yield "Destination used its context"

    runner = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    result = await runner.run(store.history("local", generation.conversation_id))
    assert result[-1]["content"] == "Destination used its context"
    reopened = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                           stream_tools=model, stream_text=model, on_text=quiet, agent=parent)
    await reopened.run([])
    assert seen == ["parent", "child"]


def test_idempotent_context_prefix_preserves_system_instructions_and_rejects_missing_resources(runtime):
    repo, _, database = runtime
    child = create(repo, "child")
    child = attach_agent_context(repo, database, child, "deduplicated document")
    from local_shell_mcp.webui.attachments import with_agent_context

    history = [{"role": "system", "content": "higher priority instructions"},
               {"role": "user", "content": "task"}]
    once = with_agent_context(database, "local", child, history)
    twice = with_agent_context(database, "local", child, once)
    assert once == twice
    assert len(once) == 3
    assert once[0] == history[0] and once[-1] == history[1]
    assert "deduplicated document" in once[1]["content"]
    assert with_agent_context(database, "foreign-owner", child, history) == history


def test_saved_steer_history_interleaves_assistant_replies_in_chronological_order(runtime):
    import json

    _, store, _ = runtime
    run, _ = store.begin('local', {'text': 'Initial request'})
    assert store.finish('local', run.run_id, status='complete', text='final')
    with store.database.connect() as db:
        db.execute('UPDATE messages SET content=? WHERE id=?',
                   (json.dumps([
                       {'type': 'text', 'text': 'Before correction'},
                       {'type': 'steer', 'steer': 'Correct assumption', 'steerId': 's1'},
                       {'type': 'text', 'text': 'First corrected answer'},
                       {'type': 'steer', 'steer': 'Use less detail', 'steerId': 's2'},
                       {'type': 'text', 'text': 'Final answer'},
                   ]), run.response_message_id))
    history = store.history('local', run.conversation_id)
    assert [(part['role'], part['content']) for part in history[1:]] == [
        ('assistant', 'Before correction'), ('user', 'Correct assumption'),
        ('assistant', 'First corrected answer'), ('user', 'Use less detail'),
        ('assistant', 'Final answer'),
    ]
