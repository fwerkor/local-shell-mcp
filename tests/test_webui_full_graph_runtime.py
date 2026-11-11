"""Real SQLite + Python LangGraph graph runs against pinned SDK topology semantics."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("langgraph")

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.fixture
def context(tmp_path, monkeypatch):
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


async def noop(text):
    pass


def runner(context, agent, model):
    _, store, database = context
    generation, _ = store.begin("local", {"text": "execute graph"}, agent)
    return AgentRunner("local", generation, database, store, scopes=set(), grant_expires=None,
                       stream_tools=model, stream_text=model, on_text=noop, agent=agent), generation


@pytest.mark.asyncio
async def test_direct_fan_out_superstep_join_barrier_and_result(context):
    repo, store, _ = context
    parent, left, right, merged = [create(repo, label) for label in ("parent", "left", "right", "merged")]
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": [left["id"], right["id"]]},
        {"from": [left["id"], right["id"]], "to": merged["id"], "edgeType": "direct"}]})
    calls, barrier = [], asyncio.Event()

    async def model(profile, history, **kwargs):
        calls.append(profile.model)
        if profile.model == "merged":
            assert sum(msg.get("content") == "left answered" for msg in history) == 1
            assert sum(msg.get("content") == "right answered" for msg in history) == 1
            barrier.set()
        if profile.model in {"left", "right"}:
            await asyncio.sleep(0.001)
        yield profile.model + " answered"

    obj, job = runner(context, parent, model)
    history = await obj.run(store.history("local", job.conversation_id))
    assert barrier.is_set()
    assert calls[0] == "parent" and set(calls[1:3]) == {"left", "right"} and calls[3:] == ["merged"]
    assert history[-1]["content"] == "merged answered"


@pytest.mark.asyncio
async def test_parallel_handoff_command_sends_fan_out(context):
    repo, store, _ = context
    parent, left, right = [create(repo, label) for label in ("parent", "left", "right")]
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": left["id"], "edgeType": "handoff"},
        {"from": parent["id"], "to": right["id"], "edgeType": "handoff"}]})
    seen = []

    async def model(profile, history, **kwargs):
        seen.append(profile.model)
        if profile.model == "parent":
            yield ModelToolCall("left", "transfer_to_" + left["id"], {})
            yield ModelToolCall("right", "transfer_to_" + right["id"], {})
        else:
            yield "done:" + profile.model

    obj, job = runner(context, parent, model)
    messages = await obj.run(store.history("local", job.conversation_id))
    assert seen[0] == "parent" and set(seen[1:]) == {"left", "right"}
    assert {item["content"] for item in messages if item.get("role") == "assistant"} >= {
        "done:left", "done:right"}


@pytest.mark.asyncio
async def test_durable_graph_checkpoint_resume_without_rerunning_completed_nodes(context):
    repo, store, database = context
    parent, child = create(repo, "parent"), create(repo, "child")
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": child["id"], "edgeType": "direct"}]})
    calls = []

    async def model(profile, history, **kwargs):
        calls.append(profile.model)
        yield profile.model + " answered"

    obj, job = runner(context, parent, model)
    first = await obj.run(store.history("local", job.conversation_id))
    assert calls == ["parent", "child"]
    second = AgentRunner("local", job, database, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=noop, agent=parent)
    again = await second.run([])
    assert calls == ["parent", "child"]
    assert first == again


@pytest.mark.asyncio
async def test_direct_and_handoff_choose_exclusive_command_path(context):
    repo, store, _ = context
    parent, direct, target = [create(repo, label) for label in ("parent", "direct", "target")]
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": direct["id"], "edgeType": "direct"},
        {"from": parent["id"], "to": target["id"], "edgeType": "handoff"}]})
    seen = []

    async def model(profile, history, **kwargs):
        seen.append(profile.model)
        if profile.model == "parent":
            yield ModelToolCall("handoff", "transfer_to_" + target["id"], {})
        else:
            yield profile.model + " answered"

    obj, job = runner(context, parent, model)
    messages = await obj.run(store.history("local", job.conversation_id))
    assert seen == ["parent", "target"]
    assert messages[-1]["content"] == "target answered"

@pytest.mark.asyncio
async def test_graph_team_subagent_uses_isolated_state_and_returns_designated_result(context):
    from local_shell_mcp.webui.subagents import build_subagent_configs

    repo, store, _ = context
    a, b = [create(repo, name) for name in ("a", "b")]
    lead = create(repo, "lead")
    definition = {"type": "research_team", "name": "Research team", "description": "Two-stage graph",
                  "agent_ids": [a["id"], b["id"]], "entry_agent_id": a["id"],
                  "result_agent_id": b["id"], "edges": [
                      {"from": a["id"], "to": b["id"], "edgeType": "direct"}]}
    lead = repo.update("local", lead["id"], {"subagents": {
        "enabled": True, "allowSelf": False, "agent_ids": [], "graphs": [definition]}})
    configs = build_subagent_configs("local", lead, context[2])
    assert len(configs) == 1 and configs[0].type == "research_team"
    seen = []

    async def model(profile, history, **kwargs):
        seen.append((profile.model, [msg.get("content") for msg in history]))
        if profile.model == "lead":
            if history[-1].get("role") == "tool":
                yield "lead done"
            else:
                yield ModelToolCall("team", "subagent", {
                    "subagent_type": "research_team", "description": "Check the components"})
        elif profile.model == "a":
            yield "intermediate reasoning"
        elif profile.model == "b":
            yield "final team result"

    obj, job = runner(context, lead, model)
    response = await obj.run(store.history("local", job.conversation_id))
    assert [name for name, _ in seen[:3]] == ["lead", "a", "b"]
    assert "Check the components" in seen[1][1]
    assert "intermediate reasoning" in seen[2][1]
    tool_messages = [msg for msg in response if msg.get("role") == "tool"]
    assert any(msg.get("content") == "final team result" for msg in tool_messages)
    assert not any(msg.get("content") == "intermediate reasoning" for msg in response)

@pytest.mark.asyncio
async def test_graph_ask_user_pause_and_new_process_resume_uses_same_generation(context):
    from local_shell_mcp.webui.agent_runtime import AgentSuspended

    repo, store, database = context
    parent = repo.create("local", {"name": "parent", "provider": "openAI",
                                   "model": "parent", "tools": ["ask_user_question"]})
    child = create(repo, "child")
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": child["id"], "edgeType": "direct"}]})
    calls = []

    async def model(profile, history, **kwargs):
        calls.append(profile.model)
        if profile.model == "parent" and not any(msg.get("role") == "tool" for msg in history):
            yield ModelToolCall("ask-1", "ask_user_question", {"questions": [
                {"id": "format", "question": "Which format?", "type": "text"}]})
        else:
            yield "answered:" + profile.model

    obj, job = runner(context, parent, model)
    obj.ask_user_enabled = True
    with pytest.raises(AgentSuspended):
        await obj.run(store.history("local", job.conversation_id))
    pending = store.pending_action("local", job.run_id)
    assert pending["payload"] is not None and pending["namespace"].endswith("/graph:" + parent["id"])
    _, history, _ = store.answer_question("local", job.run_id, pending["actionId"],
                                          {"answers": {"format": "Markdown"}})
    resumed = AgentRunner("local", job, database, store, scopes=set(), grant_expires=None,
                          stream_tools=model, stream_text=model, on_text=noop,
                          agent=parent, ask_user_enabled=True, resume_history=history,
                          resume_namespace=pending["namespace"])
    result = await resumed.run(history)
    assert result[-1]["content"] == "answered:child"
    assert calls.count("parent") == 2 and calls.count("child") == 1

@pytest.mark.asyncio
async def test_direct_prompt_excludes_intermediate_result_from_child_model_context(context):
    repo, store, _ = context
    lead, sink = create(repo, "lead"), create(repo, "sink")
    lead = repo.update("local", lead["id"], {"edges": [
        {"from": lead["id"], "to": sink["id"], "edgeType": "direct",
         "prompt": "Review these results: {results}", "excludeResults": True}]})
    seen = []

    async def model(profile, history, **kwargs):
        seen.append((profile.model, [x.get("content") for x in history]))
        if profile.model == "lead":
            yield "private intermediate"
        else:
            yield "final response"

    obj, job = runner(context, lead, model)
    result = await obj.run(store.history("local", job.conversation_id))
    assert seen[1][0] == "sink"
    assert "private intermediate" not in seen[1][1]
    assert any(isinstance(value, str) and "private intermediate" in value and "Review these" in value
               for value in seen[1][1])
    assert result[-1]["content"] == "final response"


@pytest.mark.asyncio
async def test_graph_cancel_during_node_then_restart_only_replays_incomplete_node(context):
    repo, store, database = context
    root, child = create(repo, "root"), create(repo, "child")
    root = repo.update("local", root["id"], {"edges": [
        {"from": root["id"], "to": child["id"], "edgeType": "direct"}]})
    pending = asyncio.Event()
    waiting = asyncio.Event()
    calls = []

    async def model(profile, history, **kwargs):
        calls.append(profile.model)
        if profile.model == "child" and not pending.is_set():
            waiting.set()
            await pending.wait()
        yield profile.model + " output"

    obj, job = runner(context, root, model)
    task = asyncio.create_task(obj.run(store.history("local", job.conversation_id)))
    await asyncio.wait_for(waiting.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == ["root", "child"]
    pending.set()
    continued = AgentRunner("local", job, database, store, scopes=set(), grant_expires=None,
                            stream_tools=model, stream_text=model, on_text=noop, agent=root)
    result = await continued.run([])
    assert calls == ["root", "child", "child"]
    assert result[-1]["content"] == "child output"

@pytest.mark.asyncio
async def test_graph_tool_approval_reuses_same_pause_claim_and_executor(context, monkeypatch, tmp_path):
    import httpx
    from starlette.applications import Starlette

    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.routes import _repo

    repo, store, database = context
    parent = repo.create("local", {"name": "parent", "provider": "openAI",
                                   "model": "parent", "tools": ["file_write"]})
    child = create(repo, "child")
    parent = repo.update("local", parent["id"], {"edges": [
        {"from": parent["id"], "to": child["id"], "edgeType": "direct"}]})
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {
        "enabled": True, "ask": ["file_write"]}}})
    calls = []

    async def model(profile, history, **kwargs):
        calls.append(profile.model)
        if profile.model == "parent" and not any(msg.get("role") == "tool" for msg in history):
            yield ModelToolCall("write-once", "file_write", {"path": "approved.txt", "content": "approved"})
        else:
            yield profile.model + " finished"

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    monkeypatch.setattr(generation_routes, "stream_model", model)
    monkeypatch.setattr(generation_routes, "provider_config", lambda *args: ProviderConfig(
        "openai", "parent", "https://source-test.invalid", ""))
    generation, _ = store.begin("local", {"text": "write using reviewed tool"}, parent)
    await generation_routes._run_model("local", generation, ProviderConfig(
        "openai", "parent", "https://source-test.invalid", ""),
        parent_agent=parent, granted_scopes=frozenset({"shell:read", "shell:write"}))
    pending = store.pending_action("local", generation.run_id)
    assert pending["namespace"].endswith("/graph:" + parent["id"])
    assert not (tmp_path / "approved.txt").exists()
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.post("/api/agents/chat/resume", json={
            "conversationId": generation.conversation_id, "actionId": pending["actionId"],
            "decisions": [{"tool_call_id": "write-once", "decision": "approve"}],
        })
        assert answer.status_code == 200, answer.text
        tasks = list(generation_routes._TASKS.values())
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), 10)
    assert (tmp_path / "approved.txt").read_text() == "approved"
    assert calls == ["parent", "parent", "child"]
    assert store.latest("local", generation.conversation_id).status == "complete"
    assert store.approved_review("local", generation.run_id) is None

@pytest.mark.asyncio
async def test_command_routed_source_defaults_to_direct_when_no_transfer(context):
    repo, store, _ = context
    root, direct, optional = [create(repo, name) for name in ("root", "direct", "optional")]
    root = repo.update("local", root["id"], {"edges": [
        {"from": root["id"], "to": direct["id"], "edgeType": "direct"},
        {"from": root["id"], "to": optional["id"], "edgeType": "handoff"}]})
    reached = []

    async def model(profile, history, **kwargs):
        reached.append(profile.model)
        yield profile.model + " done"

    obj, job = runner(context, root, model)
    result = await obj.run(store.history("local", job.conversation_id))
    assert reached == ["root", "direct"]
    assert result[-1]["content"] == "direct done"

@pytest.mark.asyncio
async def test_graph_team_designated_result_from_parallel_join(context):
    from local_shell_mcp.webui.subagents import build_subagent_configs

    repo, store, _ = context
    entry, result, trailing, helper = [create(repo, name) for name in ("entry", "result", "trailing", "helper")]
    lead = create(repo, "lead")
    definition = {"type": "team", "name": "Team", "description": "Concurrent",
                  "agent_ids": [entry["id"], result["id"], trailing["id"], helper["id"]],
                  "entry_agent_id": entry["id"], "result_agent_id": result["id"],
                  "edges": [{"from": entry["id"], "to": [trailing["id"], helper["id"]], "edgeType": "direct"},
                            {"from": [trailing["id"], helper["id"]], "to": result["id"], "edgeType": "direct"}]}
    lead = repo.update("local", lead["id"], {"subagents": {
        "enabled": True, "allowSelf": False, "agent_ids": [], "graphs": [definition]}})
    assert build_subagent_configs("local", lead, context[2])[0].agent["graphAgentIds"] == [
        entry["id"], result["id"], trailing["id"], helper["id"]]
    seen = []

    async def model(profile, history, **kwargs):
        seen.append(profile.model)
        if profile.model == "lead":
            if history[-1].get("role") == "tool":
                yield "all done"
            else:
                yield ModelToolCall("team", "subagent", {"subagent_type": "team", "description": "Run"})
        elif profile.model == "result":
            yield "designated result"
        elif profile.model == "trailing":
            await asyncio.sleep(0.02)
            yield "non-result sibling"
        else:
            yield "initial result"

    obj, job = runner(context, lead, model)
    response = await obj.run(store.history("local", job.conversation_id))
    assert set(seen) == {"entry", "result", "trailing", "helper", "lead"}
    assert [m["content"] for m in response if m.get("role") == "tool"] == ["designated result"]


def test_graph_team_rejects_orphan_member_before_runtime(context):
    repo, _, _ = context
    entry, result, extra = [create(repo, name) for name in ("entry", "result", "extra")]
    lead = create(repo, "lead")
    definition = {"type": "team", "name": "Team", "description": "Directed",
                  "agent_ids": [entry["id"], result["id"], extra["id"]],
                  "entry_agent_id": entry["id"], "result_agent_id": result["id"],
                  "edges": [{"from": entry["id"], "to": result["id"], "edgeType": "direct"}]}
    with pytest.raises(ValueError, match="only root"):
        repo.update("local", lead["id"], {"subagents": {
            "enabled": True, "allowSelf": False, "agent_ids": [], "graphs": [definition]}})
