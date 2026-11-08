"""Original-source differentials and owner-scoped isolated child execution."""

from __future__ import annotations

import asyncio
import itertools
import json
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.subagents import (
    SubagentConfig,
    build_subagent_configs,
    build_subagent_tool_params,
    filter_subagent_result,
    invoke_subagent,
    resolve_subagent_max_turns,
    subagent_tools,
)


def _oracle(operation, inputs):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for original-source differential oracle")
    fixture = Path(__file__).parent / "fixtures/librechat/subagent_reference.cjs"
    program = """
const fs = require('fs'); const p = require(process.argv[1]);
const {operation,inputs} = JSON.parse(fs.readFileSync(0,'utf8'));
const output = inputs.map(input => {
 if(operation === 'schema') return p.buildSubagentToolParams(input.configs, input.options);
 if(operation === 'budget') return p.resolveSubagentMaxTurns(input.endpoint, input.agent);
 return p.filterSubagentResult(input.map(message => ({...message,
  _getType: () => message.role === 'assistant' ? 'ai' : message.role})));
}); process.stdout.write(JSON.stringify(output));
"""
    return json.loads(subprocess.check_output(
        [node, "-e", program, str(fixture.resolve())],
        input=json.dumps({"operation": operation, "inputs": inputs}).encode(),
    ))


def test_exact_dynamic_schema_and_capability_gating():
    configs = [SubagentConfig("self", "Main", "self task", {}, 16, "alice"),
               SubagentConfig("agent_child", "Reviewer", "code review", {}, 16, "alice")]
    cases = [{"configs": [{"type": config.type, "name": config.name, "description": config.description}
                          for config in configs],
              "options": {"background": background, "threadContinuation": continuation}}
             for background, continuation in itertools.product([False, True], repeat=2)]
    assert [build_subagent_tool_params(configs, background=case["options"]["background"],
                                      thread_continuation=case["options"]["threadContinuation"])
            for case in cases] == _oracle("schema", cases)
    definition = subagent_tools(configs)[0]["function"]
    assert definition["name"] == "subagent"
    assert "run_in_background" not in definition["parameters"]["properties"]
    assert "subagent_thread_id" not in definition["parameters"]["properties"]
    assert subagent_tools([]) == []


def test_original_recursion_budget_cascade():
    cases = [{"agent": agent, "endpoint": endpoint} for agent, endpoint in itertools.product(
        [{}, {"recursion_limit": 1}, {"recursion_limit": 2}, {"recursion_limit": 3},
         {"recursion_limit": 25}, {"recursion_limit": 150}, {"recursion_limit": -1},
         {"recursion_limit": "200"}, {"recursion_limit": True}],
        [{}, {"recursionLimit": 75}, {"maxRecursionLimit": 20},
         {"recursionLimit": 90, "maxRecursionLimit": 30}, {"maxRecursionLimit": -1}],
    )]
    assert [resolve_subagent_max_turns(case["agent"], case["endpoint"]) for case in cases] == _oracle("budget", cases)


def test_original_result_projection_strips_reasoning_and_intermediate_tools():
    blocks = ["", "plain", {"type": "text", "text": "one"}, {"type": "text", "annotations": []},
              {"type": "thinking", "thinking": "PRIVATE"}, {"type": "tool_use", "name": "private"},
              {"type": "text_delta", "text": "hello", "index": 1},
              {"type": "text_delta", "text": " world", "index": 1},
              {"type": "text_delta", "text": "other", "index": 2},
              {"type": "text_delta", "text": " unindexed"},
              {"type": "text_delta", "text": "", "index": 3}]
    cases = [[{"role": "assistant", "content": list(pair)},
              {"role": "tool", "content": "PRIVATE TOOL OUTPUT"}]
             for pair in itertools.product(blocks, repeat=2)]
    cases += [[], [{"role": "user", "content": "hello"}],
              [{"role": "assistant", "content": "earlier progress"},
               {"role": "assistant", "content": [{"type": "tool_use", "name": "unfinished"}]}],
              [{"role": "assistant", "content": {"not": "text"}}],
              [{"role": "assistant", "content": ""}]]
    assert [filter_subagent_result(case) for case in cases] == _oracle("result", cases)
    assert filter_subagent_result([{"role": "ai", "content": [None, 5, "ok"]}]) == "ok"


