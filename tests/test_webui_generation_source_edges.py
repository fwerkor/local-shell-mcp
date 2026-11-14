"""Missing HTTP/stream branch contracts of pinned LibreChat generation routes.

Use the real SQLite lease, identity, and pause stores. A parked executor makes
error paths deterministic without launching any outside model process.
"""
from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes as routes
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    monkeypatch.setattr(routes, '_owner', lambda _request: 'local')
    monkeypatch.setattr(routes, '_database', lambda: db)
    monkeypatch.setattr(routes, '_generation_store', lambda: store)
    profile = ProviderConfig('openai', 'test-model', 'http://127.0.0.1:11434/v1/chat/completions', '')
    monkeypatch.setattr(routes, 'provider_config', lambda *_: profile)
    started = []

    async def park(*args, **kwargs):
        started.append((args, kwargs))

    monkeypatch.setattr(routes, '_start_task', park)
    app = Starlette(routes=routes.generation_routes())
    yield db, store, profile, started, app
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_source_generation_start_project_alias_agent_and_idempotent_conflict(context, monkeypatch):
    db, store, profile, started, app = context
    repo = WorkspaceRepository(db)
    from local_shell_mcp.webui import machine_permissions

    seen = []
    monkeypatch.setattr(machine_permissions, 'resolve_access',
                        lambda owner, conversation_id=None, *, project_id=None: seen.append((conversation_id, project_id)) or {})
    agent = AgentRepository(db).create('local', {'name': 'Test Agent', 'provider': 'openAI', 'model': 'test-model'})
    project_id = repo.create_project('local', 'Selected project')['id']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/api/agents/chat/openAI', json={
            'text': 'Hello', 'agent_id': agent['id'], 'chatProjectId': project_id,
            'clientRequestId': 'dedup-start', 'generationProtocolVersion': 2})
        assert result.status_code == 202, result.text
        cid = result.json()['conversationId']
        assert seen[-1] == (None, project_id)
        assert len(started) == 1 and started[0][0][3]['id'] == agent['id']
        assert started[0][1]['ask_user_enabled'] is False
        again = await client.post('/api/agents/chat/openAI', json={
            'text': 'Hello', 'agent_id': agent['id'], 'chatProjectId': project_id,
            'clientRequestId': 'dedup-start', 'generationProtocolVersion': 2})
        assert again.status_code == 202 and again.json()['status'] == 'resumed'
        assert len(started) == 1
        separate = await client.post('/api/agents/chat/openAI', json={
            'text': 'new prompt', 'conversationId': cid, 'agent_id': agent['id']})
        assert separate.status_code == 409 and separate.json()['status'] == 'replaced'
        assert seen[-1] == (cid, None)
        assert (await client.post('/api/agents/chat', json={'text': 'test', 'agent_id': 12})).status_code == 400
        assert (await client.post('/api/agents/chat', json={'text': 'test', 'agent_id': 'missing'})).status_code == 404
        assert (await client.post('/api/agents/chat', json={'text': 'test', 'projectId': []})).status_code == 400
        assert (await client.post('/api/agents/chat', json={'text': 'test', 'projectId': None})).status_code == 202
    assert repo.conversation('local', cid)


@pytest.mark.asyncio
async def test_source_generation_start_translates_provider_and_database_exceptions(context, monkeypatch):
    db, store, profile, started, app = context
    from local_shell_mcp.webui import machine_permissions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        monkeypatch.setattr(machine_permissions, 'resolve_access', lambda *args, **kw: (_ for _ in ()).throw(KeyError('missing project')))
        response = await client.post('/api/agents/chat', json={'text': 'hello', 'projectId': 'missing'})
        assert response.status_code == 404
        monkeypatch.setattr(machine_permissions, 'resolve_access', lambda *args, **kw: {'local': 'write', 'outside': 'read'})
        monkeypatch.setattr(routes, '_request_grant', lambda _: (set(), None))
        response = await client.post('/api/agents/chat', json={'text': 'hello'})
        assert response.status_code == 403
        assert not store.active('local') if hasattr(store, 'active') else True
        monkeypatch.setattr(routes, '_request_grant', lambda _: ({'shell:read', 'shell:write', 'remote:use'}, None))
        response = await client.post('/api/agents/chat', json={'text': 'hello'})
        assert response.status_code == 202
        assert started[-1][1]['write_tools'] is True
        monkeypatch.setattr(machine_permissions, 'resolve_access', lambda *args, **kw: {})
        monkeypatch.setattr(routes, 'provider_config', lambda *_: (_ for _ in ()).throw(ValueError('invalid provider')))
        assert (await client.post('/api/agents/chat', json={'text': 'hello'})).status_code == 400
        monkeypatch.setattr(routes, 'provider_config', lambda *_: profile)
        monkeypatch.setattr(store, 'begin', lambda *a, **kw: (_ for _ in ()).throw(KeyError('unknown project')))
        assert (await client.post('/api/agents/chat', json={'text': 'hello'})).status_code == 404
        monkeypatch.setattr(store, 'begin', lambda *a, **kw: (_ for _ in ()).throw(ValueError('invalid payload')))
        assert (await client.post('/api/agents/chat', json={'text': 'hello'})).status_code == 400


