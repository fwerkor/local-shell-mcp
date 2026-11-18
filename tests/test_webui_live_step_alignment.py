"""Live React message indices match the durable resume projection after tools."""
from __future__ import annotations

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
