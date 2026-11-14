"""Derive semantic tool hints from owner-owned persisted LibreChat content parts.

Source: @librechat/agents 4.0.1 messages/format.ts:
collectCompactionSemanticEntriesFromPart / formatAgentMessages.
Only recorded tool-call outcomes with exact provider-facing text are admitted.
Other source part kinds remain unsupported until their trusted projection is
available. Never infer provenance from a model response or user text.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from .semantic_index import SemanticSnapshot, snapshot_compaction_semantic_index


def _ancestry(database: Any, owner: str, conversation_id: str, anchor_id: str) -> list[dict]:
    rows = []
    seen = set()
    with database.connect() as db:
        if not db.execute('SELECT 1 FROM conversations WHERE id=? AND owner=?',
                          (conversation_id, owner)).fetchone():
            return []
        cursor = anchor_id
        while cursor and cursor not in seen and len(rows) < 1024:
            seen.add(cursor)
            row = db.execute('SELECT id,parent_id,role,content FROM messages '
                             'WHERE id=? AND conversation_id=?', (cursor, conversation_id)).fetchone()
            if row is None:
                break
            if row['role'] == 'assistant':
                try:
                    parts = json.loads(row['content'])
                except (ValueError, TypeError):
                    parts = None
                if isinstance(parts, list):
                    rows.append({'id': row['id'], 'parts': parts})
            cursor = row['parent_id']
    return list(reversed(rows))


def derive_persisted_semantic_index(database: Any, owner: str, conversation_id: str,
                                    anchor_id: str, messages_to_refine: list[dict],
                                    *, intent_tool_names: set[str] | None = None,
                                    ) -> tuple[SemanticSnapshot | None, list[dict]]:
    """Produce model-safe index and immutable provenance only for matching calls.

    Stored source content is the authority. An arbitrary user/model-supplied
    `additional_kwargs.provenance` cannot certify a matching outcome. Invalid
    or duplicate call IDs are dropped instead of assigned a fabricated source.
    """
    copied = copy.deepcopy(messages_to_refine)
    assistant_calls: dict[str, list[int]] = {}
    results: dict[str, list[int]] = {}
    for i, message in enumerate(copied):
        if not isinstance(message, dict):
            continue
        if message.get('role') == 'assistant':
            for call in message.get('tool_calls') or []:
                if isinstance(call, dict) and isinstance(call.get('id'), str):
                    assistant_calls.setdefault(call['id'], []).append(i)
        elif message.get('role') == 'tool' and isinstance(message.get('tool_call_id'), str):
            results.setdefault(message['tool_call_id'], []).append(i)
    if not assistant_calls or not results:
        return None, copied
    rows = _ancestry(database, owner, conversation_id, anchor_id)
    if not rows:
        return None, copied
    entries = []
    refs: dict[int, list[dict]] = {}
    assigned_ids = set()
    intents = intent_tool_names or set()
    for row in rows:
        source = row['id']
        if not isinstance(source, str) or not 0 < len(source) <= 512:
            continue
        for index, part in enumerate(row['parts']):
            if index > 4095:
                break
            if not isinstance(part, dict) or part.get('type') != 'tool_call':
                continue
            call = part.get('tool_call')
            if not isinstance(call, dict):
                continue
            call_id, name = call.get('id'), call.get('name')
            output = call.get('outcome', call.get('output'))
            if not isinstance(call_id, str) or not 0 < len(call_id) <= 512:
                continue
            # Require a one-to-one original invocation/result pair with the
            # same text the provider will receive before accepting lineage.
            if (call_id in assigned_ids or len(assistant_calls.get(call_id, [])) != 1
                    or len(results.get(call_id, [])) != 1 or not isinstance(output, str) or not output):
                continue
            result_index = results[call_id][0]
            if copied[result_index].get('content') != output:
                continue
            assigned_ids.add(call_id)
            entries.append({'type': 'tool_outcome', 'sourceMessageId': source,
                            'sourceContentIndex': index, 'revision': 0, 'status': 'committed',
                            'toolCallId': call_id, 'text': output})
            if isinstance(name, str) and name in intents:
                args = call.get('args')
                intent = args.get('intent') if isinstance(args, dict) else None
                if isinstance(intent, str) and intent:
                    entries.append({'type': 'tool_intent', 'sourceMessageId': source,
                                    'sourceContentIndex': index, 'revision': 0,
                                    'status': 'committed', 'toolCallId': call_id, 'text': intent})
            # Source part attribution can be appended to an assistant tool
            # invocation; its tool result uses the same saved content index.
            for i in (assistant_calls[call_id][0], result_index):
                refs.setdefault(i, []).append({'attribution': 'model' if i == assistant_calls[call_id][0] else 'tool',
                                                'sourceMessageId': source,
                                                'sourceContentPartIndices': [index]})
    if not entries:
        return None, copied
    for i, parts in refs.items():
        kwargs = copied[i].get('additional_kwargs')
        if isinstance(kwargs, dict) and 'provenance' in kwargs:
            # Never clobber a provenance envelope already supplied by an
            # upstream formatter; it must pass its independent validation.
            continue
        copied[i]['additional_kwargs'] = {'provenance': {'version': 1, 'parts': parts}}
    return snapshot_compaction_semantic_index(entries, provided_entry_count=len(entries)), copied
