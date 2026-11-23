"""Live React message indices match the durable resume projection after tools."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner, generation_routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.mark.asyncio
async def test_live_text_tool_text_uses_new_step_matching_recovery_snapshot(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    job, _ = store.begin('local', {'text': 'Run command then explain'})
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)

    class FakeAgentRunner:
        def __init__(self, *args, on_text, on_tool_completed, **kwargs):
            self.on_text = on_text
            self.on_tool_completed = on_tool_completed
            self.partial_text = ''

        async def run(self, _history):
            await self.on_text('Before result')
            store.append('local', job.run_id, {'event': 'on_run_step_completed', 'data': {
                'result': {'id': 'tool-step', 'type': 'tool_call', 'tool_call': {
                    'id': 'call-1', 'name': 'run_shell', 'output': 'okay', 'args': {}}}}})
            await self.on_tool_completed(ModelToolCall('call-1', 'run_shell', {}))
            await self.on_text('After result')
            self.partial_text = 'Before resultAfter result'

    monkeypatch.setattr(agent_runner, 'AgentRunner', FakeAgentRunner)
    profile = ProviderConfig('openai', 'mock', 'https://example.invalid', '')
    await generation_routes._run_model('local', job, profile)
    events = [item for _, item in store.events('local', job.run_id)]
    messages = [item['data'] for item in events if item.get('event') == 'on_message_delta']
    assert len(messages) == 2
    assert messages[0]['id'] != messages[1]['id']
    steps = [item['data'] for item in events if item.get('event') == 'on_run_step']
    assert [item['index'] for item in steps] == [0, 2]
    snapshot, _ = store.resume_snapshot('local', job.run_id)
    assert [part['type'] for part in snapshot['aggregatedContent']] == [
        'text', 'tool_call', 'text']
    assert [step['index'] for step in snapshot['runSteps']] == [0, 2]
    assert messages[1]['id'] == steps[1]['id']


def test_rewind_keeps_replayed_tool_slot_stable_in_resume_snapshot(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    job, _ = store.begin('local', {'text': 'Approve and resume the tool'})
    store.append('local', job.run_id, {'event': 'on_run_step', 'data': {
        'id': 'message-step', 'type': 'message_creation', 'index': 0,
        'runId': job.response_message_id,
    }})
    store.append('local', job.run_id, {'event': 'on_run_step', 'data': {
        'id': 'tool-step', 'type': 'tool_calls', 'index': 1,
        'runId': job.response_message_id,
    }})
    completion = {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'tool-step', 'tool_call': {
            'id': 'call-1', 'name': 'run_shell', 'args': {}, 'output': 'ok',
        },
    }}}
    store.append('local', job.run_id, completion)
    store.append('local', job.run_id, {'event': 'on_content_rewind', 'data': {
        'preserveText': '', 'runId': job.response_message_id,
    }})
    # Human reattachment can replay an already recorded tool completion.
    store.append('local', job.run_id, completion)

    snapshot, _ = store.resume_snapshot('local', job.run_id)
    parts = snapshot['aggregatedContent']
    assert len(parts) == 2
    assert parts[0] == {'type': 'text', 'text': '', 'phase': 'final_answer'}
    assert parts[1]['tool_call']['id'] == 'call-1'
    assert len([part for part in parts if part['type'] == 'tool_call']) == 1
    assert snapshot['runSteps'][1]['index'] == 1
    assert store.finish('local', job.run_id, status='complete', text='')
    saved = store.history('local', job.conversation_id)
    assert saved


def test_rewind_reindexes_finalized_tool_closure_after_discarding_text(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    job, _ = store.begin('local', {'text': 'Recover interrupted tool'})
    store.append('local', job.run_id, {'event': 'on_message_delta', 'data': {
        'id': 'message-step', 'delta': {'content': {'type': 'text', 'text': 'Discard me'}},
    }})
    tool = {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'tool-step', 'tool_call': {'id': 'call-1', 'name': 'run_shell', 'output': 'ok'},
    }}}
    store.append('local', job.run_id, tool)
    store.append('local', job.run_id, {'event': 'on_content_rewind', 'data': {'preserveText': ''}})
    store.append('local', job.run_id, tool)
    store.append('local', job.run_id, {'event': 'on_run_step_closed', 'data': {
        'id': 'tool-step', 'status': 'completed', 'created_at': 100, 'closed_at': 200,
    }})
    assert store.finish('local', job.run_id, status='complete', text='')
    with db.connect() as conn:
        saved = conn.execute('SELECT content FROM messages WHERE id=?',
                             (job.response_message_id,)).fetchone()
    assert saved is not None
    parts = json.loads(saved['content'])
    assert len(parts) == 1
    assert parts[0]['tool_call']['runStepStatus'] == 'completed'
