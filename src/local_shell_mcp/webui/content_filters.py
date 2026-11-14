"""Bounded, source-scoped content inspection for the Python LibreChat WebUI.

Ported from LibreChat packages/api/src/protection/runtime.ts, adapters/submissions.ts
and audit.ts. Audit events contain only source/rule metadata, never scanned text.
Regex compilation reuses the existing fail-closed memory policy engine; it is
not advertised as an exact RE2JS runtime or a substitute for file scanners.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .memory_protection import _rules

_SOURCE_CONFIG = {
    'message': 'messages',
    'assembled_context': 'messages',
    'prompt': 'prompts',
    'agent_instruction': 'agentInstructions',
    'conversation_starter': 'conversationStarters',
    'skill': 'skills',
    'memory': 'memories',
    'file': 'files',
    'tool_argument': 'toolArguments',
    'model_parameter': 'modelParameters',
    'action_metadata': 'actionMetadata',
    'feedback': 'feedback',
    'conversation_title': 'conversationTitles',
}
_MAX_ITEMS = 4096
_MAX_FIELD_CHARS = 262144
_MAX_TOTAL_CHARS = 8 * 1024 * 1024
_MAX_DEPTH = 16
_MAX_NODES = 8192
_MAX_CUSTOM_PATTERNS_TOTAL = 256
_MAX_CUSTOM_REGEX_CHARS = 8192


@dataclass(frozen=True)
class ContentFragment:
    source: str
    field: str
    text: str
    provenance: str = 'user'


class ContentFilterBlocked(ValueError):
    def __init__(self, source: str, field: str, *, label: str = 'protected content') -> None:
        self.source, self.field, self.label = source, field, label
        super().__init__('Submitted content was blocked by configured content policy')

    def response(self) -> dict:
        return {'error': 'content_filter_block',
                'message': 'Submitted content was blocked by content policy.',
                'source': self.source, 'field': self.field}


def _policies(filters: dict | None, source: str) -> dict | None:
    if not isinstance(filters, dict) or source not in _SOURCE_CONFIG:
        return None
    category = filters.get(_SOURCE_CONFIG[source])
    policy = category.get('pii') if isinstance(category, dict) else None
    if not isinstance(policy, dict):
        return None
    if policy.get('starterPatterns') == [] and not policy.get('customPatterns'):
        return None
    return policy


def _policy_fields(policy: dict) -> set[str] | None:
    specified = policy.get('fields')
    if specified is None:
        return None
    if not isinstance(specified, list) or not 1 <= len(specified) <= 256 or any(
        not isinstance(item, str) or not 0 < len(item) <= 256 for item in specified
    ):
        raise ValueError('Invalid content protection fields')
    return set(specified)


def _global_pattern_budget(filters: dict | None) -> None:
    if not isinstance(filters, dict):
        return
    custom_count = custom_chars = 0
    seen_categories = set(_SOURCE_CONFIG.values())
    for category in seen_categories:
        settings = filters.get(category)
        policy = settings.get('pii') if isinstance(settings, dict) else None
        if not isinstance(policy, dict):
            continue
        custom = policy.get('customPatterns') or []
        if not isinstance(custom, list):
            raise ValueError('Invalid configured custom filters')
        custom_count += len(custom)
        for item in custom:
            if not isinstance(item, dict) or not isinstance(item.get('regex'), str):
                raise ValueError('Invalid configured custom filter')
            custom_chars += len(item['regex'])
        if custom_count > _MAX_CUSTOM_PATTERNS_TOTAL or custom_chars > _MAX_CUSTOM_REGEX_CHARS:
            raise ValueError('Global custom content filter budget exceeded')


def _checked_patterns(policy: dict) -> list[tuple[Any, str, str]]:
    patterns = _rules(policy)
    starters = policy.get('starterPatterns')
    if starters is None:
        starters = ['sk_prefix', 'bearer_header', 'api_key_header']
    ids = [str(name) for name in starters] + [item['id'] for item in policy.get('customPatterns') or []]
    if len(ids) != len(patterns):
        raise ValueError('Invalid content protection patterns')
    return [(compiled, label, rid) for (compiled, label), rid in zip(patterns, ids, strict=True)]


def inspect_content(fragments: Iterable[ContentFragment], filters: dict | None,
                    *, audit_sink=None) -> ContentFilterBlocked | None:
    """Inspect all applicable source policies, recording bounded audit metadata.

    As in upstream, audit rules do not override an independent blocking rule.
    No snippet, matching span, source text or tool argument enters an audit row.
    """
    snapshots = []
    for index, fragment in enumerate(fragments):
        if index > _MAX_ITEMS:
            # Never ignore a later protected fragment after bounded traversal.
            protected = next((record for record in snapshots
                              if _policies(filters, record.source)), None)
            if protected is None and isinstance(fragment, ContentFragment):
                protected = fragment if _policies(filters, fragment.source) else None
            if protected is not None:
                raise ContentFilterBlocked(protected.source, protected.field)
            break
        snapshots.append(fragment)
    if not snapshots:
        return None
    try:
        _global_pattern_budget(filters)
    except ValueError:
        protected = next((record for record in snapshots
                          if _policies(filters, record.source)), None)
        if protected is not None:
            raise ContentFilterBlocked(protected.source, protected.field) from None
    active: dict[str, tuple[dict, set[str] | None, list[tuple[Any, str, str]]]] = {}
    for item in snapshots:
        if not isinstance(item, ContentFragment):
            raise TypeError('Expected a typed content fragment')
        if item.source in active:
            continue
        policy = _policies(filters, item.source)
        if policy is None:
            continue
        try:
            fields = _policy_fields(policy)
            matches = _checked_patterns(policy)
        except Exception:
            if policy.get('action') == 'audit':
                continue
            raise ContentFilterBlocked(item.source, item.field) from None
        active[item.source] = policy, fields, matches
    if not active:
        return None
    first: ContentFilterBlocked | None = None
    audit_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    try:
        size = 0
        for i, item in enumerate(snapshots):
            if item.source not in active:
                continue
            policy, fields, rules = active[item.source]
            if fields is not None and item.field not in fields:
                continue
            if not isinstance(item.text, str):
                first = first or ContentFilterBlocked(item.source, item.field)
                continue
            size += len(item.text)
            if (i >= _MAX_ITEMS or len(item.text) > _MAX_FIELD_CHARS or size > _MAX_TOTAL_CHARS):
                if policy.get('action') != 'audit':
                    first = first or ContentFilterBlocked(item.source, item.field)
                continue
            for compiled, label, rule_id in rules:
                try:
                    found = compiled.search(item.text, timeout=0.025) is not None
                except TimeoutError:
                    found = True
                if not found:
                    continue
                if policy.get('action') == 'audit':
                    if len(audit_counts) < 1024:
                        audit_counts[(item.source, item.field, item.provenance, rule_id, label)] += 1
                else:
                    first = first or ContentFilterBlocked(item.source, item.field, label=label)
    finally:
        if audit_counts:
            sink = audit_sink
            if sink is None:
                from ..audit import audit

                def sink(**data):
                    return audit('content_filter_audit', **data)
            for (source, field, provenance, rule_id, label), occurrences in audit_counts.items():
                try:
                    sink(action='audit', detectorId='pii-pattern', ruleId=rule_id,
                         label=label, source=source, field=field,
                         provenance=provenance, occurrences=occurrences)
                except Exception as exc:
                    # Audit-only policy cannot fail an otherwise permitted
                    # generation because the logging backend is unavailable.
                    logging.getLogger(__name__).warning('Content audit failed (%s)', type(exc).__name__)
    return first


def _nested_strings(value: object, *, limit: int = _MAX_NODES) -> list[str]:
    """Visit both names and values without serializing an unbounded object."""
    stack = [(value, 0)]
    strings: list[str] = []
    visited = 0
    while stack:
        current, depth = stack.pop()
        visited += 1
        if visited > limit or depth > _MAX_DEPTH:
            raise ValueError('Content traversal budget exceeded')
        if isinstance(current, str):
            strings.append(current)
        elif isinstance(current, dict):
            if len(current) > limit:
                raise ValueError('Content traversal node count exceeded')
            for key, part in reversed(list(current.items())):
                stack.append((part, depth + 1))
                stack.append((str(key), depth + 1))
        elif isinstance(current, (list, tuple)):
            if len(current) > limit:
                raise ValueError('Content traversal node count exceeded')
            stack.extend((part, depth + 1) for part in reversed(current))
    return strings


def tool_fragments(name: str, arguments: object, *, output: object = None) -> list[ContentFragment]:
    fragments = [ContentFragment('tool_argument', 'name', name, 'model')]
    for field, content in (('arguments', arguments), ('output', output)):
        try:
            nested = _nested_strings(content)
        except ValueError:
            # Fail closed for malformed/too deep inputs, without carrying a
            # potentially secret truncated value into an error response.
            nested = ['x' * (_MAX_FIELD_CHARS + 1)]
        fragments.extend(ContentFragment('tool_argument', field, text, 'model' if field == 'arguments' else 'tool')
                         for text in nested)
    return fragments


def model_message_fragments(messages: list[dict]) -> list[ContentFragment]:
    fragments = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get('role')
        if role not in ('user', 'assistant', 'system', 'tool'):
            continue
        content = message.get('content')
        if not isinstance(content, str):
            continue
        provenance = {'user': 'user', 'assistant': 'model', 'system': 'system', 'tool': 'tool'}[role]
        fragments.append(ContentFragment('assembled_context', 'assembled_context', content, provenance))
    return fragments


def validate_message_submission(text: str, filters: dict | None) -> None:
    blocked = inspect_content([ContentFragment('message', 'content_part', text)], filters)
    if blocked is not None:
        raise blocked


def validate_agent_instructions(instructions: str, filters: dict | None) -> None:
    if instructions:
        blocked = inspect_content([ContentFragment('agent_instruction', 'instructions', instructions,
                                                    'administrator')], filters)
        if blocked is not None:
            raise blocked


def validate_tool_arguments(name: str, arguments: dict, filters: dict | None) -> None:
    if _policies(filters, 'tool_argument') is None:
        return
    blocked = inspect_content(tool_fragments(name, arguments), filters)
    if blocked is not None:
        raise blocked


def filtered_tool_output(name: str, output: object, filters: dict | None) -> object:
    if _policies(filters, 'tool_argument') is None:
        return output
    blocked = inspect_content(tool_fragments(name, {}, output=output), filters)
    if blocked is None:
        return output
    return 'Tool output withheld by configured content protection policy.'


def model_parameter_fragments(parameters: dict) -> list[ContentFragment]:
    """Inspect nested user/Agent model controls with bounded key/value walks."""
    fragments = []
    for field, value in parameters.items():
        try:
            strings = _nested_strings(value)
        except ValueError:
            strings = ['x' * (_MAX_FIELD_CHARS + 1)]
        fragments.extend(ContentFragment('model_parameter', str(field), text, 'administrator')
                         for text in strings)
    return fragments


def validate_model_parameters(parameters: dict, filters: dict | None) -> None:
    if _policies(filters, 'model_parameter') is None:
        return
    blocked = inspect_content(model_parameter_fragments(parameters), filters)
    if blocked is not None:
        raise blocked
