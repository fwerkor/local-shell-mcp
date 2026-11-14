"""Differential against npm LangGraph 1.4.8 with real @langchain/core messages.

The reference vector generator instantiates actual HumanMessage, AIMessage,
ToolMessage and RemoveMessage classes (no fake coercion adapter). The generated
manifest asserts the exact integrated package versions and SDK commit.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.webui.message_reducers import messages_state_reducer

FIXTURE = Path(__file__).parent / "fixtures/librechat"
VECTORS = json.loads((FIXTURE / "graph_runtime_real_vectors.json").read_text())


def normalize(message):
    content = message.get("content", [] if message.get("role") == "remove" else "")
    return {"role": message["role"], "id": message["id"], "content": content,
            **({"tool_call_id": message["tool_call_id"]} if "tool_call_id" in message else {})}


def test_true_js_message_class_reducer_vectors():
    assert VECTORS["provenance"] == {
        "sdk_commit": "c4ffb9b1b78421bf63eba3e56993017f922387f3",
        "langgraph": "1.4.8", "core": "1.2.8", "checkpoint": "1.1.3",
        "actual_message_classes": True,
    }
    for index, (case, expected) in enumerate(zip(VECTORS["cases"], VECTORS["expected"], strict=True)):
        make_count = iter(range(100))

        def next_id(make_count=make_count):
            return f"auto:{next(make_count)}"
        try:
            out = messages_state_reducer(copy.deepcopy(case["left"]), copy.deepcopy(case["right"]),
                                         id_factory=next_id)
            got = {"messages": [normalize(msg) for msg in out]}
        except ValueError as error:
            got = {"error": str(error)}
        assert got == expected, (index, got, expected)


def test_pinned_real_node_oracle_executes_when_available():
    node = shutil.which("node")
    source_root = os.environ.get("LSM_JS_ORACLE_ROOT")
    if node is None or not source_root:
        assert os.environ.get("LSM_REQUIRE_SOURCE_ORACLES") != "1", (
            "Set LSM_JS_ORACLE_ROOT to a pinned npm package directory and add Node to PATH")
        return
    run = subprocess.check_output([node, str(FIXTURE / "graph_runtime_real_reference.cjs")],
                                  env=os.environ, cwd=source_root, timeout=20)
    assert json.loads(run) == VECTORS


@pytest.mark.asyncio
async def test_python_stategraph_vs_js_real_message_fanout_join_trace():
    pytest.importorskip("langgraph")
    from langgraph.graph import END, START, StateGraph

    from local_shell_mcp.webui.graph_runtime import MultiAgentState

    trace = []
    builder = StateGraph(MultiAgentState)
    for name in ("root", "left", "right", "join"):
        async def node(state, _name=name):
            trace.append(_name + ":" + ",".join(item["id"] for item in state["messages"]))
            return {"messages": [{"role": "assistant", "id": "known_" + _name, "content": _name}]}
        builder.add_node(name, node)
    builder.add_edge(START, "root")
    for dest in ("left", "right"):
        builder.add_edge("root", dest)
    builder.add_edge(["left", "right"], "join")
    builder.add_edge("join", END)
    result = await builder.compile().ainvoke({"messages": [{"role": "user", "id": "known_user", "content": "hello"}]})
    expected = VECTORS["traces"]["fanout"]
    assert trace == expected["trace"]
    assert result["messages"] == expected["messages"]


@pytest.mark.asyncio
async def test_python_command_and_send_traces_match_js_original():
    pytest.importorskip("langgraph")
    from langgraph.graph import START, StateGraph
    from langgraph.types import Command, Send

    from local_shell_mcp.webui.graph_runtime import MultiAgentState

    command = StateGraph(MultiAgentState)
    trace = []

    async def start(state):
        trace.append("start")
        return Command(update={"messages": [{"role": "assistant", "id": "known_start", "content": "start"}]},
                       goto=["left", "right"])

    command.add_node("start", start, destinations=("left", "right"))
    for name in ("left", "right"):
        async def finish(state, _name=name):
            trace.append(_name)
            return {"messages": [{"role": "assistant", "id": "known_" + _name, "content": _name}]}
        command.add_node(name, finish)
    command.add_edge(START, "start")
    result = await command.compile().ainvoke({"messages": [{"role": "user", "id": "known_user", "content": "hello"}]})
    expected = VECTORS["traces"]["command"]
    assert trace == expected["trace"] and result["messages"] == expected["messages"]

    sends = StateGraph(MultiAgentState)
    calls = []

    async def route(state):
        return Command(update={"messages": [{"role": "assistant", "id": "known_start", "content": "start"}]},
                       goto=[Send("recipient", {"messages": [{"role": "user", "id": "known_a", "content": "a"}]}),
                             Send("recipient", {"messages": [{"role": "user", "id": "known_b", "content": "b"}]})])

    async def recipient(state):
        text = state["messages"][-1]["content"]
        calls.append(text)
        return {"messages": [{"role": "assistant", "id": "known_reply_" + text, "content": "reply_" + text}]}

    sends.add_node("start", route, destinations=("recipient",))
    sends.add_node("recipient", recipient)
    sends.add_edge(START, "start")
    result = await sends.compile().ainvoke({"messages": [{"role": "user", "id": "known_user", "content": "hello"}]})
    expected = VECTORS["traces"]["sends"]
    assert calls == expected["trace"] and result["messages"] == expected["messages"]
