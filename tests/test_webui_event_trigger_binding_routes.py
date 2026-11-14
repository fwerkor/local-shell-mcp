"""Authenticated HTTP bound Event Actor ingress and source-protected target override."""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.auth import AuthMiddleware
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_trigger_routes import event_trigger_routes
from local_shell_mcp.webui.event_triggers import _NO_PARENT
from local_shell_mcp.webui.generations import GenerationStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    monkeypatch.setenv('LOCAL_SHELL_MCP_UI_ENABLED', 'true')
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_BACKEND', 'sqlite')
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    db = shared_database(get_settings().state_dir.resolve())
    repo = AgentRepository(db)
    child = repo.create('anonymous', {'name': 'child', 'provider': 'openai', 'model': 'test', 'tools': []})
    parent = repo.create('anonymous', {'name': 'parent', 'provider': 'openai', 'model': 'test',
                                       'tools': [], 'subagents': {'enabled': True,
                                                                  'agent_ids':[child['id']]}})
    run, _ = GenerationStore(db).begin('anonymous', {'text': 'Delegate event analysis'}, parent)
    GenerationStore(db).finish('anonymous', run.run_id, status='complete', text='Delegated')
    yield AuthMiddleware(Starlette(routes=event_trigger_routes())), db, parent, child, run
    get_settings.cache_clear()




@pytest.mark.asyncio
async def test_binding_requires_real_child_guard_and_stable_owner_thread(setup, monkeypatch):
    app, db, parent, child, root = setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                  base_url='http://localhost') as client:
        key = (await client.post('/api/agents/v1/event-source-keys',
                                 json={'permissions':['continue']})).json()
        auth = {'Authorization':'Bearer '+key['token'], 'Idempotency-Key':'actor-registration'}
        register = {'actorId':'actor-1', 'parentConversationId':root.conversation_id,
                    'parentMessageId':root.response_message_id,
                    'target':{'agentId':child['id']}}
        from local_shell_mcp.webui.child_thread_activity import ActiveChildThreads

        original = ActiveChildThreads.reserve_for_completed_parent
        monkeypatch.setattr(ActiveChildThreads, 'reserve_for_completed_parent', None)
        missing_guard = await client.post('/api/agents/v1/events/bindings', json=register,
                                          headers=auth)
        assert missing_guard.status_code == 503
        with db.connect() as conn:
            assert conn.execute('SELECT count(*) FROM agent_event_bindings').fetchone()[0] == 0
        monkeypatch.setattr(ActiveChildThreads, 'reserve_for_completed_parent', original)
        created = await client.post('/api/agents/v1/events/bindings', json=register, headers=auth)
        assert created.status_code == 201, created.text
        binding = created.json()
        assert binding['agentId'] == child['id']
        replay = await client.post('/api/agents/v1/events/bindings', json=register, headers=auth)
        assert replay.status_code == 201 and replay.json() == binding
        turn = {'mode':'continue', 'bindingId':binding['id'],
                'target':{'agentId':parent['id'], 'conversationId':'victim',
                          'parentMessageId':'forged'},
                'event':{'id':'game-7','type':'chess.turn.ready','occurredAt':1786968000000},
                'input':'Play a legal move'}
        delivered = await client.post('/api/agents/v1/events', json=turn,
                                      headers={**auth,'Idempotency-Key':'game-7'})
        assert delivered.status_code == 202, delivered.text
        with db.connect() as conn:
            record = conn.execute('SELECT envelope FROM agent_event_deliveries WHERE id=?',
                                  (delivered.json()['id'],)).fetchone()
            import json
            source = json.loads(record['envelope'])
            assert source['target'] == {'agentId':child['id'], 'conversationId':binding['threadId'],
                                        'parentMessageId':_NO_PARENT,
                                        'bindingId':binding['id'], 'sourceKeyId':key['id']}
        cross_source = (await client.post('/api/agents/v1/event-source-keys',
                                          json={'permissions':['continue']})).json()
        denied = await client.post('/api/agents/v1/events', json=turn,
                                   headers={'Authorization':'Bearer '+cross_source['token'],
                                            'Idempotency-Key':'game-8'})
        assert denied.status_code == 403
        denied = await client.post('/api/agents/v1/events', json={**turn,'bindingId':'bad'},
                                   headers={**auth,'Idempotency-Key':'game-9'})
        assert denied.status_code == 400
