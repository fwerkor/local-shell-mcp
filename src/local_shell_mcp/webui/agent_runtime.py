"""Model/tools graph-node loop derived from agents Graph.ts createAgentWorkflow.

The graph is START -> agent -> tools -> agent, or agent -> END. Transport,
ToolNode dispatch, human interruptions and checkpoint storage are injected by
LSM rather than maintaining separate provider or machine execution systems.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .providers import ModelToolCall, ProviderConfig


class RuntimeSafetyError(PermissionError):
    """A revoked grant or execution boundary stops the complete run."""


class AgentSuspended(Exception):
    """A durable human interrupt has been saved; leave the generation parked."""


@dataclass
class AgentContext:
    profile: ProviderConfig
    tools: list[dict]
    parameters: dict = field(default_factory=dict)
    recursion_limit: int = 50
    tool_end: bool = False
    agent: dict | None = None


@dataclass
class AgentLoopState:
    context: AgentContext
    messages: list[dict]
    step: int = 0
    model_turn: int = 0
    pending_calls: list[ModelToolCall] = field(default_factory=list)
    tool_step_started: bool = False
    completed: bool = False
    graph_commands: list[dict] = field(default_factory=list)


@dataclass
class ToolBatchOutput:
    messages: list[dict]
    next_context: AgentContext | None = None
    replace_messages: list[dict] | None = None
    graph_commands: list[dict] = field(default_factory=list)


async def run_agent_loop(
    state: AgentLoopState,
    *,
    stream_tools: Callable[..., AsyncIterator[str | ModelToolCall]],
    stream_text: Callable[..., AsyncIterator[str]],
    dispatch: Callable[[list[ModelToolCall], AgentLoopState], Awaitable[ToolBatchOutput]],
    on_text: Callable[[str], Awaitable[None]],
    save_state: Callable[[AgentLoopState, list[ModelToolCall]], Awaitable[None]] | None = None,
    inject_controls: Callable[[AgentLoopState, str], Awaitable[bool]] | None = None,
    should_preempt: Callable[[], bool] | None = None,
) -> list[dict]:
    if state.completed:
        return state.messages
    while True:
        if state.pending_calls:
            context = state.context
            if not state.tool_step_started:
                if state.step >= context.recursion_limit:
                    raise ValueError("Recursion limit reached without hitting a stop condition")
                state.step += 1
                state.tool_step_started = True
                if save_state is not None:
                    await save_state(state, state.pending_calls)
            output = await dispatch(state.pending_calls, state)
            if output.replace_messages is not None:
                state.messages = output.replace_messages
            state.messages.extend(output.messages)
            if output.next_context is not None:
                state.context = output.next_context
            state.pending_calls = []
            state.tool_step_started = False
            state.graph_commands = output.graph_commands
            state.completed = bool(output.graph_commands) or (output.next_context is None and context.tool_end)
            if save_state is not None:
                await save_state(state, [])
            if state.completed:
                return state.messages
            if inject_controls is not None:
                await inject_controls(state, "tool")
            continue
        if inject_controls is not None:
            await inject_controls(state, "tool")
        if state.step >= state.context.recursion_limit:
            raise ValueError("Recursion limit reached without hitting a stop condition")
        context = state.context
        state.step += 1
        state.model_turn += 1
        params = context.parameters
        max_tokens = max(1, min(int(next((params[key] for key in ("max_tokens", "maxTokens", "max_output_tokens", "maxOutputTokens")
                                          if params.get(key) is not None), 2048)), 16384))
        temperature = params.get("temperature")
        if temperature is not None:
            temperature = max(0.0, min(float(temperature), 2.0))
        top_p = next((params[key] for key in ("top_p", "topP") if params.get(key) is not None), None)
        if top_p is not None:
            top_p = max(0.0, min(float(top_p), 1.0))
        sampling = {"max_tokens": max_tokens, "temperature": temperature}
        if top_p is not None:
            sampling["top_p"] = top_p
        calls: list[ModelToolCall] = []
        text_parts: list[str] = []
        source = stream_tools(context.profile, state.messages, tools=context.tools,
                              **sampling) if context.tools else \
            stream_text(context.profile, state.messages, **sampling)
        preempted = False
        async for item in source:
            if isinstance(item, ModelToolCall):
                calls.append(item)
            elif item:
                text_parts.append(item)
                await on_text(item)
            if should_preempt is not None and should_preempt():
                preempted = True
                break
        if preempted:
            state.messages.append({"role": "assistant", "content": "".join(text_parts) or None})
            state.pending_calls = []
            state.completed = False
            if save_state is not None:
                await save_state(state, [])
            if inject_controls is not None:
                await inject_controls(state, "preempt")
            continue
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
        if calls:
            import json

            message["tool_calls"] = [
                {"id": call.call_id, "type": "function", **call.history_metadata(),
                 "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                for call in calls
            ]
        state.messages.append(message)
        state.pending_calls = calls
        state.completed = not calls
        if save_state is not None:
            await save_state(state, calls)
        if not calls:
            if inject_controls is not None and await inject_controls(state, "turn"):
                state.completed = False
                if save_state is not None:
                    await save_state(state, [])
                continue
            return state.messages
