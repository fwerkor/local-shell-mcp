"""Field-scoped memory content protection from LibreChat's memory pipeline.

The controller has no Node runtime. Custom regular expressions use Python's
regex engine with a strict timeout and fail-closed projection on errors.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_MEMORY_FIELDS = ('key', 'value', 'summary')
_MAX_FIELD_LENGTH = 262144


class MemoryContentBlocked(ValueError):
    def __init__(self, field: str, label: str = 'protected value') -> None:
        self.field, self.label = field, label
        super().__init__('Memory content blocked by configured policy')

    def response(self, *, model: bool = False) -> dict:
        return {
            'error': 'content_filter_block',
            'message': ('Submitted content was blocked by content policy.' if model else
                        f'Submitted content contains a {self.label}. Remove it and try again.'),
            'source': 'memory',
            'field': self.field,
        }


def configured_filters(repo: Any, owner: str) -> dict | None:
    configured = repo.setting(owner, 'webui.filters.config')
    if not isinstance(configured, dict):
        endpoints = repo.setting(owner, 'endpoints', {}) or {}
        configured = endpoints.get('filters') if isinstance(endpoints, dict) else None
    return configured if isinstance(configured, dict) else None


def _policy(filters: dict | None) -> dict | None:
    if not isinstance(filters, dict):
        return None
    memory = filters.get('memories')
    policy = memory.get('pii') if isinstance(memory, dict) else None
    if not isinstance(policy, dict):
        return None
    if policy.get('starterPatterns') == [] and not policy.get('customPatterns'):
        return None
    return policy


def _fields(policy: dict) -> tuple[str, ...]:
    values = policy.get('fields')
    if values is None:
        return _MEMORY_FIELDS
    if not isinstance(values, list) or len(values) > 256:
        return _MEMORY_FIELDS
    return tuple(field for field in _MEMORY_FIELDS if field in values)


@lru_cache(maxsize=256)
def _compile(expression: str, flags: int = 0) -> Any:
    import regex  # WebUI optional extra; never block a plain Controller wheel at import time.
    if not isinstance(expression, str) or not 0 < len(expression) <= 512:
        raise ValueError('Invalid memory content pattern')
    # RE2JS does not accept lookarounds, recursive groups, or backreferences.
    if re.search(r'\\[1-9]|\(\?[=!]|\(\?<[=!]|\(\?P[=<]', expression):
        raise ValueError('Unsupported regular expression syntax')
    return regex.compile(expression, flags | regex.VERSION1)


def _rules(policy: dict) -> list[tuple[Any, str]]:
    catalog = {
        'sk_prefix': (r'\b(sk-)[a-zA-Z0-9_-]+', 0, 'sk- prefix token'),
        'bearer_header': (r'\b(Bearer )[^\s"\']+', re.I, 'Bearer token'),
        'api_key_header': (r'\b(api-key:?\s+)[^\s"\']+', re.I, 'api-key header'),
    }
    starters = policy.get('starterPatterns')
    if starters is None:
        starters = list(catalog)
    customs = policy.get('customPatterns') or []
    if not isinstance(starters, list) or len(starters) > 256:
        raise ValueError('Invalid starter patterns')
    if not isinstance(customs, list) or len(customs) > 256:
        raise ValueError('Invalid custom patterns')
    compiled = []
    for item in starters:
        if not isinstance(item, str) or item not in catalog:
            raise ValueError('Invalid starter pattern id')
        pattern, flags, label = catalog[item]
        compiled.append((_compile(pattern, flags), label))
    total_length = 0
    for item in customs:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            raise ValueError('Invalid custom pattern')
        if not isinstance(item.get('label'), str) or not item['label']:
            raise ValueError('Invalid custom pattern label')
        expression = item.get('regex')
        if not isinstance(expression, str):
            raise ValueError('Invalid custom pattern expression')
        total_length += len(expression)
        if total_length > 8192:
            raise ValueError('Custom pattern budget exceeded')
        compiled.append((_compile(expression), item['label']))
    return compiled


def inspect_memory_content(entry: dict, filters: dict | None) -> MemoryContentBlocked | None:
    policy = _policy(filters)
    if policy is None or policy.get('action') == 'audit':
        return None
    fields = _fields(policy)
    if not fields:
        return None
    try:
        rules = _rules(policy)
    except Exception:
        # Invalid configuration or missing optional regex must fail closed,
        # never block Controller startup or expose already-stored values.
        return MemoryContentBlocked(fields[0])
    for field in fields:
        content = entry.get(field)
        if not isinstance(content, str):
            continue
        if len(content) > _MAX_FIELD_LENGTH:
            return MemoryContentBlocked(field)
        for compiled, label in rules:
            try:
                if compiled.search(content, timeout=0.025) is not None:
                    return MemoryContentBlocked(field, label)
            except TimeoutError:
                return MemoryContentBlocked(field)
    return None


def project_stored_memories(records: list[dict], filters: dict | None) -> list[dict]:
    """Project old rows under current policy while retaining management metadata."""
    policy = _policy(filters)
    if policy is None or policy.get('action') == 'audit':
        return records
    selected = _fields(policy)
    projected = []
    for record in records:
        copy = dict(record)
        for field in selected:
            if field not in record:
                continue
            field_policy = {'memories': {'pii': {**policy, 'fields': [field]}}}
            if inspect_memory_content({field: record[field]}, field_policy):
                copy[field] = ''
                copy['contentFilterBlocked'] = True
        projected.append(copy)
    return projected


def assert_memory_content_allowed(key: str, value: str, filters: dict | None) -> None:
    finding = inspect_memory_content({'key': key, 'value': value}, filters)
    if finding is not None:
        raise finding
