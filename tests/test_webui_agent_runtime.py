"""Model/tools/model topology from agents Graph.ts and shared runtime boundaries."""

import asyncio
import copy
import json

import pytest

from local_shell_mcp.webui.agent_runtime import (
    AgentContext,
    AgentLoopState,
    AgentSuspended,
    ToolBatchOutput,
    run_agent_loop,
)
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


def profile(name="root"):
    return ProviderConfig("openai", name, "https://model.invalid", "test-secret")


async def forbidden(*args, **kwargs):
    raise AssertionError("This graph edge must not execute")


@pytest.mark.asyncio
async def test_no_tools_routes_directly_to_model_and_end_with_parameters():
    state = AgentLoopState(AgentContext(profile(), [], {
        "max_tokens": 999999, "temperature": -10,
    }), [{"role": "user", "content": "question"}])
    rendered = []
    saved = []

    async def stream(model, messages, **kwargs):
        assert model.model == "root" and messages == [{"role": "user", "content": "question"}]
        assert kwargs == {"max_tokens": 999999, "temperature": 0.0}
        yield "Hello"
        yield ""
        yield " world"

    async def on_text(text):
        rendered.append(text)

    async def save(current, calls):
        saved.append((current.step, current.model_turn, copy.deepcopy(current.messages), list(calls)))

    result = await run_agent_loop(state, stream_tools=forbidden, stream_text=stream,
                                  dispatch=forbidden, on_text=on_text, save_state=save)
    assert result is state.messages
    assert result[-1] == {"role": "assistant", "content": "Hello world"}
    assert rendered == ["Hello", " world"]
    assert saved == [(1, 1, result, [])]


@pytest.mark.asyncio
async def test_more_than_three_tool_rounds_follow_source_model_tools_cycle():
    tools = [{"type": "function", "function": {"name": "file_read"}}]
    state = AgentLoopState(AgentContext(profile(), tools, {"max_output_tokens": 32, "temperature": 9}),
                           [{"role": "user", "content": "read files"}])
    dispatches = []
    rendered = []
    checkpoints = []
    turns = 0

    async def stream(model, messages, **kwargs):
        nonlocal turns
        turns += 1
        assert kwargs == {"tools": tools, "max_tokens": 32, "temperature": 2.0}
        if turns <= 5:
            if turns > 1:
                assert messages[-1]["role"] == "tool"
                assert messages[-1]["content"] == "native result " + str(turns - 1)
            yield "before tool " + str(turns)
            yield ModelToolCall("call-" + str(turns), "file_read", {"path": "/tmp/" + str(turns)})
        else:
            yield "final answer"

    async def dispatch(calls, current):
        assert current.messages[-1]["content"] == "before tool " + str(turns)
        serialized = current.messages[-1]["tool_calls"][0]
        assert serialized["id"] == calls[0].call_id
        assert json.loads(serialized["function"]["arguments"]) == calls[0].arguments
        dispatches.append((current.step, calls[0].name, calls[0].arguments))
        return ToolBatchOutput([{"role": "tool", "tool_call_id": calls[0].call_id,
                                 "content": "native result " + str(turns)}])

    async def on_text(text):
        rendered.append(text)

    async def save(current, calls):
        checkpoints.append((current.step, current.model_turn, len(calls), copy.deepcopy(current.messages)))

    await run_agent_loop(state, stream_tools=stream, stream_text=forbidden, dispatch=dispatch,
                         on_text=on_text, save_state=save)
    assert state.step == 11 and state.model_turn == 6
    assert [step for step, _, _ in dispatches] == [2, 4, 6, 8, 10]
    assert len(state.messages) == 12
    assert rendered == ["before tool " + str(i) for i in range(1, 6)] + ["final answer"]
    assert [pending for _, _, pending, _ in checkpoints] == [1, 1, 0] * 5 + [0]


