"""Live HTTP, tool-runner and memory audit integration of source-scoped filters."""
from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes as routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, RuntimeSafetyError
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory_protection import inspect_memory_content, project_stored_memories
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    repo = WorkspaceRepository(db)
    profile = ProviderConfig('openai', 'mock', 'http://127.0.0.1:9000/v1/chat/completions', '')
    monkeypatch.setattr(routes, '_database', lambda: db)
    monkeypatch.setattr(routes, '_generation_store', lambda: store)
    monkeypatch.setattr(routes, '_owner', lambda request: 'owner')
    monkeypatch.setattr(routes, '_request_grant', lambda request: (set(), None))
    monkeypatch.setattr(routes, 'provider_config', lambda *a, **kw: profile)
    from local_shell_mcp.webui import machine_permissions

    monkeypatch.setattr(machine_permissions, 'resolve_access', lambda *a, **kw: {})
    tasks = []

    async def start(*a, **kw):
        tasks.append((a, kw))

    monkeypatch.setattr(routes, '_start_task', start)
    app = Starlette(routes=routes.generation_routes())
    return db, store, repo, profile, app, tasks


def _policy(source='messages', *, action='block', pattern='bearer_header'):
    return {source: {'pii': {'action': action, 'starterPatterns': [pattern]}}}


