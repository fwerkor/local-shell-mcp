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


@dataclass
class ToolBatchOutput:
    messages: list[dict]
    next_context: AgentContext | None = None
    replace_messages: list[dict] | None = None


async def run_agent_loop(
    state: AgentLoopState,
    *,
    stream_tools: Callable[..., AsyncIterator[str | ModelToolCall]],
    stream_text: Callable[..., AsyncIterator[str]],
    dispatch: Callable[[list[ModelToolCall], AgentLoopState], Awaitable[ToolBatchOutput]],
    on_text: Callable[[str], Awaitable[None]],
    save_state: Callable[[AgentLoopState, list[ModelToolCall]], Awaitable[None]] | None = None,
    before_model: Callable[[AgentLoopState], Awaitable[None]] | None = None,
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
            state.completed = output.next_context is None and context.tool_end
            if save_state is not None:
                await save_state(state, [])
            if state.completed:
                return state.messages
            continue
        if state.step >= state.context.recursion_limit:
            raise ValueError("Recursion limit reached without hitting a stop condition")
        if before_model is not None:
            await before_model(state)
        context = state.context
        state.step += 1
        state.model_turn += 1
        params = context.parameters
        max_tokens = max(1, min(int(params.get("max_tokens") or params.get("max_output_tokens") or 2048), 16384))
        temperature = params.get("temperature")
        if temperature is not None:
            temperature = max(0.0, min(float(temperature), 2.0))
        calls: list[ModelToolCall] = []
        text_parts: list[str] = []
        source = stream_tools(context.profile, state.messages, tools=context.tools,
                              max_tokens=max_tokens, temperature=temperature) if context.tools else \
            stream_text(context.profile, state.messages, max_tokens=max_tokens, temperature=temperature)
        async for item in source:
            if isinstance(item, ModelToolCall):
                calls.append(item)
            elif item:
                text_parts.append(item)
                await on_text(item)
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
            return state.messages
