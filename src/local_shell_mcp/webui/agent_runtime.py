"""Model/tools graph-node loop derived from agents Graph.ts createAgentWorkflow.

The graph is START -> agent -> tools -> agent, or agent -> END. Transport,
ToolNode dispatch, human interruptions and checkpoint storage are injected by
LSM rather than maintaining separate provider or machine execution systems.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .providers import ModelThought, ModelToolCall, ProviderConfig


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
    on_boundary: Callable[[AgentLoopState, str], Awaitable[bool]] | None = None,
    on_stream_chunk: Callable[[], Awaitable[bool]] | None = None,
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
            injected = await on_boundary(state, "post_tools") if on_boundary else False
            state.pending_calls = []
            state.tool_step_started = False
            state.completed = output.next_context is None and context.tool_end and not injected
            if save_state is not None:
                await save_state(state, [])
            if state.completed:
                return state.messages
            continue
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
        reasoning: list[dict] = []
        source = stream_tools(context.profile, state.messages, tools=context.tools,
                              **sampling) if context.tools else \
            stream_text(context.profile, state.messages, **sampling)
        sealed = False
        try:
            async for item in source:
                if isinstance(item, ModelToolCall):
                    calls.append(item)
                elif isinstance(item, ModelThought):
                    if item.kind == 'thinking':
                        if reasoning and reasoning[-1].get('type') == 'thinking' and not reasoning[-1].get('signature'):
                            reasoning[-1]['thinking'] += item.text
                        else:
                            reasoning.append({'type': 'thinking', 'thinking': item.text})
                    elif item.kind == 'signature':
                        if reasoning and reasoning[-1].get('type') == 'thinking':
                            reasoning[-1]['signature'] = item.signature
                    elif item.kind == 'redacted_thinking':
                        reasoning.append({'type': 'redacted_thinking', 'data': item.data})
                elif item:
                    text_parts.append(item)
                    await on_text(item)
                # An interrupted provider can emit only tool_calls, without
                # ever yielding text. Inspect *every* chunk before dispatching
                # proposals, including the final tool-call chunk.
                if on_stream_chunk is not None and await on_stream_chunk():
                    sealed = True
                    break
        finally:
            # Closing the async iterator releases provider SSE/HTTP resources
            # after an intentional provider-safe steer preemption.
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()
        # A steer may arrive after the provider's last chunk and before
        # dispatch. Recheck the durable queue at this execution boundary.
        if not sealed and on_stream_chunk is not None and await on_stream_chunk():
            sealed = True
        # A preempted provider turn is incomplete. None of its buffered
        # tool proposals may dispatch: the injected user steer must be heard
        # by the model before it can authorize another batch.
        if sealed:
            calls.clear()
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
        if reasoning:
            message["reasoning"] = reasoning
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
        injected = (not calls and on_boundary is not None and
                    await on_boundary(state, "stream" if sealed else "terminal"))
        if injected or sealed:
            # A client may cancel a queued preempt while aclose() releases the
            # provider stream. Never finalize the truncated partial answer as
            # successful when the seal happened but no steer was injected.
            # Continue the model from that partial assistant message instead.
            state.completed = False
        if save_state is not None:
            await save_state(state, calls)
        if state.completed:
            return state.messages
