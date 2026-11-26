"""Model/tools graph-node loop derived from agents Graph.ts createAgentWorkflow.

The graph is START -> agent -> tools -> agent, or agent -> END. Transport,
ToolNode dispatch, human interruptions and checkpoint storage are injected by
LSM rather than maintaining separate provider or machine execution systems.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .providers import ModelThought, ModelToolCall, ModelUsage, ProviderConfig
from .semantic_index import SemanticSnapshot

log = logging.getLogger(__name__)


def _retryable_provider_disconnect(error: Exception) -> bool:
    """Retry transient HTTP transport failures only before any model event.

    A model response may already contain executed tool calls, visible text or
    signed reasoning. Retrying after the first event would duplicate content or
    invalidate provider state; HTTP status errors are never transient here.
    """
    import httpx

    return isinstance(error, (
        httpx.RemoteProtocolError, httpx.ConnectError, httpx.ConnectTimeout,
        httpx.ReadError, httpx.ReadTimeout,
    ))


class RuntimeSafetyError(PermissionError):
    """A revoked grant or execution boundary stops the complete run."""


class AgentSuspended(Exception):
    """A durable human interrupt has been saved; leave the generation parked."""


_MODEL_RETRY_DELAYS = (0.4, 0.4 * 3)

# A model that keeps re-issuing the same call and receiving the same result is
# making no progress. Stop the run instead of streaming one durable event per
# iteration; an unbounded loop otherwise writes without limit to SQLite.
_MAX_REPEATED_TOOL_BATCHES = 2


def _tool_batch_signature(calls: list[ModelToolCall], results: list[dict]) -> str:
    """Fingerprint one tool round-trip: requested calls plus delivered results."""
    payload = json.dumps(
        {
            "calls": [[call.name, call.arguments] for call in calls],
            "results": results,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _retryable_model_error(error: Exception) -> bool:
    """Only retry transient transport failures and explicitly temporary HTTP statuses."""
    import httpx

    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {408, 429, 500, 502, 503, 504}
    return isinstance(error, (
        httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError,
        httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.PoolTimeout,
    ))


@dataclass
class AgentContext:
    profile: ProviderConfig
    tools: list[dict]
    parameters: dict = field(default_factory=dict)
    recursion_limit: int | None = None
    tool_end: bool = False
    agent: dict | None = None
    compaction_semantic_index: SemanticSnapshot | None = None


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
    provider_projection: list[dict] | None = None
    repeated_tool_batches: int = 0
    last_tool_batch: str | None = None


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
    on_thought: Callable[[str], Awaitable[None]] | None = None,
    save_state: Callable[[AgentLoopState, list[ModelToolCall]], Awaitable[None]] | None = None,
    before_model: Callable[[AgentLoopState], Awaitable[None]] | None = None,
    on_model_usage: Callable[[ModelUsage, AgentLoopState], Awaitable[None]] | None = None,
    project_messages: Callable[[AgentLoopState], list[dict]] | None = None,
    preflight_calls: Callable[[list[ModelToolCall], AgentLoopState], list[ModelToolCall]] | None = None,
    inject_controls: Callable[[AgentLoopState, str], Awaitable[bool]] | None = None,
    should_preempt: Callable[[], bool] | None = None,
    on_boundary: Callable[[AgentLoopState, str], Awaitable[bool]] | None = None,
    on_stream_chunk: Callable[[], Awaitable[bool]] | None = None,
) -> list[dict]:
    if state.completed:
        return state.messages
    while True:
        if state.pending_calls:
            context = state.context
            if not state.tool_step_started:
                if context.recursion_limit is not None and state.step >= context.recursion_limit:
                    raise ValueError("Recursion limit reached without hitting a stop condition")
                state.step += 1
                state.tool_step_started = True
                if save_state is not None:
                    await save_state(state, state.pending_calls)
            output = await dispatch(state.pending_calls, state)
            signature = _tool_batch_signature(state.pending_calls, output.messages)
            if signature == state.last_tool_batch:
                state.repeated_tool_batches += 1
            else:
                state.last_tool_batch = signature
                state.repeated_tool_batches = 0
            if state.repeated_tool_batches >= _MAX_REPEATED_TOOL_BATCHES:
                raise RuntimeSafetyError(
                    "The model repeated an identical tool call and received an "
                    "identical result without making progress; the run was "
                    "stopped to prevent an unbounded loop.",
                )
            if output.replace_messages is not None:
                state.messages = output.replace_messages
            state.messages.extend(output.messages)
            if output.next_context is not None:
                state.context = output.next_context
            injected = await on_boundary(state, "post_tools") if on_boundary else False
            state.pending_calls = []
            state.tool_step_started = False
            state.graph_commands = output.graph_commands
            # Detached task controls can arrive while a tool is running. Apply
            # them at the durable post-tool boundary before deciding whether
            # end_after_tools terminates the child.
            control_applied = await inject_controls(state, "tool") if inject_controls else False
            state.completed = bool(output.graph_commands) or (
                output.next_context is None and context.tool_end and not injected and not control_applied
            )
            if save_state is not None:
                await save_state(state, [])
            if state.completed:
                return state.messages
            continue
        if inject_controls is not None:
            await inject_controls(state, "tool")
        if state.context.recursion_limit is not None and state.step >= state.context.recursion_limit:
            raise ValueError("Recursion limit reached without hitting a stop condition")
        if before_model is not None:
            await before_model(state)
        context = state.context
        state.step += 1
        state.model_turn += 1
        params = context.parameters
        # Missing max tokens means no application-imposed output limit.
        max_tokens = next((params[key] for key in ("max_tokens", "maxTokens", "max_output_tokens", "maxOutputTokens")
                           if params.get(key) is not None), None)
        max_tokens = int(max_tokens) if isinstance(max_tokens, (int, float)) and not isinstance(max_tokens, bool) and max_tokens > 0 else None
        temperature = params.get("temperature")
        if temperature is not None:
            temperature = max(0.0, min(float(temperature), 2.0))
        top_p = next((params[key] for key in ("top_p", "topP") if params.get(key) is not None), None)
        if top_p is not None:
            top_p = max(0.0, min(float(top_p), 1.0))
        sampling = {"temperature": temperature}
        if max_tokens is not None:
            sampling["max_tokens"] = max_tokens
        if top_p is not None:
            sampling["top_p"] = top_p
        calls: list[ModelToolCall] = []
        text_parts: list[str] = []
        reasoning: list[dict] = []
        projected = project_messages(state) if project_messages else state.messages
        state.provider_projection = projected
        preempted = False
        # Retry only an *empty* model attempt. Text and complete tool proposals
        # are observable, so replaying them could duplicate output or actions.
        # A new model attempt keeps the graph turn and completed tool results.
        for attempt in range(len(_MODEL_RETRY_DELAYS) + 1):
            received_event = False
            source = stream_tools(context.profile, projected, tools=context.tools,
                                  **sampling) if context.tools else \
                stream_text(context.profile, projected, **sampling)
            try:
                async for item in source:
                    received_event = True
                    if isinstance(item, ModelToolCall):
                        calls.append(item)
                    elif isinstance(item, ModelUsage):
                        if on_model_usage is not None:
                            await on_model_usage(item, state)
                    elif isinstance(item, ModelThought):
                        if item.kind == 'thinking':
                            if reasoning and reasoning[-1].get('type') == 'thinking' and not reasoning[-1].get('signature'):
                                reasoning[-1]['thinking'] += item.text
                            else:
                                reasoning.append({'type': 'thinking', 'thinking': item.text})
                            if item.text and on_thought is not None:
                                await on_thought(item.text)
                        elif item.kind == 'signature':
                            if reasoning and reasoning[-1].get('type') == 'thinking':
                                reasoning[-1]['signature'] = item.signature
                        elif item.kind == 'redacted_thinking':
                            reasoning.append({'type': 'redacted_thinking', 'data': item.data})
                        elif item.kind == 'responses_item' and item.provider_data:
                            reasoning.append({'type': 'responses_item', **item.provider_data})
                    elif item:
                        text_parts.append(item)
                        await on_text(item)
                    # Model streams may contain only tool calls. Both the durable
                    # user steer and detached-child interrupt can preempt these.
                    if ((should_preempt is not None and should_preempt()) or
                        (on_stream_chunk is not None and await on_stream_chunk())):
                        preempted = True
                        break
            except Exception as error:
                if (attempt == len(_MODEL_RETRY_DELAYS) or received_event
                        or not _retryable_model_error(error)):
                    raise
                # Honor revocation and user interrupts even during backoff.
                if ((should_preempt is not None and should_preempt()) or
                    (on_stream_chunk is not None and await on_stream_chunk())):
                    preempted = True
                    break
                log.warning("Model transport %s before first event; retry %d/2 (model=%s)",
                            type(error).__name__, attempt + 1, context.profile.model)
                await asyncio.sleep(_MODEL_RETRY_DELAYS[attempt])
                continue
            finally:
                close = getattr(source, "aclose", None)
                if close is not None:
                    await close()
            break
        # A steer can arrive between final SSE chunk and tool dispatch.
        if not preempted and ((should_preempt is not None and should_preempt()) or
                              (on_stream_chunk is not None and await on_stream_chunk())):
            preempted = True
        if preempted:
            interrupted = {"role": "assistant", "content": "".join(text_parts) or None}
            if reasoning:
                interrupted["reasoning"] = reasoning
            state.messages.append(interrupted)
            state.pending_calls = []
            state.completed = False
            if on_boundary is not None:
                await on_boundary(state, "stream")
            if save_state is not None:
                await save_state(state, [])
            if inject_controls is not None:
                await inject_controls(state, "preempt")
            continue

        if calls and preflight_calls is not None:
            # Reject protected tool arguments before the model turn is saved.
            calls = preflight_calls(calls, state)
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
        if not calls and on_boundary is not None and await on_boundary(state, "terminal"):
            state.completed = False
        if save_state is not None:
            await save_state(state, calls)
        if not calls:
            if inject_controls is not None and await inject_controls(state, "turn"):
                state.completed = False
                if save_state is not None:
                    await save_state(state, [])
            if state.completed:
                return state.messages
