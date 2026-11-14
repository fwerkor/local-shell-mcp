"""Prompt budget and semantic summary trigger/recency primitives.

Source: agents/src/summarization/index.ts, src/messages/recency.ts,
src/messages/prune.ts, src/summarization/shared.ts (4.0.1).
Only the host's summary model call is async; this module is pure and offline.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .context_calibration import clamp_calibration_ratio
from .tokenizer import count_tokens

DEFAULT_RESERVE_RATIO = 0.05
DEFAULT_RETAIN_RECENT_TURNS = 2


@dataclass(frozen=True)
class ContextBudget:
    max_context_tokens: int
    instruction_tokens: int
    tool_schema_tokens: int
    message_tokens: int
    reserve_tokens: int
    available_for_messages: int
    remaining_context_tokens: int


def message_token_count(message: dict) -> int:
    """Model-facing content includes tool arguments, outputs and reasoning."""
    content = message.get('content')
    if isinstance(content, str):
        text = content
    elif content is None:
        text = ''
    else:
        text = json.dumps(content, ensure_ascii=False, separators=(',', ':'))
    other = {key: message[key] for key in ('tool_calls', 'function_call', 'tool_call_id',
                                          'reasoning_content', 'thinking', 'name') if key in message}
    if other:
        text += json.dumps(other, ensure_ascii=False, separators=(',', ':'))
    # Messages pay role/formatting overhead; conservatively include a 4-token
    # envelope (provider-specific calibration remains the transport's job).
    return count_tokens(text, exact=False) + 4


def calculate_budget(messages: list[dict], tools: list[dict], max_context_tokens: int,
                     *, reserve_ratio: float = DEFAULT_RESERVE_RATIO,
                     calibration_ratio: float = 1.0) -> ContextBudget:
    if max_context_tokens <= 0:
        raise ValueError('max_context_tokens must be positive')
    instructions = sum(message_token_count(item) for item in messages if item.get('role') == 'system')
    tools_text = json.dumps(tools, ensure_ascii=False, separators=(',', ':')) if tools else ''
    tool_tokens = count_tokens(tools_text, exact=False) if tools else 0
    messages_raw = sum(message_token_count(item) for item in messages if item.get('role') != 'system')
    # prune.ts keeps individual raw BPE counts intact, applying cumulative
    # provider calibration only to the pre-invoke budget decision.
    messages_count = math.floor(messages_raw * clamp_calibration_ratio(calibration_ratio) + 0.5)
    reserve = round(max_context_tokens * reserve_ratio) if 0 < reserve_ratio < 1 else 0
    available = max(0, max_context_tokens - reserve - instructions - tool_tokens)
    return ContextBudget(max_context_tokens, instructions, tool_tokens, messages_count,
                         reserve, available, available - messages_count)


def context_usage_snapshot(messages: list[dict], tools: list[dict],
                           max_context_tokens: int, *, reserve_ratio: float = DEFAULT_RESERVE_RATIO,
                           run_id: str | None = None, agent_id: str | None = None,
                           calibration_ratio: float = 1.0) -> dict:
    """Project the offline BPE budget onto the pinned SDK context-usage shape.

    This is a pre-invoke estimate calibrated only by provider-confirmed input
    usage, when available. Prompt cache and billed usage remain provider-native.
    """
    ratio = clamp_calibration_ratio(calibration_ratio)
    budget = calculate_budget(messages, tools, max_context_tokens, reserve_ratio=reserve_ratio,
                              calibration_ratio=ratio)
    summaries = [message for message in messages if message.get('role') == 'system'
                 and isinstance(message.get('content'), str)
                 and message['content'].startswith('<summary>\n')]
    summary_tokens = sum(map(message_token_count, summaries))
    system_tokens = budget.instruction_tokens - summary_tokens
    instructions = system_tokens + budget.tool_schema_tokens
    tool_messages = [message for message in messages if message.get('role') == 'tool'
                     or message.get('tool_calls')]
    tool_message_tokens = min(budget.message_tokens,
                              math.floor(sum(map(message_token_count, tool_messages)) * ratio + 0.5))
    return {
        **({'runId': run_id} if run_id else {}),
        **({'agentId': agent_id} if agent_id else {}),
        'breakdown': {
            'maxContextTokens': budget.max_context_tokens,
            'instructionTokens': instructions,
            'systemMessageTokens': system_tokens,
            'dynamicInstructionTokens': 0,
            'toolSchemaTokens': budget.tool_schema_tokens,
            'summaryTokens': summary_tokens,
            'toolCount': len(tools),
            'messageCount': len([message for message in messages if message.get('role') != 'system']),
            'messageTokens': budget.message_tokens,
            'availableForMessages': budget.available_for_messages,
            'toolMessageTokens': tool_message_tokens,
        },
        'calibrationRatio': ratio,
        'contextBudget': max(0, budget.max_context_tokens - budget.reserve_tokens),
        'effectiveInstructionTokens': instructions,
        'prePruneContextTokens': budget.message_tokens,
        'remainingContextTokens': max(0, budget.remaining_context_tokens),
    }


def should_trigger_summarization(*, messages_to_refine_count: int,
                                 trigger: dict | None = None,
                                 max_context_tokens: int | None = None,
                                 pre_prune_context_tokens: int | None = None,
                                 remaining_context_tokens: int | None = None) -> bool:
    """Faithful port of agents summarization/index.ts trigger selection."""
    if messages_to_refine_count <= 0:
        return False
    if not isinstance(trigger, dict) or not isinstance(trigger.get('type'), str):
        return True
    value = trigger.get('value')
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return False
    kind = trigger['type']
    remaining = remaining_context_tokens
    if (max_context_tokens is not None and math.isfinite(max_context_tokens) and max_context_tokens > 0
        and pre_prune_context_tokens is not None and math.isfinite(pre_prune_context_tokens)):
        remaining = max_context_tokens - pre_prune_context_tokens
    if kind == 'token_ratio':
        return bool(max_context_tokens and max_context_tokens > 0 and remaining is not None
                    and math.isfinite(remaining) and (1 - remaining / max_context_tokens) >= value)
    if kind == 'remaining_tokens':
        return remaining is not None and math.isfinite(remaining) and remaining <= value
    if kind == 'messages_to_refine':
        return messages_to_refine_count >= value
    return False


def _open_tool_calls(messages: list[dict]) -> set[str]:
    pending: set[str] = set()
    for message in messages:
        if message.get('role') == 'assistant':
            for call in message.get('tool_calls') or []:
                if isinstance(call, dict) and isinstance(call.get('id'), str):
                    pending.add(call['id'])
        elif message.get('role') == 'tool':
            pending.discard(message.get('tool_call_id'))
    return pending


def split_recent_turns(messages: list[dict], *, turns: int = DEFAULT_RETAIN_RECENT_TURNS,
                       tokens: int | None = None) -> tuple[list[dict], list[dict]]:
    """Retain complete user-led turns and never strand a tool-call/result pair.

    Provider-native tool-results carried inside user messages are not decoded by
    this adapter; the richer message-protocol port owns that normalization.
    """
    if not messages or turns <= 0:
        return list(messages), []
    starts = [index for index, message in enumerate(messages) if message.get('role') == 'user'
              and not message.get('_tool_result')]
    if not starts:
        return list(messages), []
    boundary = starts[-1]
    included = 1
    for index in range(len(starts) - 2, -1, -1):
        if included >= turns:
            break
        candidate = starts[index]
        if tokens is not None and sum(map(message_token_count, messages[candidate:])) > tokens:
            break
        boundary = candidate
        included += 1
    # Move toward the oldest call whenever the proposed boundary starts inside
    # an unanswered tool batch. Never summarize a half-open tool invocation.
    while boundary > 0 and _open_tool_calls(messages[:boundary]):
        previous_user = next((index for index in range(boundary - 1, -1, -1)
                              if messages[index].get('role') == 'user'), 0)
        boundary = previous_user
    return list(messages[:boundary]), list(messages[boundary:])


def summarize_options(settings: dict | None, params: dict) -> tuple[int | None, dict]:
    config = settings or {}
    raw = params.get('max_context_tokens', params.get('maxContextTokens',
          config.get('maxContextTokens')))
    max_context = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw) and raw > 0 else None
    summarization = config.get('summarization') or {}
    return max_context, summarization if isinstance(summarization, dict) else {}
