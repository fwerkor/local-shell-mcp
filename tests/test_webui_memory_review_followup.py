"""Regression tests for compaction, multi-modal filtering and memory boundaries."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.content_filters import inspect_content, model_message_fragments
from local_shell_mcp.webui.generations import GenerationStore


def test_assembled_context_scans_text_inside_multimodal_content():
    policy = {'messages': {'pii': {'action': 'block', 'fields': ['assembled_context'],
                           'starterPatterns': ['bearer_header']}}}
    messages = [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}},
        {'type': 'text', 'text': 'Bearer secret-token'},
    ]}]
    assert inspect_content(model_message_fragments(messages), policy) is not None
    messages[0]['content'][1]['text'] = 'No secrets here'
    assert inspect_content(model_message_fragments(messages), policy) is None


def test_checkpoint_keeps_tool_results_produced_after_its_coverage(tmp_path):
    db = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(db)
    run, _ = store.begin('local', {'text': 'Research tool calls'})
    store.stage_summary('local', run.run_id, 'Earlier tool already reviewed.', 10,
                               covered_tool_call_ids=['call-old'], retained_tail=[])
    new_steps = [
        {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'call-old', 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'call-old', 'content': 'already summarized'},
        {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'call-new', 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'call-new', 'content': 'new result: 42'},
        {'role': 'assistant', 'content': 'Final answer: 42'},
    ]
    assert store.finish('local', run.run_id, status='complete', text='Final answer: 42',
                        model_steps=new_steps)
    other, _ = store.begin('local', {'text': 'What did the new tool find?',
                              'conversationId': run.conversation_id,
                              'parentMessageId': run.response_message_id})
    hist = store.history('local', other.conversation_id, message_id=other.user_message_id)
    assert any(m.get('role') == 'system' and 'Earlier tool' in m.get('content', '') for m in hist)
    assert any(m.get('tool_call_id') == 'call-new' and '42' in m.get('content', '') for m in hist)
    assert not any(m.get('tool_call_id') == 'call-old' for m in hist)
    assert json.dumps(hist).count('new result: 42') == 1


@pytest.mark.asyncio
async def test_memory_system_prompt_does_not_duplicate_user_in_canonical_steps(tmp_path, monkeypatch):
    from local_shell_mcp.webui import generation_routes, memory_agent
    from local_shell_mcp.webui.providers import ProviderConfig
    from local_shell_mcp.webui.storage import WorkspaceRepository

    db = SQLiteDatabase(tmp_path / 'memory-db')
    store = GenerationStore(db)
    WorkspaceRepository(db).save_setting('local', 'endpoints', {'memory': {}})
    job, _ = store.begin('local', {'text': 'Unique user question'})
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)
    from local_shell_mcp.webui import machine_permissions
    monkeypatch.setattr(machine_permissions, '_repo', lambda: WorkspaceRepository(db))

    async def model(*args, **kwargs):
        yield 'One answer.'

    async def no_memory_extraction(*args, **kwargs):
        return 0

    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', model)
    monkeypatch.setattr(generation_routes, 'stream_model', model)
    monkeypatch.setattr(memory_agent, 'run_automatic_memory', no_memory_extraction)
    profile = ProviderConfig('openai', 'mock', 'https://example.invalid', '')
    await generation_routes._run_model('local', job, profile)
    assert store.get('local', job.run_id).status == 'complete'
    history = store.history('local', job.conversation_id)
    assert [m['role'] for m in history] == ['user', 'assistant']
    assert [m['content'] for m in history] == ['Unique user question', 'One answer.']
    with db.connect() as conn:
        state = json.loads(conn.execute('SELECT state FROM runs WHERE id=?', (job.run_id,)).fetchone()['state'])
    assert all(msg.get('role') != 'user' for msg in state['modelSteps'])


@pytest.mark.asyncio
async def test_joined_multimodal_text_is_checked_before_run_creation(tmp_path, monkeypatch):
    import httpx
    from starlette.applications import Starlette
    from starlette.routing import Route

    from local_shell_mcp.webui import generation_routes, memory_protection

    db = SQLiteDatabase(tmp_path / 'joined')
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    monkeypatch.setattr(generation_routes, '_owner', lambda request: 'local')
    monkeypatch.setattr(memory_protection, 'configured_filters', lambda repo, owner: {
        'messages': {'pii': {'action': 'block', 'fields': ['content_part'],
                             'starterPatterns': [], 'customPatterns': [
                                 {'id': 'joined', 'label': 'joined pattern', 'regex': 'XJOINZ'}]}}})
    app = Starlette(routes=[Route('/chat', generation_routes.start_generation, methods=['POST'])])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/chat', json={'text': 'normal', 'model': 'mock', 'content': [
            {'type': 'text', 'text': 'XJO'}, {'type': 'text', 'text': 'INZ'}]})
    assert response.status_code == 400
    assert response.json()['error'] == 'content_filter_block'
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
