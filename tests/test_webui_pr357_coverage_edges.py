"""Regression tests for persisted generation admission and React reconnect edges."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.generations import GenerationStore


@pytest.fixture
def generation_api(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.state')
    store = GenerationStore(db)
    yield Starlette(routes=generation_routes.generation_routes()), store
    get_settings.cache_clear()


@pytest.mark.parametrize(('payload', 'error'), [
    ({'text': 'Task', 'clientRequestId': 9}, 'Invalid client request id'),
    ({'text': 'Task', 'clientRequestId': 'x' * 161}, 'Invalid client request id'),
    ({'text': 'Task', 'conversationId': 9}, 'Invalid conversation id'),
    ({'text': 'Task', 'projectId': []}, 'Invalid project id'),
    ({'text': 'Task', 'projectId': 'foreign-project'}, 'Project not found'),
    ({'text': 'Task', 'conversationId': 'foreign-conversation'}, 'Conversation not found'),
])
def test_generation_admission_rejects_invalid_and_foreign_ids(generation_api, payload, error):
    _, store = generation_api
    with pytest.raises((ValueError, KeyError), match=error):
        store.begin('local', payload)


@pytest.mark.asyncio
async def test_terminal_sse_reconnect_replays_final_at_sync_watermark(generation_api):
    app, store = generation_api
    run, _ = store.begin('local', {'text': 'Respond now'})
    assert store.finish('local', run.run_id, status='complete', text='Result available')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url='http://test') as client:
        url = f'/api/agents/chat/stream/{run.conversation_id}'
        resumed = await client.get(url + '?resume=true')
        assert resumed.status_code == 200
        assert '"sync":true' in resumed.text
        assert '"final":true' in resumed.text
        assert 'Result available' in resumed.text
        assert (await client.get(url + '?generationCreatedAt=-1')).status_code == 409
        assert (await client.get(url + '?generationCreatedAt=invalid')).status_code == 400
        assert (await client.get(url + '?after=not-an-integer')).status_code == 400
        repeated = await client.get(url + '?after=0')
        assert repeated.status_code == 200 and '"final":true' in repeated.text
        unknown = await client.get('/api/agents/chat/status/unknown-conversation')
        assert unknown.json()['active'] is False


@pytest.mark.asyncio
async def test_paused_generation_cannot_resume_without_human_decision(generation_api):
    app, store = generation_api
    run, _ = store.begin('local', {'text': 'Ask for approval'})
    assert store.pause_for_question('local', run.run_id,
                                    {'actionId': 'ask-one', 'payload': {'type': 'ask_user_question',
                                     'tool_call_id': 'call-one', 'question': {'question': 'Choose'}}},
                                    [], '')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url='http://test') as client:
        url = '/api/agents/chat/resume'
        paused = await client.post(url, json={'conversationId': run.conversation_id})
        assert paused.status_code == 409
        malformed = await client.post(url, json={
            'conversationId': run.conversation_id, 'actionId': []})
        assert malformed.status_code == 400
