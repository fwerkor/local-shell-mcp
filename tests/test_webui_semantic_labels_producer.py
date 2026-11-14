"""Source `formatAgentMessages` trusted activity/reasoning label collection."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.semantic_index import render_compaction_semantic_index
from local_shell_mcp.webui.semantic_index_source import (
    _derived_semantic_snapshot,
    _labels_from_source,
    derive_persisted_semantic_index,
)


@pytest.fixture
def source_messages(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    first, _ = store.begin('owner', {'text': 'Research issue'})
    store.finish('owner', first.run_id, status='complete', text='Verified the issue.')
    next_job, _ = store.begin('owner', {'text': 'Summarize previous run',
                                    'conversationId': first.conversation_id,
                                    'parentMessageId': first.response_message_id})
    return db, store, first, next_job


def _set_parts(db, response_id: str, parts):
    with db.connect() as connection:
        connection.execute('UPDATE messages SET content=? WHERE id=?',
                           (json.dumps(parts), response_id))


def test_source_activity_reasoning_match_actual_sqlite_projection(source_messages):
    db, store, first, next_job = source_messages
    parts = [
        {'type': 'text', 'text': 'Verified the issue.'},
        {'type': 'think', 'text': 'I checked the repository history.',
         'reasoning_label_step_id': 'reason1', 'reasoning_label_revision': 1,
         'reasoning_label_status': 'complete', 'reasoning_label': 'Checked history'},
        {'type': 'activity_label', 'activity_label_type': 'phase', 'activity_start_index': 0,
         'activity_label': 'Research and verification', 'activity_label_revision': 1},
    ]
    _set_parts(db, first.response_message_id, parts)
    history = store.history('owner', next_job.conversation_id, message_id=next_job.user_message_id)
    assert any(entry.get('reasoning_content') == 'I checked the repository history.'
               for entry in history)
    snapshot, trusted = derive_persisted_semantic_index(
        db, 'owner', next_job.conversation_id, next_job.user_message_id, history)
    assert snapshot is not None
    assert [entry['type'] for entry in snapshot.entries] == ['reasoning_label', 'activity_phase']
    rendered = render_compaction_semantic_index(snapshot, trusted)
    assert rendered['entryCount'] == 2
    assert 'reasoning_label: Checked history' in rendered['appendix']
    assert 'activity_phase: Research and verification' in rendered['appendix']
    assert 'additional_kwargs' not in history[1]
    assert 'additional_kwargs' in trusted[1]
    assert all(entry['sourceMessageId'] == first.response_message_id for entry in snapshot.entries)


def test_unmatched_or_ambiguous_assistant_text_cannot_authorize_labels(source_messages):
    db, store, first, next_job = source_messages
    parts = [
        {'type': 'text', 'text': 'Verified the issue.'},
        {'type': 'think', 'text': 'Reasoning evidence', 'reasoning_label_step_id': 'r',
         'reasoning_label_revision': 0, 'reasoning_label_status': 'complete',
         'reasoning_label': 'Sensitive internal label'},
    ]
    _set_parts(db, first.response_message_id, parts)
    history = store.history('owner', next_job.conversation_id, message_id=next_job.user_message_id)
    clone = json.loads(json.dumps(history))
    for entry in clone:
        if entry.get('role') == 'assistant':
            entry['reasoning_content'] = 'A different thought'
    snapshot, _ = derive_persisted_semantic_index(db, 'owner', next_job.conversation_id,
                                                   next_job.user_message_id, clone)
    assert snapshot is None
    ambiguous = [*history, *[entry for entry in history if entry.get('role') == 'assistant']]
    snapshot, _ = derive_persisted_semantic_index(db, 'owner', next_job.conversation_id,
                                                   next_job.user_message_id, ambiguous)
    assert snapshot is None
    snapshot, _ = derive_persisted_semantic_index(db, 'other-owner', next_job.conversation_id,
                                                   next_job.user_message_id, history)
    assert snapshot is None


def test_pending_redacted_and_malformed_labels_never_enter_summary(source_messages):
    db, store, first, next_job = source_messages
    parts = [
        {'type': 'text', 'text': 'Verified the issue.'},
        {'type': 'think', 'text': 'Observed history', 'reasoning_label_step_id': 'r1',
         'reasoning_label_revision': 1, 'reasoning_label_status': 'streaming',
         'reasoning_label': 'Not yet committed'},
        {'type': 'think', 'text': 'Observed another history', 'reasoning_label_step_id': 'r2',
         'reasoning_label_revision': 1, 'reasoning_label_status': 'weird',
         'reasoning_label': 'Malformed state'},
        {'type': 'activity_label', 'activity_label_type': 'phase', 'activity_start_index': 0,
         'pending': True, 'activity_label': 'Pending phase'},
        {'type': 'activity_label', 'activity_label_type': 'phase', 'activity_start_index': 0,
         'pending': 'true', 'activity_label': 'Malformed phase'},
    ]
    _set_parts(db, first.response_message_id, parts)
    history = store.history('owner', next_job.conversation_id, message_id=next_job.user_message_id)
    snapshot, trusted = derive_persisted_semantic_index(db, 'owner', next_job.conversation_id,
        next_job.user_message_id, history)
    assert snapshot is not None
    assert len(snapshot.entries) == 4
    assert all(entry['status'] == 'pending' for entry in snapshot.entries)
    assert render_compaction_semantic_index(snapshot, trusted)['entryCount'] == 0


def test_rejects_reasoning_and_activity_index_forgery_without_visible_anchors():
    source = 'source-1'
    refs = {}
    parts = [{'type': 'tool_call', 'tool_call': {'id': 'tool1'}},
             {'type': 'activity_label', 'activity_label_type': 'phase',
              'activity_start_index': 0, 'activity_label': 'Fake reference'},
             {'type': 'think', 'text': 'Not visible', 'reasoning_label_step_id': 'r',
              'reasoning_label_revision': 0, 'reasoning_label_status': 'complete',
              'reasoning_label': 'Secret'}]
    assert _labels_from_source(source, parts, None, refs) == []
    assert refs == {}
    assert _labels_from_source(source, parts, (1, []), refs) == []
    assert _labels_from_source(source, parts, (1, [2]), refs)[0]['type'] == 'reasoning_label'


def test_derived_snapshot_bounded_coverage_preserves_earliest_latest_and_each_kind():
    entries = []
    for i in range(700):
        kind = ['tool_intent', 'tool_outcome', 'activity_phase', 'reasoning_label'][i % 4]
        record = {'type': kind, 'sourceMessageId': 'source', 'sourceContentIndex': i % 100,
                  'revision': i // 100, 'status': 'committed', 'text': f'entry-{i:03d}'}
        if kind == 'reasoning_label':
            record['reasoningStepId'] = f'R{i}'
        elif kind != 'activity_phase':
            record['toolCallId'] = f'C{i}'
        entries.append(record)
    snapshot = _derived_semantic_snapshot(entries)
    assert snapshot is not None
    assert len(snapshot.entries) <= 256
    assert snapshot.provided_entry_count == 700
    assert snapshot.entries[0]['text'] == 'entry-000'
    assert snapshot.entries[-1]['text'] == 'entry-699'
    assert set(entry['type'] for entry in snapshot.entries) == {
        'tool_intent', 'tool_outcome', 'activity_phase', 'reasoning_label'}
    assert _derived_semantic_snapshot([]) is None
