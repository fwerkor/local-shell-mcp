"""HTTP and OAuth recovery boundaries for the graph-human integration."""

from __future__ import annotations

import contextlib

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture
def hosted_api(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)
    monkeypatch.setattr(generation_routes, 'provider_config', lambda *_: ProviderConfig(
        'openai', 'mock', 'https://example.invalid/v1/chat/completions', ''))
    dispatched = []

    async def dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))
        return True

    monkeypatch.setattr(generation_routes, '_start_task', dispatch)
    yield Starlette(routes=generation_routes.generation_routes()), store, dispatched
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admission_rejects_wrong_agent_project_and_conflicting_generation(hosted_api):
    app, store, dispatched = hosted_api
    run, _ = store.begin('local', {'text': 'Active task'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url='http://test') as client:
        endpoint = '/api/agents/chat'
        for payload, expected in [
            ({'text': 'Question', 'agent_id': []}, 400),
            ({'text': 'Question', 'agent_id': 'missing-agent'}, 404),
            ({'text': 'Question', 'projectId': ['bad']}, 400),
            ({'text': 'Question', 'chatProjectId': ['bad']}, 400),
            ({'text': 'Question', 'projectId': 'missing-project'}, 404),
            ({'text': 'Question', 'clientRequestId': 3}, 400),
            ({'text': 'Question', 'conversationId': 'missing-conversation'}, 404),
            ({'text': 'Next task', 'conversationId': run.conversation_id}, 409),
        ]:
            response = await client.post(endpoint, json=payload)
            assert response.status_code == expected, (payload, response.text)
        assert not dispatched
        assert store.get('local', run.run_id).status == 'running'


@pytest.mark.asyncio
async def test_oauth_recovery_requires_paused_action_matching_expected_identity(hosted_api):
    _, store, _ = hosted_api
    run, _ = store.begin('local', {'text': 'Authorize tool'})
    assert await generation_routes._resume_ready_oauth('local', run, frozenset(), None) is False
    question = {'actionId': 'question-1', 'payload': {'type': 'ask_user_question',
                'tool_call_id': 'call-1', 'question': {'question': 'Proceed?'}}}
    assert store.pause_for_question('local', run.run_id, question, [], '')
    paused = store.get('local', run.run_id)
    assert await generation_routes._resume_ready_oauth('local', paused, frozenset(), None) is False
    with store.database.connect() as db:
        import json

        row = db.execute('SELECT state FROM runs WHERE id=?', (run.run_id,)).fetchone()
        state = json.loads(row['state'])
        state['pendingAction']['payload'] = {'type': 'action_oauth',
            'action_id': 'act-1', 'tool_call_id': 'call-1', 'action_version': 'not-int'}
        db.execute('UPDATE runs SET state=? WHERE id=?', (json.dumps(state), run.run_id))
    assert await generation_routes._resume_ready_oauth('local', paused, frozenset(), None) is False
    assert await generation_routes._resume_ready_oauth('local', paused, frozenset(), None,
                                                        action_id='different') is False


@pytest.mark.asyncio
async def test_sse_identity_and_cursor_validation_and_closed_replay(hosted_api):
    app, store, _ = hosted_api
    run, _ = store.begin('local', {'text': 'Complete immediately'})
    assert store.finish('local', run.run_id, status='complete', text='Completed reply')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url='http://test') as client:
        url = f'/api/agents/chat/stream/{run.conversation_id}'
        for query, status in [('?generationCreatedAt=invalid', 400),
                              ('?generationCreatedAt=1', 409), ('?after=not-an-int', 400)]:
            response = await client.get(url + query)
            assert response.status_code == status, response.text
        response = await client.get(url + '?after=0')
        assert response.status_code == 200 and 'Completed reply' in response.text
        missing = await client.get('/api/agents/chat/stream/does-not-exist')
        assert missing.status_code == 404
        pending = await client.get('/api/agents/chat/active')
        assert pending.status_code == 200 and pending.json()['activeJobIds'] == []
        for payload, status in [({}, 400),
                                ({'conversationId': 'missing'}, 404),
                                ({'conversationId': run.conversation_id}, 409),
                                ({'conversationId': run.conversation_id, 'actionId': []}, 400)]:
            outcome = await client.post('/api/agents/chat/resume', json=payload)
            assert outcome.status_code == status, (payload, outcome.text)


@pytest.mark.asyncio
async def test_sse_recovery_heartbeat_when_active_generation_is_quiet(hosted_api, monkeypatch):
    _, store, _ = hosted_api
    run, _ = store.begin('local', {'text': 'Long running task'})
    monotonic = iter([0.0, 13.0, 13.0])
    monkeypatch.setattr(generation_routes.time, 'monotonic', lambda: next(monotonic, 13.0))
    last_existing = store.events('local', run.run_id)[-1][0]
    iterator = generation_routes._events('local', run, after=last_existing)
    try:
        heartbeat = await iterator.__anext__()
        assert heartbeat == b': heartbeat\n\n'
    finally:
        await iterator.aclose()


@pytest.mark.asyncio
async def test_oauth_retry_never_steals_an_inflight_graph_actor(tmp_path, monkeypatch):
    import asyncio

    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    run, _ = store.begin('local', {'text': 'Complete original OAuth action'})
    profile = ProviderConfig('openai', 'mock', 'https://example.invalid/v1/chat/completions', '')
    existing = asyncio.create_task(asyncio.sleep(60))
    generation_routes._TASKS[run.run_id] = existing
    try:
        async def timed_out(*args, **kwargs):
            raise TimeoutError('The first actor is still processing')

        with monkeypatch.context() as patch:
            patch.setattr(generation_routes.asyncio, 'wait_for', timed_out)
            assert await generation_routes._start_task(
                'local', run, profile, None,
                oauth_claim=('action-1', 'tool-call-1', 1, True),
            ) is False
        assert generation_routes._TASKS[run.run_id] is existing and not existing.done()
        # Even without OAuth re-entry, admission cannot duplicate a live task.
        assert await generation_routes._start_task('local', run, profile, None) is False
    finally:
        generation_routes._TASKS.pop(run.run_id, None)
        existing.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await existing