@pytest.mark.asyncio
async def test_source_generation_stream_replay_status_and_terminal_guards(context):
    db, store, profile, started, app = context
    job, _ = store.begin('local', {'text': 'hello'})
    cid = job.conversation_id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/agents/chat/stream/missing')).status_code == 404
        assert (await client.get('/api/agents/chat/stream/' + cid, params={'generationCreatedAt': 'bad'})).status_code == 400
        assert (await client.get('/api/agents/chat/stream/' + cid, params={'generationCreatedAt': -1})).status_code == 409
        assert (await client.get('/api/agents/chat/stream/' + cid, params={'after': 'bad'})).status_code == 400
        assert (await client.get('/api/agents/chat/status/missing')).json()['active'] is False
        assert (await client.get('/api/agents/chat/status/' + cid)).json()['status'] == 'running'
        assert (await client.get('/api/agents/chat/active')).json()['activeJobIds'] == [cid]
        assert store.finish('local', job.run_id, status='complete', text='Done')
        stream = await client.get('/api/agents/chat/stream/' + cid,
                                  headers={'last-event-id': '0'},
                                  params={'generationCreatedAt': job.generation_created_at, 'after': '9999'})
        assert stream.status_code == 200
        assert '"final":true' in stream.text
        assert (await client.get('/api/agents/chat/status/' + cid)).json()['active'] is False
        assert (await client.get('/api/agents/chat/active')).json()['activeJobIds'] == []


@pytest.mark.asyncio
async def test_source_generation_abort_terminal_missing_epoch_and_task_paths(context, monkeypatch):
    db, store, profile, started, app = context
    done, _ = store.begin('local', {'text': 'closed'})
    store.finish('local', done.run_id, status='complete', text='closed')
    open_job, _ = store.begin('local', {'text': 'pending'})
    cid = open_job.conversation_id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post('/api/agents/chat/abort', json={'conversationId': 1})).status_code == 400
        assert (await client.post('/api/agents/chat/abort', json={'conversationId': 'missing'})).status_code == 404
        assert (await client.post('/api/agents/chat/abort', json={'conversationId': done.conversation_id})).status_code == 409
        assert (await client.post('/api/agents/chat/abort', json={'conversationId': cid,
                        'generationCreatedAt': -1})).status_code == 409
        response = await client.post('/api/agents/chat/abort', json={'streamId': cid})
        assert response.status_code == 200
        assert store.latest('local', cid).status == 'aborted'
        assert (await client.post('/api/agents/chat/abort', json={'conversationId': cid})).status_code == 409
    pending, _ = store.begin('local', {'text': 'cancellable'})
    event = asyncio.Event()
    async def held():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            event.set()
            raise
    task = asyncio.create_task(held())
    await asyncio.sleep(0)
    routes._TASKS[pending.run_id] = task
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.post('/api/agents/chat/abort', json={'conversationId': pending.conversation_id})
            assert result.status_code == 200
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert event.is_set()
    finally:
        routes._TASKS.pop(pending.run_id, None)


