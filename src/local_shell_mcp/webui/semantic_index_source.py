"""Derive semantic tool hints from owner-owned persisted LibreChat content parts.

Source: @librechat/agents 4.0.1 messages/format.ts:
collectCompactionSemanticEntriesFromPart / formatAgentMessages.
Trust is established by owner-bound SQLite ancestry and exact provider-message
matching. Tool calls, activity phases and reasoning labels remain host-owned;
never infer provenance from user/model supplied text or metadata.
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


def _matching_visible_assistant(parts: list, messages: list[dict]) -> tuple[int, list[int]] | None:
    """Match the exact `GenerationStore.history` projection to the saved source.

    An arbitrary equal-looking model message is insufficient when multiple
    candidates exist. Ambiguous or structured/unsupported parts are skipped.
    """
    text_parts = [(index, part['text']) for index, part in enumerate(parts)
                  if isinstance(part, dict) and part.get('type') == 'text'
                  and isinstance(part.get('text'), str)]
    reasoning_parts = [(index, part.get('text') or part.get('thinking'))
                       for index, part in enumerate(parts) if isinstance(part, dict)
                       and part.get('type') in ('think', 'thinking', 'reasoning')]
    if not text_parts and not reasoning_parts:
        return None
    text = ''.join(value for _, value in text_parts)
    reasoning = '\n'.join(str(value) for _, value in reasoning_parts if value)
    candidates = [index for index, item in enumerate(messages)
                  if isinstance(item, dict) and item.get('role') == 'assistant'
                  and not item.get('tool_calls') and item.get('content') == text
                  and (item.get('reasoning_content') or '') == reasoning]
    if len(candidates) != 1:
        return None
    part_indices = [index for index, _ in text_parts]
    part_indices.extend(index for index, value in reasoning_parts if value)
    return candidates[0], part_indices


def _derived_semantic_snapshot(entries: list[dict]) -> SemanticSnapshot | None:
    """Maintain the source collector's head/tail/type coverage budget.

    Compaction must not discard *every* host hint when a long tool-running
    session crosses the source 256-input-entry threshold.
    """
    if not entries:
        return None
    count = len(entries)
    if count <= 256:
        return snapshot_compaction_semantic_index(entries)
    retained = set(range(min(count, 64)))
    retained.update(range(max(0, count - 128), count))
    for kind in ('tool_intent', 'tool_outcome', 'activity_phase', 'reasoning_label'):
        indices = [i for i, entry in enumerate(entries) if entry['type'] == kind]
        retained.update(indices[:8])
        retained.update(indices[-8:])
    # Worst-case disjoint coverage is 64+128+4*16=256.
    selected = [entries[index] for index in sorted(retained)]
    return snapshot_compaction_semantic_index(selected, provided_entry_count=count)


def _labels_from_source(source: str, parts: list, visible: tuple[int, list[int]] | None,
                        refs: dict[int, list[dict]]) -> list[dict]:
    if visible is None:
        return []
    message_index, retained_indices = visible
    anchors = set(retained_indices)
    refs.setdefault(message_index, []).extend(
        {'attribution': 'model', 'sourceMessageId': source,
         'sourceContentPartIndices': [index]} for index in retained_indices if index <= 4095)
    labels = []
    for index, part in enumerate(parts[:4096]):
        if not isinstance(part, dict):
            continue
        if part.get('type') == 'think' and index in anchors:
            reasoning_step = part.get('reasoning_label_step_id')
            revision = part.get('reasoning_label_revision')
            if not isinstance(reasoning_step, str) or not 0 < len(reasoning_step) <= 512 or (
                type(revision) is not int or revision < 0 or revision > 9007199254740991
            ):
                continue
            status = part.get('reasoning_label_status')
            label = part.get('reasoning_label')
            malformed = status not in ('complete', 'streaming') or not isinstance(label, str)
            labels.append({'type': 'reasoning_label', 'sourceMessageId': source,
                           'sourceContentIndex': index, 'revision': revision,
                           'status': 'pending' if status == 'streaming' or malformed else 'committed',
                           'text': label if isinstance(label, str) else '',
                           'reasoningStepId': reasoning_step,
                           **({'redacted': True} if malformed else {})})
        elif part.get('type') == 'activity_label' and part.get('activity_label_type') == 'phase':
            anchor = part.get('activity_start_index')
            revision = part.get('activity_label_revision', 0)
            if (type(anchor) is not int or anchor not in anchors or anchor > 4095 or
                    type(revision) is not int or revision < 0 or revision > 9007199254740991):
                continue
            pending = part.get('pending', False)
            label = part.get('activity_label')
            malformed = type(pending) is not bool or not isinstance(label, str)
            labels.append({'type': 'activity_phase', 'sourceMessageId': source,
                           'sourceContentIndex': anchor, 'revision': revision,
                           'status': 'pending' if pending is True or type(pending) is not bool else 'committed',
                           'text': label if isinstance(label, str) else '',
                           **({'redacted': True} if malformed else {})})
    return labels


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
    # Activity/reasoning labels may exist without any tool execution; continue
    # to validate assistant provenance even when the tool index is empty.
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
        visible = _matching_visible_assistant(row['parts'], copied)
        entries.extend(_labels_from_source(source, row['parts'], visible, refs))
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
    return _derived_semantic_snapshot(entries), copied
