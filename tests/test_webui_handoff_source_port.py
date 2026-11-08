"""Source oracle and behavior tests for SDK handoff routing and tool commands."""

import copy
import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_shell_mcp.webui.handoff import (
    PARENT,
    HandoffLimitError,
    HandoffRouting,
    build_handoff_command,
    combine_handoff_commands,
    handoff_edge_for_call,
    handoff_tools,
    merge_handoff_state,
    outgoing_handoff_edges,
    receive_handoff,
)


def state(limit=None, *, transitions=None, parallel=False, execution="turn"):
    return {"version": 1, "executionId": execution, "entryAgentId": "a",
            **({"maxHandoffs": limit} if limit is not None else {}),
            "transitions": transitions or [], "parallel": parallel}


def command(destination="b", call_id="call", scope="turn", graph=PARENT):
    return {"graph": graph, "goto": destination, "update": {"handoffRequest": {
        "sourceAgentId": "a", "targetAgentId": destination,
        "toolCallId": call_id, "scope": scope}}}


def node_oracle(cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("Original SDK oracle requires development-only Node")
    fixture = Path(__file__).parent / "fixtures/librechat/handoff_reference.cjs"
    script = """
const fs = require('fs'), p = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(c => {
 const route = new p.HandoffRouting('a', c.limit ?? undefined, c.parallel || false);
 try {
   route.restore(c.state);
   for (const step of c.steps) route.finalize(step.commands, step.input, step.config || {});
   return {state: route.snapshot(), commands: c.steps.map(s => s.commands), outcome: route.outcome(c.reason)};
 } catch (error) { return {error:error.message,name:error.name}; }
})));
"""
    return json.loads(subprocess.check_output([node, "-e", script, str(fixture.resolve())],
                                              input=json.dumps(cases).encode(), env=os.environ))


def test_original_sdk_differential_routing_budget_scope_parallel_and_replay():
    cases = []
    for limit, scope, parallel, count, replay in itertools.product(
            [None, 0, 1, 2], ["turn", "conversation"], [False, True], [0, 1, 2], [False, True]):
        initial = state(limit, parallel=parallel)
        commands = [command("b" if n == 0 else "c", "call-" + str(n), scope) for n in range(count)]
        if parallel and commands:
            commands = [{"graph": PARENT, "goto": [
                {"lg_name": "Send", "node": cmd["goto"], "args": cmd["update"]} for cmd in commands]}]
        step = {"commands": commands, "input": {"messages": [{"id": "assistant"}], "handoffState": initial},
                "config": {"configurable": {"checkpoint_ns": "namespace"}}}
        cases.append({"limit": limit, "parallel": parallel, "state": initial,
                      "steps": [step, copy.deepcopy(step)] if replay else [step]})
    expected = node_oracle(copy.deepcopy(cases))
    results = []
    for case in copy.deepcopy(cases):
        route = HandoffRouting("a", case["limit"], case["parallel"])
        try:
            route.restore(case["state"])
            for step in case["steps"]:
                route.finalize(step["commands"], step["input"], step["config"])
            results.append({"state": route.snapshot(), "commands": [step["commands"] for step in case["steps"]],
                            "outcome": route.outcome(case.get("reason"))})
        except ValueError as error:
            results.append({"error": str(error), "name": "HandoffLimitError" if isinstance(error, HandoffLimitError) else "Error"})
    assert results == expected


def test_identity_union_conflicts_and_snapshot_are_independent():
    transition = {"id": "a", "sourceAgentId": "a", "targetAgentId": "b",
                  "toolCallId": "call", "scope": "conversation", "depth": 0}
    current = state(transitions=[transition])
    update = state(transitions=[{**transition, "id": "b", "targetAgentId": "c", "depth": 1}], parallel=True)
    assert merge_handoff_state(None, current) is current
    assert merge_handoff_state(current, None) is current
    assert merge_handoff_state(current, update) == merge_handoff_state(update, current)
    assert len(merge_handoff_state(current, current)["transitions"]) == 1
    for other, error in [
        (state(execution="other"), "different logical turns"),
        ({**state(), "entryAgentId": "b"}, "Conflicting handoff checkpoint"),
        (state(1), "Conflicting handoff checkpoint"),
        (state(transitions=[{**transition, "targetAgentId": "c"}]), "Conflicting replayed"),
    ]:
        with pytest.raises(ValueError, match=error):
            merge_handoff_state(current, other)
    route = HandoffRouting("a")
    route.restore(current)
    snapshot = route.snapshot()
    snapshot["transitions"][0]["targetAgentId"] = "changed"
    assert route.snapshot()["transitions"][0]["targetAgentId"] == "b"
    assert route.outcome()["agentId"] == "b"
    assert route.outcome("cancelled")["status"] == "incomplete"
    with pytest.raises(ValueError, match="different handoff execution"):
        route.restore(state(execution="other"))
    route.start()
    assert route.snapshot()["transitions"] == []
    for value in [-1, True, 2 ** 53, 1.5]:
        with pytest.raises(ValueError, match="non-negative safe integer"):
            HandoffRouting("a", value)
    for bad in [{**state(), "version": 2}, {**state(), "entryAgentId": "b"}, state(1)]:
        with pytest.raises(ValueError):
            HandoffRouting("a").restore(bad)
    route.restore(None)
    route.resume(None)
    assert route.outcome()["reason"] == "legacy_checkpoint"
    with pytest.raises(ValueError, match="without routing state"):
        HandoffRouting("a", 1).resume(None)


def test_replay_cannot_change_destination_and_budget_failure_leaves_batch_unmodified():
    route = HandoffRouting("a", 1)
    initial = route.start()
    source = {"messages": [{"id": "message"}], "handoffState": initial}
    first = command()
    route.finalize([first], source)
    with pytest.raises(ValueError, match="changed its destination"):
        route.finalize([command("c")], source)
    second = command("c", "second")
    with pytest.raises(HandoffLimitError):
        route.finalize([second], {"messages": [{"id": "other"}]})
    assert "handoffRequest" in second["update"]
    assert len(route.snapshot()["transitions"]) == 1
    route.finalize([{"graph": "elsewhere"}, {"graph": PARENT, "update": {}}], source)
    assert len(route.snapshot()["transitions"]) == 1


def test_tools_come_only_from_edges_and_enforce_agent_ownership():
    agent = {"id": "a", "edges": [{"from": "a", "to": ["b", "c"], "edgeType": "handoff",
                                       "prompt": "Explain the task", "promptKey": "context"},
                                      {"from": "b", "to": "d", "edgeType": "handoff"}]}
    repository = SimpleNamespace(get=lambda owner, identity: {"id": identity} if owner == "alice" else None)
    tools = handoff_tools("alice", agent, repository)
    assert [tool["function"]["name"] for tool in tools] == ["transfer_to_b", "transfer_to_c"]
    assert tools[0]["function"]["parameters"] == {"type": "object", "properties": {
        "context": {"type": "string", "description": "Explain the task"}}, "required": []}
    assert handoff_edge_for_call("alice", agent, repository, "transfer_to_b") is agent["edges"][0]
    with pytest.raises(PermissionError, match="not enabled"):
        handoff_edge_for_call("alice", agent, repository, "handoff_agent")
    with pytest.raises(PermissionError, match="not owned"):
        handoff_tools("bob", agent, repository)
    assert outgoing_handoff_edges({"id": "a"}) == []
    for edge in [None, {"from": "a", "to": "b", "edgeType": "direct", "handoffScope": "turn"},
                 {"from": "a", "to": "b", "edgeType": "handoff", "handoffScope": "bad"},
                 {"from": "a", "to": [], "edgeType": "handoff"}]:
        with pytest.raises(ValueError):
            outgoing_handoff_edges({"id": "a", "edges": [edge]})
    conflict = [{"from": "a", "to": "b", "edgeType": "handoff", "handoffScope": scope}
                for scope in ("turn", "conversation")]
    with pytest.raises(ValueError, match="Conflicting handoffScope"):
        outgoing_handoff_edges({"id": "a", "edges": conflict})


def test_parallel_transfer_preserves_pairing_and_recipient_has_clean_context():
    edge = {"from": "a", "to": ["b", "c"], "edgeType": "handoff", "prompt": "Task"}
    messages = [{"role": "user", "content": "task"}, {"role": "assistant", "id": "ai",
        "content": "", "provider_data": {"thoughtSignature": "keep"}, "tool_calls": [
            {"id": "one", "function": {"name": "transfer_to_b"}},
            {"id": "two", "function": {"name": "transfer_to_c"}}]}]
    commands = [build_handoff_command(edge, "a", "Router", "transfer_to_" + target,
                                     {"instructions": "Work " + target}, call, messages)
                for target, call in [("b", "one"), ("c", "two")]]
    assert commands[0]["update"]["messages"][-2]["tool_calls"] == [messages[-1]["tool_calls"][0]]
    assert commands[0]["update"]["messages"][-2]["provider_data"] == {"thoughtSignature": "keep"}
    combined = combine_handoff_commands(commands, parallel_batch="12345678")
    route = HandoffRouting("a")
    initial = route.start()
    route.finalize(combined, {"messages": messages, "handoffState": initial})
    assert route.snapshot()["parallel"] is True
    assert len(route.snapshot()["transitions"]) == 2
    for send in combined[0]["goto"]:
        assert send["args"]["handoffState"]["parallel"] is True
        reception = receive_handoff(send["args"]["messages"], send["node"], agent_names={"b": "Bee", "c": "See"})
        assert reception["filteredMessages"] == messages[:1]
        assert reception["instructions"] == "Work " + send["node"]
        assert reception["sourceAgentName"] == "Router"
        assert len(reception["parallelSiblings"]) == 1
        assert reception["parallelGroupId"] > 2 ** 48
    assert receive_handoff(messages, "b") is None
    stale = commands[0]["update"]["messages"] + [{"role": "assistant", "content": "already received"}]
    assert receive_handoff(stale, "b") is None
    assert receive_handoff([], "b") is None
    with pytest.raises(PermissionError):
        build_handoff_command(edge, "a", "Router", "transfer_to_foreign", {}, "bad", messages)
    with pytest.raises(ValueError, match="must be a string"):
        build_handoff_command(edge, "a", "Router", "transfer_to_b", {"instructions": 123}, "bad", messages)


def test_conditional_transfer_destination_admission_and_mixed_commands():
    edge = {"from": "a", "to": ["b", "c"], "edgeType": "handoff", "condition": lambda state: "c"}
    repo = SimpleNamespace(get=lambda owner, identity: {"id": identity})
    assert handoff_tools("alice", {"id": "a", "edges": [edge]}, repo)[0]["function"]["name"] == "conditional_transfer"
    assert handoff_edge_for_call("alice", {"id": "a", "edges": [edge]}, repo, "conditional_transfer") is edge
    transfer = build_handoff_command(edge, "a", "Router", "conditional_transfer", {}, "call", [])
    assert transfer["goto"] == "c"
    assert transfer["update"]["messages"][-1]["additional_kwargs"]["handoff_destination"] == "c"
    assert build_handoff_command(edge, "a", "Router", "conditional_transfer", {}, "call", [], condition=lambda state: False) is None
    assert build_handoff_command(edge, "a", "Router", "conditional_transfer", {}, "call", [], condition=lambda state: True)["goto"] == "b"
    assert build_handoff_command(edge, "a", "Router", "conditional_transfer", {}, "call", [], condition=lambda state: ["b"])["goto"] == "b"
    with pytest.raises(ValueError, match="undeclared"):
        build_handoff_command(edge, "a", "Router", "conditional_transfer", {}, "call", [], condition=lambda state: "foreign")
    with pytest.raises(ValueError, match="match exactly"):
        build_handoff_command(edge, "a", "Router", "transfer_to_c", {}, "call", [])
    bad = {**edge, "condition": "unknown"}
    with pytest.raises(ValueError, match="condition resolver"):
        handoff_tools("alice", {"id": "a", "edges": [bad]}, repo)
    with pytest.raises(ValueError, match="condition resolver"):
        build_handoff_command(bad, "a", "Router", "conditional_transfer", {}, "call", [])
    normal = command()
    assert combine_handoff_commands([normal]) == [normal]
    other = {"graph": "other", "goto": "node"}
    send = {"graph": PARENT, "goto": [{"lg_name": "Send", "node": "b", "args": {}}]}
    assert combine_handoff_commands([other, send]) == [other, send]


def test_reception_retains_nontransfer_tools_and_array_content_without_orphans():
    calls = [{"id": "transfer", "name": "transfer_to_b"}, {"id": "native", "name": "file_read"}]
    messages = [{"role": "user", "content": "task"},
                {"role": "assistant", "id": "ai", "tool_calls": calls, "content": [
                    {"type": "text", "text": "inspect"},
                    {"type": "tool_use", "id": "transfer", "name": "transfer_to_b"},
                    {"type": "tool_use", "id": "sibling", "name": "transfer_to_c"},
                    {"type": "tool_use", "id": "native", "name": "file_read"}]},
                {"role": "tool", "tool_call_id": "native", "name": "file_read", "content": "contents"},
                {"role": "tool", "tool_call_id": "transfer", "name": "transfer_to_b", "content": "handoff",
                 "additional_kwargs": {"handoff_instructions": " context ", "handoff_source_name": "Router"}}]
    received = receive_handoff(messages, "b")
    assert received["instructions"] == "context"
    assert received["filteredMessages"][1]["tool_calls"] == [calls[1]]
    assert received["filteredMessages"][1]["content"] == [
        {"type": "text", "text": "inspect"},
        {"type": "tool_use", "id": "native", "name": "file_read"}]
    assert received["filteredMessages"][-1] == messages[-2]
    assert receive_handoff(messages, "foreign") is None
    extra = {"role": "tool", "tool_call_id": "unrelated", "name": "file_list", "content": "ok"}
    assert receive_handoff(messages + [extra], "b")["filteredMessages"][-1] == extra
    null_name = {"role": "tool", "tool_call_id": "weird", "content": "ok"}
    assert receive_handoff(messages + [null_name], "b")["filteredMessages"][-1] == null_name
    one = build_handoff_command({"to": "b"}, "a", "Router", "transfer_to_b", {}, "transfer", messages[:2])
    assert len(one["update"]["messages"][-2]["tool_calls"]) == 1
    single = [{"role": "assistant", "tool_calls": [calls[0]], "content": "reason"}]
    command_value = build_handoff_command({"to": "b"}, "a", "Router", "transfer_to_b", {}, "transfer", single)
    assert receive_handoff(command_value["update"]["messages"], "b")["filteredMessages"][0]["content"] == "reason"


def test_handoff_restore_from_checkpoint_and_outcome_ambiguity():
    route = HandoffRouting("a")
    initial = route.start()
    route.resume(initial)
    requests = [command("b", "one", "conversation"), command("c", "two", "conversation")]
    route.finalize(combine_handoff_commands(requests, parallel_batch="batch123"), {"messages": []})
    restored = HandoffRouting("a")
    restored.resume(json.loads(json.dumps(route.snapshot())))
    assert restored.outcome()["status"] == "ambiguous"
    assert restored.snapshot() == route.snapshot()
    snapshot = restored.snapshot()
    snapshot["parallel"] = False
    snapshot["transitions"][0]["depth"] = 2
    snapshot["transitions"][1]["depth"] = 1
    another = HandoffRouting("a")
    another.restore(snapshot)
    assert another.outcome()["agentId"] == "b"


def test_identity_union_sort_matches_sdk_ascii_identity_collation():
    import random

    node = shutil.which("node")
    if not node:
        pytest.skip("Original SDK oracle requires development-only Node")
    randomizer = random.Random(343)
    alphabet = "_-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    cases = []
    for _ in range(40):
        identities = ["".join(randomizer.choice(alphabet) for _ in range(8)) for _ in range(20)]
        transitions = [{"id": identity, "sourceAgentId": "a", "targetAgentId": "b", "toolCallId": "call",
                        "scope": "turn", "depth": randomizer.randrange(3)} for identity in identities]
        cases.append([state(transitions=transitions[:10]), state(transitions=transitions[10:])])
    fixture = Path(__file__).parent / "fixtures/librechat/handoff_reference.cjs"
    script = "const fs=require('fs'),p=require(process.argv[1]);process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8')).map(([a,b])=>p.mergeHandoffState(a,b))));"
    expected = json.loads(subprocess.check_output([node, "-e", script, str(fixture.resolve())], input=json.dumps(cases).encode()))
    assert [merge_handoff_state(a, b) for a, b in cases] == expected
