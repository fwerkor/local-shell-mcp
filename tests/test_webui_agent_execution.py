"""Original direct ToolNode batch ordering, replay and interruption semantics."""

import asyncio
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.webui.agent_execution import _same_args, execute_tool_batch, replay_key
from local_shell_mcp.webui.providers import ModelToolCall


def call(identity, name="read", arguments=None):
    return ModelToolCall(identity, name, arguments if arguments is not None else {"key": identity})


def test_replay_keys_and_argument_equality_match_original_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Original source differential oracle requires Node")
    values = [{}, {"x": 1}, {"x": 1.0}, {"x": True}, {"x": False},
              {"x": [1, "1"]}, {"x": None}, {"x": {"b": 2, "a": 1}},
              {"x": {"a": 1, "b": 2}}, {"x": -0.0}]
    pairs = list(itertools.product(values, repeat=2))
    fixture = Path(__file__).parent / "fixtures/librechat/tool_batch_reference.cjs"
    script = """
const fs=require('fs'), p=require(process.argv[1]);
const pairs=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify({equal:pairs.map(([a,b])=>p.recordArgsEqual(a,b)),
keys:[p.directReplayKey({id:'call'},0),p.directReplayKey({id:''},2),p.directReplayKey({},3)]}));
"""
    expected = json.loads(subprocess.check_output([node, "-e", script, str(fixture.resolve())],
                                                  input=json.dumps(pairs).encode()))
    assert [_same_args(a, b) for a, b in pairs] == expected["equal"]
    assert [replay_key(call("call"), 0), replay_key(call(""), 2), replay_key(call(None), 3)] == expected["keys"]


@pytest.mark.asyncio
async def test_batch_executes_concurrently_but_returns_provider_order_and_replays():
    calls = [call("first"), call("second")]
    both_started = asyncio.Event()
    started = []
    saved = []
    cache = {}

    async def execute(item):
        started.append(item.call_id)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 1)
        return {"id": item.call_id}

    async def complete(item, result):
        saved.append((item.call_id, result))

    assert await execute_tool_batch(calls, execute, settled=cache, on_completed=complete) == [
        {"id": "first"}, {"id": "second"},
    ]
    assert len(saved) == 2
    replayed = await execute_tool_batch(calls, execute, settled=cache)
    replayed[0]["id"] = "mutated"
    assert len(started) == 2
    assert cache[replay_key(calls[0], 0)]["output"]["id"] == "first"
    with pytest.raises(ValueError, match="Cannot change"):
        await execute_tool_batch([call("first", arguments={"key": "changed"})], execute, settled=cache)
    with pytest.raises(ValueError, match="Cannot change"):
        await execute_tool_batch([call("first", name="other")], execute, settled=cache)


class Pause(Exception):
    pass


@pytest.mark.asyncio
async def test_interrupting_siblings_finish_before_pause_and_ordinary_tools_never_start():
    order = []
    finished = asyncio.Event()

    async def execute(item):
        if item.name == "pause":
            await asyncio.wait_for(finished.wait(), 1)
            raise Pause("waiting for user")
        order.append(item.name)
        finished.set()
        return item.name

    with pytest.raises(Pause):
        await execute_tool_batch([call("1", "pause"), call("2", "child"), call("3", "write")],
                                 execute, interrupting_names=frozenset({"pause", "child"}),
                                 is_interrupt=lambda error: isinstance(error, Pause))
    assert order == ["child"]


@pytest.mark.asyncio
async def test_successful_interrupting_group_then_regular_group_keep_original_positions():
    order = []

    async def execute(item):
        order.append(item.name)
        return item.call_id

    assert await execute_tool_batch([call("1", "write"), call("2", "child")], execute,
                                    interrupting_names=frozenset({"child"})) == ["1", "2"]
    assert order == ["child", "write"]


@pytest.mark.asyncio
async def test_safety_errors_beat_pause_in_normal_group_and_wait_for_siblings():
    settled = []

    async def execute(item):
        settled.append(item.name)
        if item.name == "pause":
            raise Pause()
        raise PermissionError("revoked")

    with pytest.raises(PermissionError, match="revoked"):
        await execute_tool_batch([call("1", "pause"), call("2", "denied")], execute,
                                 is_interrupt=lambda error: isinstance(error, Pause))
    assert settled == ["pause", "denied"]


@pytest.mark.asyncio
async def test_breaker_before_dispatch_and_after_interrupting_group():
    executed = []

    async def execute(item):
        executed.append(item.name)
        return "done"

    def breaker():
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        await execute_tool_batch([call("1")], execute, check_breaker=breaker)
    assert executed == []
    checks = 0

    def later():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        await execute_tool_batch([call("1", "child"), call("2", "write")], execute,
                                 interrupting_names=frozenset({"child"}), check_breaker=later)
    assert executed == ["child"]


@pytest.mark.asyncio
async def test_cancel_stops_every_sibling_and_does_not_cache_unfinished_work():
    started = asyncio.Event()
    finished = []
    cache = {}

    async def execute(item):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.append(item.call_id)

    task = asyncio.create_task(execute_tool_batch([call("1"), call("2")], execute, settled=cache))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert set(finished) == {"1", "2"}
    assert cache == {}


@pytest.mark.asyncio
async def test_failed_completion_persistence_does_not_mark_tool_replayable():
    cache = {}

    async def execute(item):
        return "side effect completed"

    async def complete(item, result):
        raise OSError("database full")

    with pytest.raises(OSError, match="database full"):
        await execute_tool_batch([call("1")], execute, settled=cache, on_completed=complete)
    assert cache == {}
    assert await execute_tool_batch([], execute) == []