@pytest.fixture
def db(tmp_path):
    return SQLiteDatabase(tmp_path / ".local-shell-mcp")


def _agent(db, owner="alice", **body):
    return AgentRepository(db).create(owner, {"provider": "openai", "name": "Worker", **body})


def test_optional_config_self_defaults_children_cycle_pruning_and_own_tools(db):
    child = _agent(db, tools=["file_read", "ask_user_question"], recursion_limit=30)
    parent = _agent(db, tools=["run_shell"], subagents={"enabled": True, "agent_ids": [child["id"]]})
    child = AgentRepository(db).update("alice", child["id"], {
        "subagents": {"enabled": True, "allowSelf": False, "agent_ids": [parent["id"]]},
    })
    configs = build_subagent_configs("alice", parent, db)
    assert [config.type for config in configs] == ["self", child["id"]]
    assert configs[0].self_spawn and not configs[0].allow_nested
    assert "subagents" not in configs[0].agent
    assert configs[1].agent["tools"] == ["file_read"]
    assert configs[1].max_turns == 10
    assert configs[1].children == ()
    assert child["tools"] == ["file_read", "ask_user_question"]
    assert build_subagent_configs("alice", None, db) == []
    assert build_subagent_configs("alice", {"subagents": []}, db) == []
    assert build_subagent_configs("alice", {"subagents": {"enabled": False}}, db) == []
    parent["subagents"]["allowSelf"] = False
    parent["subagents"]["agent_ids"].append(parent["id"])
    assert len(build_subagent_configs("alice", parent, db)) == 1


def test_subagent_config_rejects_foreign_malformed_duplicate_and_graph(db):
    foreign = _agent(db, "bob")
    child = _agent(db)
    base = {"id": "parent", "subagents": {"enabled": True, "allowSelf": False}}
    for value in ["not-array", [7]]:
        base["subagents"]["agent_ids"] = value
        with pytest.raises(ValueError, match="agent_ids"):
            build_subagent_configs("alice", base, db)
    base["subagents"]["agent_ids"] = [foreign["id"]]
    with pytest.raises(PermissionError):
        build_subagent_configs("alice", base, db)
    base["subagents"]["agent_ids"] = [child["id"], child["id"]]
    with pytest.raises(ValueError, match="Duplicate"):
        build_subagent_configs("alice", base, db)
    base["subagents"]["agent_ids"] = []
    base["subagents"]["graphs"] = [{"id": "graph"}]
    with pytest.raises(ValueError, match="multi-agent graph"):
        build_subagent_configs("alice", base, db)
    with pytest.raises(ValueError, match="maximum depth"):
        build_subagent_configs("alice", base, db, depth=6)
    base["subagents"].pop("graphs")
    base["subagents"]["allowSelf"] = True
    with pytest.raises(ValueError, match="100 expanded"):
        build_subagent_configs("alice", base, db, _count=[100])
    base["subagents"]["allowSelf"] = False
    base["subagents"]["agent_ids"] = [child["id"]]
    with pytest.raises(ValueError, match="maximum depth"):
        build_subagent_configs("alice", base, db, depth=5)
    fallback = {"subagents": {"enabled": True}}
    assert build_subagent_configs("alice", fallback, db)[0].name == "self"


