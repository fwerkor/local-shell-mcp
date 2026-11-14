"""Bound the provider-only view of tool traffic using source fading v2 caps.

The immutable canonical history and SQLite checkpoints remain unmodified.
The model receives valid JSON-shaped tool input when a large invocation is
capped, and text tool results are truncated without disclosing source extras.
"""
from __future__ import annotations

import copy
import json

from .fading import is_fading_tier, resolve_fading_caps


def _clip(value: str, chars: int) -> str:
    if len(value) <= chars:
        return value
    if chars < 12:
        return value[:chars]
    suffix = max(1, chars // 5)
    middle = f'… [truncated: {len(value)} chars] …'
    head = max(0, chars - suffix - len(middle))
    if head == 0:
        return value[:max(0, chars - 1)] + '…'
    return value[:head] + middle + value[-suffix:]


def _answered_by_later_assistant(messages: list[dict], index: int) -> bool:
    for later in messages[index + 1:]:
        if not isinstance(later, dict):
            continue
        if later.get('role') == 'assistant' and isinstance(later.get('content'), str) and later['content']:
            return True
    return False


def project_faded_provider_messages(messages: list[dict], tier: dict | None,
                                    max_tool_result_chars: int | None = None) -> list[dict]:
    """Apply tier caps to provider-facing tool result and call input copies."""
    if not is_fading_tier(tier):
        return messages
    caps = resolve_fading_caps(tier, max_tool_result_chars)
    rendered = []
    for i, original in enumerate(messages):
        if not isinstance(original, dict):
            rendered.append(copy.deepcopy(original))
            continue
        item = copy.deepcopy(original)
        if item.get('role') == 'tool' and isinstance(item.get('content'), str):
            consumed = tier['masked'] and _answered_by_later_assistant(messages, i)
            max_chars = caps['consumedChars'] if consumed else caps['resultChars']
            item['content'] = _clip(item['content'], max_chars)
        elif item.get('role') == 'assistant':
            for call in item.get('tool_calls') or []:
                if not isinstance(call, dict):
                    continue
                function = call.get('function')
                if not isinstance(function, dict):
                    continue
                arguments = function.get('arguments')
                if isinstance(arguments, str) and len(arguments) > caps['inputChars']:
                    limit = caps['inputChars']
                    preview = _clip(arguments, max(0, limit - 90))
                    encoded = json.dumps({'_truncated': preview, '_originalChars': len(arguments)},
                                         ensure_ascii=False, separators=(',', ':'))
                    while len(encoded) > limit and preview:
                        preview = preview[:max(0, len(preview) - max(1, len(preview) // 4))]
                        encoded = json.dumps({'_truncated': preview, '_originalChars': len(arguments)},
                                             ensure_ascii=False, separators=(',', ':'))
                    function['arguments'] = encoded if len(encoded) <= limit else '{}'
        rendered.append(item)
    return rendered