@pytest.mark.asyncio
async def test_handoff_switches_profile_tools_messages_and_checkpoint_context_before_resuming():
    root = AgentContext(profile(), [{"name": "transfer_to_writer"}], tool_end=True, agent={"id": "root"})
    writer = AgentContext(profile("writer"), [], agent={"id": "writer"})
    state = AgentLoopState(root, [{"role": "user", "content": "write"}])
    checkpoints = []
    replacements = [{"role": "system", "content": "writer instructions"},
                    {"role": "user", "content": "handoff context"}]

    async def root_stream(model, messages, **kwargs):
        assert model.model == "root"
        yield ModelToolCall("handoff-1", "transfer_to_writer", {})

    async def writer_stream(model, messages, **kwargs):
        assert model.model == "writer"
        assert messages == replacements + [{"role": "tool", "tool_call_id": "handoff-1", "content": "transferred"}]
        yield "written"

    async def dispatch(calls, current):
        return ToolBatchOutput([{"role": "tool", "tool_call_id": "handoff-1", "content": "transferred"}],
                               next_context=writer, replace_messages=copy.deepcopy(replacements))

    async def save(current, calls):
        checkpoints.append((current.context.profile.model, len(calls), copy.deepcopy(current.messages)))

    async def on_text(text):
        assert text == "written"

    await run_agent_loop(state, stream_tools=root_stream, stream_text=writer_stream,
                         dispatch=dispatch, on_text=on_text, save_state=save)
    assert state.context is writer and state.messages[-1]["content"] == "written"
    assert [name for name, _, _ in checkpoints] == ["root", "root", "writer", "writer"]
    assert checkpoints[2][2] == replacements + [{"role": "tool", "tool_call_id": "handoff-1", "content": "transferred"}]


@pytest.mark.asyncio
async def test_tool_end_stops_after_tool_results_without_another_provider_call():
    state = AgentLoopState(AgentContext(profile(), [{"name": "file_read"}], tool_end=True), [])
    calls = 0

    async def stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield ModelToolCall("call", "file_read", {"path": "/tmp/a"})

    async def dispatch(batch, current):
        return ToolBatchOutput([{"role": "tool", "tool_call_id": "call", "content": "result"}])

    result = await run_agent_loop(state, stream_tools=stream, stream_text=forbidden,
                                  dispatch=dispatch, on_text=forbidden)
    assert calls == 1 and result[-1]["content"] == "result" and state.step == 2


@pytest.mark.asyncio
async def test_human_suspend_propagates_after_proposal_checkpoint_without_finalization():
    state = AgentLoopState(AgentContext(profile(), [{"name": "ask_user_question"}]), [])
    saves = []

    async def stream(*args, **kwargs):
        yield ModelToolCall("question", "ask_user_question", {"questions": [{"id": "where", "question": "Where?"}]})

    async def dispatch(calls, current):
        assert current.step == 2 and calls[0].name == "ask_user_question"
        raise AgentSuspended("durable question saved")

    async def save(current, calls):
        saves.append((current.step, copy.deepcopy(current.messages), [call.call_id for call in calls]))

    with pytest.raises(AgentSuspended, match="durable question"):
        await run_agent_loop(state, stream_tools=stream, stream_text=forbidden, dispatch=dispatch,
                             on_text=forbidden, save_state=save)
    assert len(saves) == 2 and saves[0][2] == ["question"] and saves[1][0] == 2
    assert state.messages[-1]["tool_calls"][0]["id"] == "question"


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,dispatch_count", [(0, 0), (1, 0), (2, 1), (3, 1), (4, 2)])
async def test_recursion_budget_counts_model_and_tools_nodes(budget, dispatch_count):
    state = AgentLoopState(AgentContext(profile(), [{"name": "job_get"}], recursion_limit=budget), [])
    dispatched = []

    async def stream(*args, **kwargs):
        yield ModelToolCall("call-" + str(state.model_turn), "job_get", {"job_id": "job"})

    async def dispatch(calls, current):
        dispatched.append(calls[0].call_id)
        return ToolBatchOutput([{"role": "tool", "tool_call_id": calls[0].call_id, "content": "result"}])

    with pytest.raises(ValueError, match="Recursion limit"):
        await run_agent_loop(state, stream_tools=stream, stream_text=forbidden, dispatch=dispatch, on_text=forbidden)
    assert state.step == budget and len(dispatched) == dispatch_count