@pytest.mark.asyncio
async def test_source_generation_resume_validation_and_pending_question(context, monkeypatch):
    db, store, profile, started, app = context
    job, _ = store.begin('local', {'text': 'question'})
    pending = {'actionId': 'ask-1', 'payload': {'type': 'ask_user_question',
        'tool_call_id': 'call-1', 'question': {'question': 'Which?'}}}
    assert store.pause_for_question('local', job.run_id, pending, [], 'prior')
    cid = job.conversation_id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/api/agents/chat/resume'
        assert (await client.post(url, json={'conversationId': 'missing'})).status_code == 404
        assert (await client.post(url, json={'conversationId': 1})).status_code == 400
        assert (await client.post(url, json={'conversationId': cid})).status_code == 409
        assert (await client.post(url, json={'conversationId': cid, 'actionId': []})).status_code == 400
        assert (await client.post(url, json={'conversationId': cid, 'actionId': 'bad'})).status_code == 409
        assert (await client.post(url, json={'conversationId': cid, 'actionId': 'ask-1',
            'generationCreatedAt': -1, 'answer': 'x'})).status_code == 409
        assert (await client.post(url, json={'conversationId': cid, 'actionId': 'ask-1', 'answer': ''})).status_code == 400
        result = await client.post(url, json={'conversationId': cid, 'actionId': 'ask-1', 'answer': 'yes'})
        assert result.status_code == 200, result.text
        assert started and started[-1][1]['partial_text'] == 'prior'
        assert started[-1][1]['resume_history'][-1]['tool_call_id'] == 'call-1'
        assert (await client.post(url, json={'conversationId': cid, 'actionId': 'ask-1', 'answer': 'again'})).status_code == 409
        assert (await client.post(url, json={'conversationId': cid})).status_code == 200


@pytest.mark.asyncio
async def test_source_generation_native_auth_mode_and_task_cleanup(context, monkeypatch):
    from local_shell_mcp import settings as settings_module
    from local_shell_mcp.webui import machine_permissions

    db, store, profile, started, app = context
    settings = settings_module.Settings(auth_mode='oauth', state_dir=db.root, workspace_root=db.root)
    monkeypatch.setattr(settings_module, 'get_settings', lambda: settings)
    assert routes._request_grant(SimpleNamespace(state=SimpleNamespace())) == (set(), None)
    subject = SimpleNamespace(claims={'scope': 'shell:read', 'exp': 123456})
    scopes, expiry = routes._request_grant(SimpleNamespace(state=SimpleNamespace(principal=subject)))
    assert expiry == 123456
    assert isinstance(scopes, set)
    monkeypatch.setattr(routes, '_request_grant', lambda _: (set(), None))
    monkeypatch.setattr(machine_permissions, 'resolve_access', lambda *args, **kw: {})
    assert routes._generator_headers(1)['X-LibreChat-Generation-Protocol'] == '1'
    assert routes._generation_body(store.begin('local', {'text': 'one'})[0], protocol_version=1)['generationProtocolVersion'] == 1


@pytest.mark.asyncio
async def test_source_generation_stream_event_terminal_and_heartbeat(context, monkeypatch):
    db, store, profile, started, app = context
    job, _ = store.begin('local', {'text': 'stream'})
    store.append('local', job.run_id, {'event': 'on_run_step', 'data': {'id': 'step'}})
    assert store.finish('local', job.run_id, status='complete', text='done')
    frames = []
    async for value in routes._events('local', job):
        frames.append(value)
    assert len(frames) >= 2 and all(value.startswith(b'id: ') for value in frames)
    assert b'on_run_step' in b''.join(frames)
    assert [v async for v in routes._events('local', job, after=frames[-1].split(b'\n', 1)[0].split(b': ')[-1] and 10**9)] == []

    # Mock monotonic elapsed time: a live run sends a heartbeat before the
    # SSE consumer reconnects. Never poll/sleep in real time.
    live, _ = store.begin('local', {'text': 'live'})
    monotonic = iter([0, 13, 13])
    monkeypatch.setattr(routes, 'time', SimpleNamespace(monotonic=lambda: next(monotonic, 13)))
    generator = routes._events('local', live)
    frames = [await asyncio.wait_for(generator.__anext__(), 2), await asyncio.wait_for(generator.__anext__(), 2)]
    assert frames[0].startswith(b'id: ') and frames[1] == b': heartbeat\n\n'
    await generator.aclose()


@pytest.mark.asyncio
async def test_source_generation_shutdown_cancels_live_tasks(context):
    waiting = asyncio.Event()
    started = asyncio.Event()

    async def block():
        started.set()
        try:
            await waiting.wait()
        except asyncio.CancelledError:
            waiting.set()
            raise

    task = asyncio.create_task(block())
    await started.wait()
    routes._TASKS['stoptest'] = task
    await routes.shutdown_generations()
    assert task.cancelled() and waiting.is_set()
    routes._TASKS.pop('stoptest', None)