@pytest.mark.asyncio
async def test_shared_child_execution_is_isolated_and_scope_bound(db):
    child = _agent(db, instructions="Be precise", additional_instructions="Use source", tools=["file_read", "ask_user_question"])
    parent = _agent(db, instructions="PARENT PRIVATE", subagents={"enabled": True, "allowSelf": False, "agent_ids": [child["id"]]})
    configs = build_subagent_configs("alice", parent, db)
    call = ModelToolCall("call-1", "subagent", {"subagent_type": child["id"], "description": "Review this file"})
    expiry = int(time.time()) + 60

    async def execute(invocation):
        assert invocation.messages == [{"role": "system", "content": "Be precise\n\nUse source"},
                                       {"role": "user", "content": "Review this file"}]
        assert invocation.selected_tools == ("file_read",)
        assert invocation.scopes == frozenset({"shell:read"})
        assert invocation.grant_expires == expiry
        assert invocation.recursion_limit == 48 and invocation.remaining_depth == 4
        assert invocation.parent_tool_call_id == "call-1"
        assert invocation.parent_run_id == "run-1" and invocation.owner == "alice"
        assert invocation.conversation_id == "conversation-1"
        return [{"role": "assistant", "content": [{"type": "thinking", "thinking": "PRIVATE"},
                                                    {"type": "text", "text": "Final summary"}]}]

    options = dict(execute_child=execute, owner="alice", conversation_id="conversation-1",
                   parent_run_id="run-1", scopes=frozenset({"shell:read"}), grant_expires=expiry, database=db)
    assert await invoke_subagent(call, configs, **options) == "Final summary"
    assert child["tools"] == ["file_read", "ask_user_question"]
    with pytest.raises(PermissionError, match="expired"):
        await invoke_subagent(call, configs, **{**options, "grant_expires": 0})
    with pytest.raises(PermissionError, match="owned"):
        await invoke_subagent(call, [replace(configs[0], owner="bob")], **options)
    AgentRepository(db).delete("alice", child["id"])
    with pytest.raises(PermissionError, match="owned"):
        await invoke_subagent(call, configs, **options)


@pytest.mark.asyncio
async def test_source_wrapper_defaults_capability_rejection_and_cancellation(db):
    parent = {"subagents": {"enabled": True}}
    configs = build_subagent_configs("alice", parent, db)
    options = dict(owner="alice", conversation_id="c", parent_run_id="r", scopes=frozenset(), grant_expires=None, database=db)
    call = ModelToolCall("id", "subagent", {"subagent_type": "self", "description": " "})

    async def execute(invocation):
        assert invocation.messages == [{"role": "user", "content": "No task description provided"}]
        assert invocation.remaining_depth == 0
        return "result"

    assert await invoke_subagent(call, configs, execute_child=execute, **options) == "result"
    assert "Unknown subagent type" in await invoke_subagent(replace(call, arguments={}), configs, execute_child=execute, **options)
    assert "nesting depth" in await invoke_subagent(call, configs, execute_child=execute, max_depth=0, **options)
    with pytest.raises(ValueError, match="Unknown subagent"):
        await invoke_subagent(replace(call, name="delegate_agent"), configs, execute_child=execute, **options)
    with pytest.raises(ValueError, match="object"):
        await invoke_subagent(replace(call, arguments=[]), configs, execute_child=execute, **options)
    with pytest.raises(ValueError, match="host task store"):
        await invoke_subagent(replace(call, arguments={"subagent_type": "self", "run_in_background": True}), configs, execute_child=execute, **options)
    rejected = await invoke_subagent(replace(call, arguments={"subagent_type": "self", "subagent_thread_id": " thread "}), configs, execute_child=execute, **options)
    assert json.loads(rejected)["status"] == "rejected"

    async def cancel(invocation):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await invoke_subagent(call, configs, execute_child=cancel, **options)