@pytest.mark.asyncio
async def test_submitted_chat_message_blocked_before_creating_run(runtime):
    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', _policy())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        blocked = await client.post('/api/agents/chat', json={'text': 'Bearer hidden-token', 'model': 'mock'})
        assert blocked.status_code == 400
        assert blocked.json() == {
            'error': 'content_filter_block',
            'message': 'Submitted content was blocked by content policy.',
            'source': 'message', 'field': 'content_part'}
        assert 'hidden-token' not in blocked.text
        allowed = await client.post('/api/agents/chat', json={'text': 'A public question'})
        assert allowed.status_code == 202
    assert len(tasks) == 1
    with db.connect() as connection:
        assert connection.execute('SELECT count(*) FROM runs').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_agent_instruction_policy_rechecks_even_if_user_text_is_safe(runtime):
    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', _policy('agentInstructions'))
    agent = AgentRepository(db).create('owner', {'name': 'Private',
        'provider': 'openAI', 'model': 'mock', 'instructions': 'Bearer classified-token'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/api/agents/chat', json={'text': 'Hello', 'agent_id': agent['id']})
        assert result.status_code == 400
        assert result.json()['source'] == 'agent_instruction'
        assert 'classified-token' not in result.text
    assert not tasks


@pytest.mark.asyncio
async def test_audit_only_chat_records_metadata_and_allows_generation(runtime, monkeypatch):
    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', _policy(action='audit'))
    from local_shell_mcp import audit

    events = []
    monkeypatch.setattr(audit, 'audit', lambda event, **kwargs: events.append((event, kwargs)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/agents/chat', json={'text': 'Bearer TOP-SECRET'})
    assert response.status_code == 202
    assert len(tasks) == 1
    assert len(events) == 1 and events[0][0] == 'content_filter_audit'
    assert events[0][1]['source'] == 'message'
    assert 'TOP-SECRET' not in str(events)


@pytest.mark.asyncio
async def test_tools_block_before_side_effects_and_sanitize_sensitive_output(runtime, monkeypatch):
    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', _policy('toolArguments'))
    job, _ = store.begin('owner', {'text': 'Perform a tool operation'})

    async def no_model(*a, **kw):
        if False:
            yield ''

    async def no_output(_):
        pass

    runner = AgentRunner('owner', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=no_model, stream_text=no_model, on_text=no_output,
                         profile=profile)
    invoked = []

    async def fake_tool(call, state):
        invoked.append(call.name)
        return 'Bearer secret-output' if call.name == 'safe_tool' else 'public'

    monkeypatch.setattr(runner, '_invoke', fake_tool)
    state = AgentLoopState(AgentContext(profile, [{'function': {'name': 'safe_tool'}}]),
                           [{'role': 'user', 'content': 'Call a tool'}])
    await runner._save(state, [])
    secret = ModelToolCall('blocked-input', 'safe_tool', {'token': 'Bearer sensitive-credential'})
    safe = ModelToolCall('blocked-output', 'safe_tool', {'param': 'public'})
    result = await runner._dispatch([secret, safe], state)
    assert invoked == ['safe_tool']
    assert result.messages[0]['content'] == 'Tool call blocked by configured content protection policy.'
    assert result.messages[1]['content'] == 'Tool output withheld by configured content protection policy.'
    assert 'sensitive-credential' not in str(store.events('owner', job.run_id))
    assert 'secret-output' not in str(store.events('owner', job.run_id))
    assert not any('secret-output' in str(entry) for entry in runner.cache.values())


@pytest.mark.asyncio
async def test_assembled_context_is_checked_without_max_context_tokens(runtime):
    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', _policy())
    job, _ = store.begin('owner', {'text': 'Hello'})

    async def no_model(*a, **kw):
        if False:
            yield ''

    async def no_output(_):
        pass

    runner = AgentRunner('owner', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=no_model, stream_text=no_model, on_text=no_output,
                         profile=profile)
    state = AgentLoopState(AgentContext(profile, []), [
        {'role': 'user', 'content': 'Normal question'},
        {'role': 'tool', 'content': 'Bearer sensitive-credential'}])
    with pytest.raises(RuntimeSafetyError, match='context was blocked'):
        await runner._before_model(state)
    child = AgentRunner('owner', job, db, store, scopes=set(), grant_expires=None,
                        stream_tools=no_model, stream_text=no_model, on_text=no_output,
                        profile=profile, namespace='subagent-1')
    with pytest.raises(RuntimeSafetyError, match='context was blocked'):
        await child._before_model(state)
    assert store.latest('owner', job.conversation_id).status == 'running'


def test_memory_policy_audit_on_write_and_projection_does_not_leak(runtime, monkeypatch):
    db, store, repo, profile, app, tasks = runtime
    filters = _policy('memories', action='audit')
    from local_shell_mcp import audit

    metadata = []
    monkeypatch.setattr(audit, 'audit', lambda event, **kw: metadata.append((event, kw)))
    assert inspect_memory_content({'key': 'user_key', 'value': 'Bearer secret-record'}, filters) is None
    record = {'id': 'opaque', 'key': 'user_key', 'value': 'Bearer secret-record'}
    assert project_stored_memories([record], filters) == [record]
    assert len(metadata) == 2
    assert all('secret-record' not in str(item) for item in metadata)
    assert all(item[1]['source'] == 'memory' for item in metadata)


@pytest.mark.asyncio
async def test_model_tool_arguments_redacted_before_any_checkpoint_or_sse(runtime, monkeypatch):
    from local_shell_mcp.webui.agent_runtime import run_agent_loop

    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', _policy('toolArguments'))
    job, _ = store.begin('owner', {'text': 'Run a selected tool'})
    executed = []

    async def stream_tools(*args, **kwargs):
        yield ModelToolCall('call-sensitive', 'safe_tool', {'token': 'Bearer PRIVATE-CONTENT'})

    async def stream_text(*args, **kwargs):
        yield 'Text result'

    async def no_output(_):
        pass

    async def execute(call, state):
        executed.append(call.call_id)
        return 'MUST NOT RUN'

    runner = AgentRunner('owner', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=stream_tools, stream_text=stream_text, on_text=no_output,
                         profile=profile)
    monkeypatch.setattr(runner, '_invoke', execute)
    state = AgentLoopState(AgentContext(profile,
        [{'type': 'function', 'function': {'name': 'safe_tool'}}], tool_end=True),
        [{'role': 'user', 'content': 'Perform operation'}])
    history = await run_agent_loop(state, stream_tools=stream_tools, stream_text=stream_text,
        dispatch=runner._dispatch, on_text=no_output, save_state=runner._save,
        preflight_calls=runner._preflight_model_calls)
    assert not executed
    assert history[-1]['content'] == 'Tool call blocked by configured content protection policy.'
    assert history[-2]['tool_calls'][0]['function']['arguments'] == '{"_content_filter_blocked": true}'
    with db.connect() as connection:
        checkpoints = [row[0] for row in connection.execute('SELECT checkpoint FROM agent_checkpoints')]
        events = [row[0] for row in connection.execute('SELECT data FROM generation_events')]
    assert 'PRIVATE-CONTENT' not in str(checkpoints) + str(events)
    assert 'PRIVATE-CONTENT' not in json.dumps(history)
    assert '_content_filter_blocked' in json.dumps(history)


@pytest.mark.asyncio
async def test_blocked_ask_user_input_never_persists_question_or_pauses(runtime, monkeypatch):
    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', _policy('toolArguments'))
    job, _ = store.begin('owner', {'text': 'Ask user a question'})

    async def no_model(*args, **kwargs):
        if False:
            yield ''

    async def no_output(_):
        pass

    runner = AgentRunner('owner', job, db, store, scopes=set(), grant_expires=None,
        stream_tools=no_model, stream_text=no_model, on_text=no_output, profile=profile)
    call = ModelToolCall('ask-private', 'ask_user_question', {'question': 'Bearer PRIVATE-CONTENT'})
    state = AgentLoopState(AgentContext(profile, [{'function': {'name': 'ask_user_question'}}]),
                           [{'role': 'user', 'content': 'some prompt'}])
    await runner._save(state, [])
    output = await runner._dispatch([call], state)
    assert output.messages[0]['content'] == 'Tool call blocked by configured content protection policy.'
    assert store.latest('owner', job.conversation_id).status == 'running'
    assert 'PRIVATE-CONTENT' not in str(store.events('owner', job.run_id))


@pytest.mark.asyncio
async def test_model_parameter_policy_blocks_before_model_invocation(runtime):
    db, store, repo, profile, app, tasks = runtime
    repo.save_setting('owner', 'webui.filters.config', {'modelParameters': {'pii': {
        'starterPatterns': [], 'customPatterns': [
            {'id': 'secret_stop', 'label': 'secret', 'regex': 'private_key_[0-9]+'}],
        'fields': ['stop']}}})
    agent = AgentRepository(db).create('owner', {'name': 'Private Parameters',
        'provider': 'openAI', 'model': 'mock', 'model_parameters': {'stop': ['private_key_123']}})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/api/agents/chat', json={'text': 'Normal question', 'agent_id': agent['id']})
        assert result.status_code == 400
        assert result.json()['source'] == 'model_parameter'
    assert tasks == []
