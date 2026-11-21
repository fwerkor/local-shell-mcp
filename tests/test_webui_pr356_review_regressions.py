"""Targeted regressions for the PR #356 integration review."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.steering import SteeringStore, SteerRejection


def test_steering_submission_and_quotes_obey_content_part_block_policy(tmp_path, monkeypatch):
    from local_shell_mcp.webui import memory_protection

    db = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(db)
    run, _ = store.begin('local', {'text': 'Safe initial question'})
    policy = {'messages': {'pii': {'action': 'block', 'fields': ['content_part'],
                                 'starterPatterns': ['bearer_header']}}}
    monkeypatch.setattr(memory_protection, 'configured_filters', lambda repo, owner: policy)
    steering = SteeringStore(db)
    for body in ({'text': 'Bearer secret-token'},
                 {'text': 'An ordinary question', 'quotes': ['Bearer secret-token']}):
        with pytest.raises(SteerRejection) as exc:
            steering.enqueue('local', {'conversationId': run.conversation_id, **body},
                             preempt_capable=True)
        assert exc.value.status == 400
        assert exc.value.body['code'] == 'CONTENT_FILTER_BLOCKED'
        assert exc.value.body['field'] == 'content_part'
    with db.connect() as connection:
        state = json.loads(connection.execute(
            'SELECT state FROM runs WHERE id=?', (run.run_id,)).fetchone()['state'])
    assert not (state.get('steering') or {}).get('queue')
    assert steering.enqueue('local', {'conversationId': run.conversation_id,
                                      'text': 'No credentials here'}, preempt_capable=True)


def test_checkpoint_replays_only_new_unsummarized_steering_with_files(tmp_path):
    store = GenerationStore(SQLiteDatabase(tmp_path / 'db'))
    run, _ = store.begin('local', {'text': 'Original question'})
    old = {'role': 'user', 'source': 'steer', 'steerId': 'old', 'content': 'Summarized steering'}
    kept = {'role': 'user', 'source': 'steer', 'steerId': 'kept', 'content': 'Retained steering'}
    new = {'role': 'user', 'source': 'steer', 'steerId': 'new',
           'content': 'New instruction', 'files': [{'file_id': 'attachment-id'}]}
    store.stage_summary('local', run.run_id, 'Earlier input was summarized', 12,
                        covered_steer_ids=['old'], retained_tail=[kept],
                        visible_text_boundary=0)
    store.stage_summary('local', run.run_id, 'Refreshed summary', 8,
                        covered_steer_ids=[], retained_tail=[kept],
                        visible_text_boundary=0)
    assert store.finish('local', run.run_id, status='complete', text='Done',
                        model_steps=[old, kept, new, {'role': 'assistant', 'content': 'Done'}])
    following, _ = store.begin('local', {'text': 'What did I change?',
                            'conversationId': run.conversation_id,
                            'parentMessageId': run.response_message_id})
    history = store.history('local', run.conversation_id, message_id=following.user_message_id)
    steers = [m for m in history if m.get('source') == 'steer']
    assert [m['steerId'] for m in steers] == ['kept', 'new']
    assert steers[1]['files'] == [{'file_id': 'attachment-id'}]
    assert any(m.get('role') == 'system' and 'Refreshed summary' in m['content']
               for m in history)


def test_completed_manual_compaction_does_not_append_failure_part(tmp_path):
    db = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(db)
    previous, _ = store.begin('local', {'text': 'Start conversation'})
    assert store.finish('local', previous.run_id, text='Initial response', status='complete')
    run, _ = store.begin('local', {'text': 'Please compact', 'compact': True,
                                  'conversationId': previous.conversation_id,
                                  'parentMessageId': previous.response_message_id})
    store.stage_summary('local', run.run_id, 'Complete summary', 11, boundary=1, manual=True)
    assert store.finish('local', run.run_id, status='complete')
    with db.connect() as connection:
        row = connection.execute('SELECT content FROM messages WHERE id=?',
                                 (run.response_message_id,)).fetchone()
    content = json.loads(row['content'])
    assert [part['type'] for part in content] == ['summary']
    assert content[0]['initiatedBy'] == 'user'


@pytest.mark.asyncio
async def test_graph_members_receive_persisted_memory_and_conversation_summary(tmp_path, monkeypatch):
    pytest.importorskip('langgraph')
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import agent_runner
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.agents import AgentRepository
    from local_shell_mcp.webui.memory import MemoryRepository
    from local_shell_mcp.webui.providers import ProviderConfig
    from local_shell_mcp.webui.storage import WorkspaceRepository

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'db'))
    get_settings.cache_clear()
    try:
        db = SQLiteDatabase(tmp_path / 'db')
        WorkspaceRepository(db).save_setting('local', 'endpoints', {'memory': {}})
        MemoryRepository(db).write('local', 'recall', 'Important saved preference.')
        agents, store = AgentRepository(db), GenerationStore(db)
        root = agents.create('local', {'name': 'root', 'provider': 'openAI',
                                       'model': 'root', 'tools': []})
        child = agents.create('local', {'name': 'child', 'provider': 'openAI',
                                        'model': 'child', 'tools': []})
        root = agents.update('local', root['id'], {'edges': [
            {'from': root['id'], 'to': child['id'], 'edgeType': 'direct'}]})
        old, _ = store.begin('local', {'text': 'Prior conversation'}, root)
        store.stage_summary('local', old.run_id, 'Prior conversation was about a project', 12)
        assert store.finish('local', old.run_id, text='Prior answer', status='complete')
        run, _ = store.begin('local', {'conversationId': old.conversation_id,
                                      'parentMessageId': old.response_message_id,
                                      'text': 'Follow up'}, root)
        seen = {}
        async def model(profile, messages, **kwargs):
            seen[profile.model] = messages
            yield 'Response from ' + profile.model
        async def sink(text):
            pass
        monkeypatch.setattr(agent_runner, 'provider_config', lambda _, model: ProviderConfig(
            'openai', model, 'http://localhost:1234/v1', ''))
        runner = AgentRunner('local', run, db, store, scopes=set(), grant_expires=None,
                             stream_tools=model, stream_text=model, on_text=sink, agent=root)
        await runner.run(store.history('local', run.conversation_id,
                                       message_id=run.user_message_id))
        assert set(seen) == {'root', 'child'}
        for messages in seen.values():
            assert any('Important saved preference.' in str(m.get('content')) for m in messages)
            assert any('Prior conversation was about a project' in str(m.get('content'))
                       for m in messages)
    finally:
        get_settings.cache_clear()

@pytest.mark.asyncio
async def test_summarizer_prepares_owned_steering_text_and_rechecks_policy(tmp_path, monkeypatch):
    import hashlib

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import agent_runner
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
    from local_shell_mcp.webui.providers import ProviderConfig

    root = tmp_path / '.state'
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(root))
    get_settings.cache_clear()
    try:
        db = SQLiteDatabase(root)
        store = GenerationStore(db)
        run, _ = store.begin('local', {'text': 'Current question'})
        folder = root / 'attachments' / hashlib.sha256(b'local').hexdigest()[:32]
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / 'note.txt'
        file.write_text('Safe document content', encoding='utf-8')
        with db.connect() as conn:
            conn.execute('INSERT INTO attachments(id,owner,name,path,content_type,metadata) '
                         'VALUES(?,?,?,?,?,?)',
                         ('note-id', 'local', file.name, str(file), 'text/plain', '{}'))
        messages_seen = []

        async def model(profile, messages, **kwargs):
            messages_seen.append(messages)
            yield 'Document context was summarized.'

        async def sink(text):
            pass

        runner = AgentRunner('local', run, db, store, scopes=set(), grant_expires=None,
                             stream_tools=model, stream_text=model, on_text=sink,
                             profile=ProviderConfig('openai', 'mock', 'https://example.invalid', ''))
        steer = {'role': 'user', 'source': 'steer', 'steerId': 'step-1',
                 'content': 'Consult the file', 'files': [{'file_id': 'note-id'}]}
        assert await runner._summarize_history([steer], semantic_index=[], head_count=1)
        assert 'Safe document content' in str(messages_seen[0])
        file.write_text('PRIVATE-ATTACHMENT', encoding='utf-8')
        block_policy = {'messages': {'pii': {'action': 'block',
            'fields': ['assembled_context'], 'starterPatterns': [],
            'customPatterns': [{'id': 'sensitive-doc', 'label': 'sensitive-doc',
                                'regex': 'PRIVATE-ATTACHMENT'}]}}}
        monkeypatch.setattr(agent_runner, 'configured_filters', lambda repo, owner: block_policy)
        with pytest.raises(RuntimeSafetyError, match='Summary context was blocked'):
            await runner._summarize_history([steer], semantic_index=[], head_count=1)
        assert len(messages_seen) == 1
    finally:
        get_settings.cache_clear()