@pytest.mark.asyncio
async def test_child_multi_step_real_provider_wire_and_native_tools_respect_revocation(tmp_path, monkeypatch):
    import httpx

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import lsm_tool_registry as registry
    from local_shell_mcp.webui.providers import ProviderConfig, stream_model_with_tools
    from local_shell_mcp.webui.routes import _repo

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    registry._registry_for_state.cache_clear()
    db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    repo = _repo()
    cid = repo.create_conversation("local", {"title": "Isolated child"})["conversationId"]
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    (tmp_path / "input.txt").write_text("isolate-secret", encoding="utf-8")
    child = _agent(db, "local", tools=["file_read", "file_write"])
    parent = _agent(db, "local", subagents={"enabled": True, "allowSelf": False, "agent_ids": [child["id"]]})
    configs = build_subagent_configs("local", parent, db)
    registry._registry()  # Import native MCP annotations before replacing the HTTP client.
    requests = []
    original = httpx.AsyncClient

    async def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "PARENT SECRET" not in str(body["messages"])
        names = {entry["function"]["name"] for entry in body["tools"]}
        assert names <= {"file_read", "file_write"}
        turn = (len(requests) - 1) % 3
        if turn == 0:
            delta = {"tool_calls": [{"index": 0, "id": "read", "type": "function",
                       "function": {"name": "file_read", "arguments": json.dumps({"path": "input.txt"})}}]}
        elif turn == 1:
            assert "isolate-secret" in body["messages"][-1]["content"]
            delta = {"tool_calls": [{"index": 0, "id": "write", "type": "function",
                       "function": {"name": "file_write", "arguments": json.dumps({"path": "output.txt", "content": "checked"})}}]}
        else:
            delta = {"content": "Summary only"}
        event = {"choices": [{"delta": delta}]}
        return httpx.Response(200, text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n",
                              headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))

    async def execute(invocation):
        history = list(invocation.messages)
        for _ in range(invocation.max_turns):
            tools = [entry for entry in registry.available_tools("local", cid, scopes=set(invocation.scopes))
                     if entry["function"]["name"] in invocation.selected_tools]
            calls, text = [], ""
            async for result in stream_model_with_tools(
                ProviderConfig("openai", "test", "https://provider.invalid", "secret"), history, tools=tools,
            ):
                if isinstance(result, ModelToolCall):
                    calls.append(result)
                else:
                    text += result
            if not calls:
                return [{"role": "assistant", "content": text}]
            history.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": call.call_id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}} for call in calls]})
            for call in calls:
                result = await registry.call_tool("local", cid, call, granted_scopes=set(invocation.scopes))
                history.append({"role": "tool", "tool_call_id": call.call_id, "content": result})
        raise AssertionError("child failed to settle")

    call = ModelToolCall("parent-call", "subagent", {"subagent_type": child["id"], "description": "Read input and write checked output"})
    options = dict(execute_child=execute, owner="local", conversation_id=cid, parent_run_id="parent-run",
                   scopes=frozenset({"shell:read", "shell:write"}), grant_expires=None, database=db)
    try:
        assert await invoke_subagent(call, configs, **options) == "Summary only"
        assert (tmp_path / "output.txt").read_text() == "checked"
        assert len(requests) == 3
        (tmp_path / "output.txt").unlink()
        repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
        rejected = await invoke_subagent(call, configs, **options)
        assert rejected.startswith("Subagent error:") and "read-only" in rejected
        assert not (tmp_path / "output.txt").exists()
    finally:
        registry._registry_for_state.cache_clear()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_child_errors_are_original_tool_text_except_graph_control_flow(db):
    configs = build_subagent_configs("alice", {"subagents": {"enabled": True}}, db)
    call = ModelToolCall("id", "subagent", {"subagent_type": "self"})
    options = dict(owner="alice", conversation_id="c", parent_run_id="r", scopes=frozenset(), grant_expires=None, database=db)

    async def provider_failure(invocation):
        raise RuntimeError("provider offline")

    assert await invoke_subagent(call, configs, execute_child=provider_failure, **options) == "Subagent error: provider offline"

    async def long_failure(invocation):
        raise RuntimeError("🙂" * 101)

    assert await invoke_subagent(call, configs, execute_child=long_failure, **options) == "Subagent error: " + "🙂" * 100 + "..."
    with pytest.raises(RuntimeError, match="offline"):
        await invoke_subagent(call, configs, execute_child=provider_failure,
                              propagate_error=lambda error: isinstance(error, RuntimeError), **options)
