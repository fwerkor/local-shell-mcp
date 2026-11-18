"""Review regressions: run-step indexing, detached controls, OAuth and reattachment."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import (
    AgentContext,
    AgentLoopState,
    ToolBatchOutput,
    run_agent_loop,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


def test_run_step_index_preserves_text_slot_when_tool_completes_first(tmp_path):
    store = GenerationStore(SQLiteDatabase(tmp_path / 'db'))
    run, _ = store.begin('owner', {'text': 'test'})
    store.append('owner', run.run_id, {'event': 'on_run_step', 'data': {
        'id': 'answer-step', 'index': 0, 'type': 'message_creation'}})
    store.append('owner', run.run_id, {'event': 'on_run_step', 'data': {
        'id': 'tool-step', 'index': 1, 'type': 'tool_calls'}})
    completed = {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'tool-step', 'index': 1, 'tool_call': {
            'id': 'call-one', 'name': 'file_read', 'output': 'result'}}}}
    store.append('owner', run.run_id, completed)
    empty, _ = store.resume_snapshot('owner', run.run_id)
    assert [p['type'] for p in empty['aggregatedContent']] == ['text', 'tool_call']
    assert empty['aggregatedContent'][0]['text'] == ''
    store.append('owner', run.run_id, {'event': 'on_message_delta', 'data': {
        'id': 'answer-step', 'delta': {'content': {'type': 'text', 'text': 'Answer '}}}})
    store.append('owner', run.run_id, {'event': 'on_message_delta', 'data': {
        'id': 'answer-step', 'delta': {'content': {'type': 'text', 'text': 'complete'}}}})
    store.append('owner', run.run_id, completed)
    snap, _ = store.resume_snapshot('owner', run.run_id)
    assert snap['aggregatedContent'][0]['text'] == 'Answer complete'
    assert snap['aggregatedContent'][1]['tool_call']['id'] == 'call-one'
    assert len(snap['aggregatedContent']) == 2


@pytest.mark.asyncio
async def test_detached_steer_after_tool_overrides_end_after_tools():
    config = ProviderConfig('openai', 'stub', 'https://invalid.example', '')
    state = AgentLoopState(AgentContext(config, [{'function': {'name': 'read'}}], tool_end=True),
                           [{'role': 'user', 'content': 'read then continue'}])
    turns = []
    controls = []

    async def stream(*_args, **_kwargs):
        turns.append(1)
        if len(turns) == 1:
            yield ModelToolCall('call-one', 'read', {})
        else:
            assert any(m.get('content') == 'Accepted correction' for m in state.messages)
            yield 'Corrected answer'

    async def dispatch(*_args):
        return ToolBatchOutput([{'role': 'tool', 'tool_call_id': 'call-one', 'content': 'raw'}])

    async def inject(current, boundary):
        controls.append(boundary)
        if boundary == 'tool':
            current.messages.append({'role': 'user', 'content': 'Accepted correction'})
            return True
        return False

    async def noop(_):
        return None

    output = await run_agent_loop(state, stream_tools=stream, stream_text=stream,
                                  dispatch=dispatch, on_text=noop, inject_controls=inject)
    assert len(turns) == 2
    assert output[-1]['content'] == 'Corrected answer'
    assert controls.count('tool') >= 2


@pytest.mark.asyncio
async def test_detached_oauth_is_blocked_without_parking_or_starting_flow(tmp_path, monkeypatch):
    from local_shell_mcp.webui import action_oauth
    from local_shell_mcp.webui.action_spec import tool_name
    from local_shell_mcp.webui.actions import ActionRepository

    db = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(db)
    agent = {'id': 'agent-1', 'tools': []}
    run, _ = store.begin('owner', {'text': 'test'})
    name = tool_name('get_resource', 'api.example.org')
    assert name
    monkeypatch.setattr(ActionRepository, 'get_for_tool', lambda *args: (
        {'auth': {'type': 'oauth'}}, {}, {'action_id': 'action-1', 'action_version': 1}))

    async def no_token(*args, **kwargs):
        return None

    def never_redirect(*_args, **_kwargs):
        raise AssertionError('Detached OAuth must not create an interactive login flow')

    monkeypatch.setattr(action_oauth, 'access_token', no_token)
    monkeypatch.setattr(action_oauth, 'begin_flow', never_redirect)
    async def silent(*_args, **_kwargs):
        return None

    runner = AgentRunner('owner', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=silent, stream_text=silent, on_text=silent,
                         agent=agent, background_deny=True)
    state = AgentLoopState(AgentContext(ProviderConfig('openai', 'model', 'https://invalid.example', ''),
                                        [{'function': {'name': name}}], agent=agent), [])
    tool = ModelToolCall('call-one', name, {})
    await runner._prepare_oauth([tool], state)
    assert await runner._invoke(tool, state) == 'Blocked: OAuth Action requires foreground human authorization.'
    assert store.pending_action('owner', run.run_id) is None


@pytest.mark.asyncio
async def test_foreground_reattach_refuses_detached_child(monkeypatch):
    class FakeDatabase:
        def connect(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def execute(self, query, params=()):
            if 'child_run_id=?' in query:
                assert params == ('owner', 'child-run')
            return SimpleNamespace(fetchone=lambda: (1,))

    monkeypatch.setattr(generation_routes, '_database', FakeDatabase)
    run = SimpleNamespace(run_id='child-run', conversation_id='child-conversation')
    with pytest.raises(HTTPException) as caught:
        await generation_routes._reattach_running_actor(None, 'owner', run)
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_nested_graph_subagent_tool_results_are_not_published_to_parent(tmp_path, monkeypatch):
    from local_shell_mcp.webui.checkpoints import SQLiteCheckpointSaver

    db = SQLiteDatabase(tmp_path / 'parent')
    store = GenerationStore(db)
    run, _ = store.begin('owner', {'text': 'Delegate private inspection'})

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(SQLiteCheckpointSaver, 'put_writes', lambda *args, **kwargs: None)
    config = {'scopes': set(), 'grant_expires': None, 'stream_tools': noop,
              'stream_text': noop, 'on_text': noop, 'profile': ProviderConfig(
                  'openai', 'model', 'https://invalid.example', '')}
    isolated = AgentRunner('owner', run, db, store,
                           namespace='/subagent:delegation/graph:member:one', graph_node=True, **config)
    foreground = AgentRunner('owner', run, db, store, namespace='/graph:member:two',
                             graph_node=True, **config)
    completed = {'proposal': {'name': 'file_read', 'args': {}}, 'output': 'PRIVATE CHILD FINDING'}
    call = ModelToolCall('tool-child', 'file_read', {})
    assert isolated._publishes_tool_steps() is False
    original_events = store.events('owner', run.run_id)
    await isolated._completed(call, completed)
    assert store.events('owner', run.run_id) == original_events
    assert foreground._publishes_tool_steps() is True
    await foreground._completed(ModelToolCall('tool-root', 'file_read', {}),
                                {'proposal': {'name': 'file_read', 'args': {}}, 'output': 'Public finding'})
    recorded = store.events('owner', run.run_id)
    assert any(item.get('event') == 'on_run_step_completed' for _, item in recorded)
    assert 'PRIVATE CHILD FINDING' not in str(recorded)


def test_active_step_lookup_reads_all_event_pages_after_steer(tmp_path):
    store = GenerationStore(SQLiteDatabase(tmp_path / 'state'))
    run, _ = store.begin('owner', {'text': 'long streaming answer'})
    store.append('owner', run.run_id, {'event': 'on_run_step', 'data': {
        'id': 'first', 'type': 'message_creation', 'index': 0, 'created_at': 100}})
    for _ in range(205):
        store.append('owner', run.run_id, {'event': 'on_message_delta', 'data': {
            'id': 'first', 'delta': {'content': {'type': 'text', 'text': '.'}}}})
    store.append('owner', run.run_id, {'event': 'on_run_step_closed', 'data': {'id': 'first'}})
    store.append('owner', run.run_id, {'event': 'on_steer_applied', 'data': {
        'index': 1, 'part': {'type': 'steer', 'steer': 'new instruction'}}})
    store.append('owner', run.run_id, {'event': 'on_run_step', 'data': {
        'id': 'second', 'type': 'message_creation', 'index': 2, 'created_at': 200}})
    assert generation_routes._last_open_message_step(store, 'owner', run.run_id) == (
        'second', 2, 200)
