"""Actual ASGI remote Agent event source auth, keys, replay and visibility."""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.auth import AuthMiddleware
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_trigger_routes import event_trigger_routes
from local_shell_mcp.webui.event_triggers import validate_source_key


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    monkeypatch.setenv('LOCAL_SHELL_MCP_UI_ENABLED', 'true')
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_BACKEND', 'sqlite')
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    from local_shell_mcp.sqlite_store import shared_database

    db = shared_database(get_settings().state_dir.resolve())
    agent = AgentRepository(db).create('anonymous', {'name': 'Event Agent', 'provider': 'openai',
                                                  'model': 'test-model', 'tools': []})
    app = AuthMiddleware(Starlette(routes=event_trigger_routes()))
    yield app, db, agent
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_authenticated_remote_source_ingress_and_owner_scoped_status(configured):
    app, db, agent = configured
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
        admin = await client.post('/api/agents/v1/event-source-keys', json={'label': 'resources',
                                                                            'permissions': ['fire']})
        assert admin.status_code == 201, admin.text
        key = admin.json()
        assert key['token'].startswith('lsm_evt_')
        assert key['token'] not in (await client.get('/api/agents/v1/event-source-keys')).text
        assert validate_source_key(db, key['token']) is not None
        payload = {'mode': 'fire', 'event': {'id': 'resource-ready-1', 'type': 'resource.ready',
                   'occurredAt': 1786967999000, 'source': {'id': 'forged'}},
                   'target': {'agentId': agent['id']}, 'input': 'Please inspect this resource'}
        endpoint = '/api/agents/v1/events'
        assert (await client.post(endpoint, json=payload)).status_code == 401
        assert (await client.post(endpoint, json=payload, headers={'Authorization':'Bearer oauth-invalid'})).status_code == 401
        source = {'Authorization': 'Bearer ' + key['token'], 'Idempotency-Key': 'resource-1'}
        created = await client.post(endpoint, json=payload, headers=source)
        assert created.status_code == 202, created.text
        ref = created.json()['id']
        assert ref.startswith('trigger_') and len(ref) == 72
        assert created.headers['Location'] == endpoint + '/' + ref
        replay = await client.post(endpoint, json=payload, headers=source)
        assert replay.status_code == 202 and replay.json()['replayed'] is True
        lookup = await client.get(endpoint + '/' + ref, headers=source)
        assert lookup.status_code == 200 and lookup.json()['status'] == 'pending'
        assert 'input' not in lookup.text and 'resource-ready-1' not in lookup.text
        assert (await client.get(endpoint + '/' + ref)).status_code == 401
        assert (await client.delete('/api/agents/v1/event-source-keys/' + key['id'])).status_code == 200
        assert (await client.get(endpoint + '/' + ref, headers=source)).status_code == 401
        assert (await client.post(endpoint, json=payload, headers=source)).status_code == 401


@pytest.mark.asyncio
async def test_source_rejects_duplicate_headers_and_different_event_payload(configured):
    app, db, agent = configured
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
        admin = await client.post('/api/agents/v1/event-source-keys', json={'permissions': ['fire']})
        key = admin.json()
        headers = {'Authorization': 'Bearer '+key['token'], 'Idempotency-Key': 'idempotent-1'}
        payload = {'mode':'fire','event':{'id':'one','type':'new','occurredAt':123},
                   'target':{'agentId':agent['id']},'input':'hello'}
        assert (await client.post('/api/agents/v1/events', json=payload, headers=headers)).status_code == 202
        assert (await client.post('/api/agents/v1/events', json={**payload,'input':'changed'},
                                  headers=headers)).status_code == 409
        repeated = [(b'authorization', b'Bearer '+key['token'].encode()),
                    (b'idempotency-key', b'idempotent-1'),
                    (b'idempotency-key', b'idempotent-1')]
        assert (await client.post('/api/agents/v1/events', json=payload, headers=repeated)).status_code == 400
        assert (await client.post('/api/agents/v1/events', json=payload,
                                  headers={'Authorization': 'Bearer '+key['token']})).status_code == 400
        assert (await client.post('/api/agents/v1/events', json={**payload,'mode':'continue'},
                                  headers={'Authorization': 'Bearer '+key['token'],
                                           'Idempotency-Key':'not-bound'})).status_code == 400