@pytest.mark.asyncio
async def test_provider_failure_and_cancellation_propagate_without_fabricating_messages():
    state = AgentLoopState(AgentContext(profile(), []), [])

    async def failed(*args, **kwargs):
        raise RuntimeError("provider failed")
        yield "unreachable"

    with pytest.raises(RuntimeError, match="provider failed"):
        await run_agent_loop(state, stream_tools=forbidden, stream_text=failed,
                             dispatch=forbidden, on_text=forbidden)
    assert state.messages == []
    ready = asyncio.Event()

    async def blocked(*args, **kwargs):
        ready.set()
        await asyncio.Event().wait()
        yield "unreachable"

    task = asyncio.create_task(run_agent_loop(state, stream_tools=forbidden, stream_text=blocked,
                                              dispatch=forbidden, on_text=forbidden))
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.messages == []


@pytest.mark.asyncio
async def test_resuming_started_tool_node_replays_tools_before_model_without_recharging_step():
    call = ModelToolCall("pending", "file_read", {"path": "/tmp/a"})
    state = AgentLoopState(AgentContext(profile(), [{"name": "file_read"}], recursion_limit=3),
                           [{"role": "assistant", "content": "before tool", "tool_calls": [{"id": "pending"}]}],
                           step=2, model_turn=1, pending_calls=[call], tool_step_started=True)
    order = []
    saves = []

    async def dispatch(calls, current):
        order.append("tools")
        assert current.step == 2 and current.model_turn == 1 and calls == [call]
        return ToolBatchOutput([{"role": "tool", "tool_call_id": "pending", "content": "restored output"}])

    async def stream(model, messages, **kwargs):
        order.append("model")
        assert messages[-1]["content"] == "restored output"
        yield "final"

    async def save(current, calls):
        saves.append((current.step, current.tool_step_started, [item.call_id for item in current.pending_calls]))

    async def on_text(text):
        assert text == "final"

    await run_agent_loop(state, stream_tools=stream, stream_text=forbidden, dispatch=dispatch,
                         on_text=on_text, save_state=save)
    assert order == ["tools", "model"]
    assert saves == [(2, False, []), (3, False, [])]
    assert state.step == 3 and state.model_turn == 2


@pytest.mark.asyncio
async def test_suspend_then_resume_same_checkpoint_advances_without_another_proposal():
    state = AgentLoopState(AgentContext(profile(), [{"name": "ask_user_question"}], recursion_limit=3), [])
    provider_calls = 0
    dispatch_calls = 0

    async def stream(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            yield ModelToolCall("question", "ask_user_question", {"questions": [{"id": "where", "question": "Where?"}]})
        else:
            assert state.messages[-1]["content"] == '{"answers":{"where":"here"}}'
            yield "done"

    async def dispatch(calls, current):
        nonlocal dispatch_calls
        dispatch_calls += 1
        assert current.step == 2 and calls[0].call_id == "question"
        if dispatch_calls == 1:
            raise AgentSuspended()
        return ToolBatchOutput([{"role": "tool", "tool_call_id": "question", "content": '{"answers":{"where":"here"}}'}])

    async def on_text(text):
        assert text == "done"

    with pytest.raises(AgentSuspended):
        await run_agent_loop(state, stream_tools=stream, stream_text=forbidden, dispatch=dispatch, on_text=on_text)
    assert state.step == 2 and state.tool_step_started and len(state.pending_calls) == 1
    await run_agent_loop(state, stream_tools=stream, stream_text=forbidden, dispatch=dispatch, on_text=on_text)
    assert provider_calls == 2 and dispatch_calls == 2 and state.step == 3
    assert not state.pending_calls and not state.tool_step_started
