"""Canonical SQLite tool outcome index producer is owner/branch/text bound."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.semantic_index import render_compaction_semantic_index
from local_shell_mcp.webui.semantic_index_source import derive_persisted_semantic_index


@pytest.fixture
def persisted_tool(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    job, _ = store.begin('local', {'text': 'Read the repo contents'})
    calls = [
        {'type': 'tool_call', 'tool_call': {'id': 'call-source', 'name': 'source_tool',
            'args': {'intent': 'Read README'}, 'output': 'File has 5 entries.'}},
        {'type': 'text', 'text': 'Tool completed.'},
    ]
    with db.connect() as connection:
        connection.execute('UPDATE runs SET state=json_set(state,\'$.testing\',1) WHERE id=?', (job.run_id,))
    store.append('local', job.run_id, {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'step-source', 'tool_call': calls[0]['tool_call']}}})
    assert store.finish('local', job.run_id, status='complete', text='Tool completed.')
    next_job, _ = store.begin('local', {
        'text': 'Now summarize', 'conversationId': job.conversation_id,
        'parentMessageId': job.response_message_id,
    })
    return db, store, job, next_job


def test_trusted_persisted_output_yields_source_index_and_bound_provenance(persisted_tool):
    db, store, previous, latest = persisted_tool
    history = store.history('local', latest.conversation_id, message_id=latest.user_message_id)
    assert any(entry.get('role') == 'tool' for entry in history)
    frozen, verified = derive_persisted_semantic_index(
        db, 'local', latest.conversation_id, latest.user_message_id, history,
        intent_tool_names={'source_tool'})
    assert frozen is not None
    assert len(frozen.entries) == 2
    assert set(entry['type'] for entry in frozen.entries) == {'tool_outcome', 'tool_intent'}
    assert all(entry['sourceMessageId'] == previous.response_message_id for entry in frozen.entries)
    semantic = render_compaction_semantic_index(frozen, verified)
    assert semantic['entryCount'] == 2
    assert '- tool_intent: Read README' in semantic['appendix']
    assert '- tool_outcome: File has 5 entries.' in semantic['appendix']
    assert all('additional_kwargs' not in entry for entry in history)  # copy, not model request mutation
    assert verified != history


def test_source_producer_rejects_other_owner_and_edited_or_missing_tool_messages(persisted_tool):
    db, store, previous, latest = persisted_tool
    history = store.history('local', latest.conversation_id, message_id=latest.user_message_id)
    assert derive_persisted_semantic_index(db, 'bob', latest.conversation_id,
        latest.user_message_id, history)[0] is None
    assert derive_persisted_semantic_index(db, 'local', 'no-such-conversation',
        latest.user_message_id, history)[0] is None
    altered = json.loads(json.dumps(history))
    for record in altered:
        if record.get('role') == 'tool':
            record['content'] = 'A different text than was actually stored.'
    assert derive_persisted_semantic_index(db, 'local', latest.conversation_id,
        latest.user_message_id, altered)[0] is None
    only_text = [{'role': 'assistant', 'content': 'No tool invocations'}]
    assert derive_persisted_semantic_index(db, 'local', latest.conversation_id,
        latest.user_message_id, only_text)[0] is None
    assert derive_persisted_semantic_index(db, 'local', latest.conversation_id,
        latest.user_message_id, history[:1])[0] is None


@pytest.mark.asyncio
async def test_real_summary_reads_persisted_host_tool_outcome_with_no_external_index(persisted_tool):
    db, store, previous, latest = persisted_tool
    seen = []

    async def provider(profile, messages, **kw):
        seen.append(messages[-1]['content'])
        yield '## Checkpoint\nWe read the repository.'

    async def empty(*args, **kwargs):
        if False:
            yield ''

    async def emit(_):
        pass

    runner = AgentRunner('local', latest, db, store, scopes=set(), grant_expires=None,
        stream_tools=empty, stream_text=provider, on_text=emit,
        profile=ProviderConfig('openai', 'mock', 'http://127.0.0.1:11001', ''))
    history = store.history('local', latest.conversation_id, message_id=latest.user_message_id)
    await runner._summarize_history(history, head_count=len(history))
    assert len(seen) == 1
    assert '- tool_outcome: File has 5 entries.' in seen[0]
    assert '- tool_intent:' not in seen[0]  # Source requires explicit intent tool selection
    assert store.finish('local', latest.run_id, status='complete', text='Continued')
    assert 'Checkpoint' in str(store.events('local', latest.run_id))


@pytest.mark.parametrize('replacement', [
    {'id': '', 'name': 'source_tool', 'output': 'File has 5 entries.'},
    {'id': 'call-source', 'name': 'source_tool', 'output': None},
    {'id': 'call-source', 'name': 'source_tool', 'output': ''},
    {'id': 'call-source', 'name': 'source_tool', 'output': ['not text']},
    {'id': 'call-source', 'name': 'source_tool', 'output': 'A different outcome'},
])
def test_source_rejects_untrustworthy_or_unmatched_canonical_parts(persisted_tool, replacement):
    db, store, previous, latest = persisted_tool
    history = store.history('local', latest.conversation_id, message_id=latest.user_message_id)
    with db.connect() as connection:
        connection.execute('UPDATE messages SET content=? WHERE id=?',
            (json.dumps([{'type': 'tool_call', 'tool_call': replacement}]), previous.response_message_id))
    rendered, messages = derive_persisted_semantic_index(
        db, 'local', latest.conversation_id, latest.user_message_id, history)
    assert rendered is None
    assert messages == history


def test_source_producer_rejects_duplicate_calls_and_untrusted_provenance(persisted_tool):
    db, store, previous, latest = persisted_tool
    history = store.history('local', latest.conversation_id, message_id=latest.user_message_id)
    duplicate = json.loads(json.dumps(history))
    duplicate.extend([item for item in duplicate if item.get('role') == 'tool'])
    assert derive_persisted_semantic_index(db, 'local', latest.conversation_id,
        latest.user_message_id, duplicate)[0] is None
    duplicate = json.loads(json.dumps(history))
    duplicate.extend([item for item in duplicate if item.get('tool_calls')])
    assert derive_persisted_semantic_index(db, 'local', latest.conversation_id,
        latest.user_message_id, duplicate)[0] is None
    invalid = json.loads(json.dumps(history))
    for message in invalid:
        if message.get('role') == 'tool':
            message['additional_kwargs'] = {'provenance': {'version': 3, 'parts': []}}
    source, modified = derive_persisted_semantic_index(db, 'local', latest.conversation_id,
        latest.user_message_id, invalid)
    assert source is not None
    assert render_compaction_semantic_index(source, modified)['entryCount'] == 1
    # The valid canonical assistant message has independently verified lineage;
    # malformed caller-supplied tool metadata cannot be used as an authority.
    assert modified != history
    invalid[0] = None
    assert derive_persisted_semantic_index(db, 'local', latest.conversation_id,
        latest.user_message_id, invalid)[0] is not None


def test_source_reads_malformed_content_conservatively_without_leak(persisted_tool):
    db, store, previous, latest = persisted_tool
    history = store.history('local', latest.conversation_id, message_id=latest.user_message_id)
    for bad in ('not valid JSON', 'null', 'false', '42', '"raw"',
                json.dumps([None, 'bad', {'type': 'tool_call', 'tool_call': 'invalid'}])):
        with db.connect() as connection:
            connection.execute('UPDATE messages SET content=? WHERE id=?',
                               (bad, previous.response_message_id))
        frozen, projected = derive_persisted_semantic_index(
            db, 'local', latest.conversation_id, latest.user_message_id, history)
        assert frozen is None
        assert projected == history
