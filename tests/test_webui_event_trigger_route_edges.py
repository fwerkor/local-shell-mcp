"""Real ASGI error status and entitlement paths for remote Agent Trigger ingress."""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.auth import AuthMiddleware
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_trigger_routes import _event_error, event_trigger_routes


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE','none')
    monkeypatch.setenv('LOCAL_SHELL_MCP_UI_ENABLED','true')
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_BACKEND','sqlite')
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    db=shared_database(get_settings().state_dir.resolve())
    agent=AgentRepository(db).create('anonymous', {'name':'test', 'provider':'openai',
                                                   'model':'model','tools':[]})
    yield AuthMiddleware(Starlette(routes=event_trigger_routes())), agent
    get_settings.cache_clear()


async def make_key(client):
    result=await client.post('/api/agents/v1/event-source-keys', json={'permissions':['fire']})
    assert result.status_code==201
    return result.json()


def source(key, identity='same-id'):
    return {'Authorization':'Bearer '+key['token'], 'Idempotency-Key':identity}


def body(agent):
    return {'mode':'fire','event':{'id':'one','type':'ready','occurredAt':123},
            'target':{'agentId':agent['id']},'input':'Please work'}


@pytest.mark.asyncio
async def test_source_key_creation_validation_missing_revocation_and_no_leak(app):
    server,agent=app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                  base_url='http://localhost') as client:
        for bad in ({'permissions':[]}, {'permissions':'fire'}, {'permissions':[1]},
                    {'permissions':['unsafe']}, {'label':''},
                    {'expiresAt': -1}):
            assert (await client.post('/api/agents/v1/event-source-keys', json=bad)).status_code==400
        key=await make_key(client)
        assert (await client.delete('/api/agents/v1/event-source-keys/no-such-key')).status_code==404
        assert (await client.get('/api/agents/v1/event-source-keys')).status_code==200
        assert key['token'] not in (await client.get('/api/agents/v1/event-source-keys')).text


@pytest.mark.asyncio
async def test_remote_event_errors_stay_opaque_and_return_source_http_status(app):
    server,agent=app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                  base_url='http://localhost') as client:
        key=await make_key(client)
        endpoint='/api/agents/v1/events'
        headers=source(key)
        for bad in ('[]','null','invalid json'):
            assert (await client.post(endpoint,content=bad,headers=headers)).status_code==400
        for bad in ({'mode':'steer'},
                    {**body(agent),'bindingId':'abc'},
                    {**body(agent),'expectedAction':{'toolName':'destructive'}},
                    {**body(agent),'coalesce':{'key':'unsafe'}},
                    {**body(agent),'target':{'agentId':'foreign-agent'}}):
            answer=await client.post(endpoint,json=bad,headers=headers)
            assert answer.status_code in {400,403},answer.text
        import json
        nan_event = body(agent)
        nan_event['event']['occurredAt'] = float('nan')
        nan_reply = await client.post(endpoint, content=json.dumps(nan_event), headers=headers)
        assert nan_reply.status_code == 400
        assert (await client.get(endpoint+'/not-valid',headers=headers)).status_code==400
        assert (await client.get(endpoint+'/trigger_'+'a'*64,headers=headers)).status_code==404
        assert (await client.post(endpoint+'/bindings',json={},headers=headers)).status_code==400
        assert (await client.post(endpoint+'/bindings',json={'target':{}},headers=headers)).status_code in {400,404}
        too_big={**body(agent),'input':'Z'*(1024*1024+50)}
        assert (await client.post(endpoint,json=too_big,headers=headers)).status_code==413


def test_original_error_type_mapping_never_leaks_unexpected_exception():
    assert _event_error(PermissionError('no permission')).status_code==403
    assert _event_error(ValueError('Idempotency-Key was already used')).status_code==409
    assert _event_error(TypeError('bad JSON type')).status_code==400
    generic=_event_error(OSError('SECRET upstream error body'))
    assert generic.status_code==500 and 'SECRET' not in generic.detail


@pytest.mark.asyncio
async def test_plain_http_routes_do_not_accept_missing_controller_principal_even_in_noauth(app):
    from starlette.requests import Request

    from local_shell_mcp.webui.event_trigger_routes import (
        _event_auth,
    )
    server,agent=app
    with pytest.raises(Exception) as exc:
        _event_auth(Request({'type':'http','method':'GET','path':'/api/agents/v1/events',
                             'headers':[],'query_string':b'', 'state':{}}))
    assert exc.value.status_code==401
    inner=Starlette(routes=event_trigger_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=inner),
                                  base_url='http://localhost') as client:
        assert (await client.get('/api/agents/v1/event-source-keys')).status_code==403
        assert (await client.delete('/api/agents/v1/event-source-keys/missing')).status_code==403
