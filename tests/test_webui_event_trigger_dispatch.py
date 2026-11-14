"""Durable external Agent Trigger fire admission through the original AgentRunner."""
from __future__ import annotations

import asyncio

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner, generation_routes, providers
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    _OWNED,
    active_event_generations,
    assert_event_lease,
    enqueue_event,
    get_event,
    mint_source_key,
    process_event_deliveries,
    shutdown_event_workers,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    agent = AgentRepository(db).create('alice', {'name': 'Remote event handler', 'provider': 'openai',
                                                  'model': 'remote-test', 'tools': []})
    source = mint_source_key(db, 'alice', permissions=('fire',))
    monkeypatch.setattr(providers, 'provider_config', lambda *args: ProviderConfig(
        'openai', 'remote-test', 'https://example.invalid', ''))
    monkeypatch.setattr(agent_runner, 'provider_config', providers.provider_config)
    yield db, agent, source
    get_settings.cache_clear()


def send(db, agent, source, *, event='one', lane=None):
    payload = {'mode': 'fire', 'event': {'id': event, 'type': 'resource.ready',
               'occurredAt': 1786967999000}, 'target': {'agentId': agent['id']}, 'input': 'Do research ' + event}
    if lane:
        payload['orderingKey'] = lane
    return enqueue_event(db, 'alice', source['id'], 'stable-id-' + event, payload)['id']


@pytest.mark.asyncio
async def test_external_fire_exactly_one_new_generation_and_claim_token_on_crash_replay(environment):
    db, agent, source = environment
    first = send(db, agent, source)
    captured = []

    async def dispatch(owner, generation, profile, agent_config, **kwargs):
        captured.append((generation, kwargs['event_delivery_lease']))

    assert await process_event_deliveries(db, dispatch=dispatch) == 1
    assert len(captured) == 1
    generation, (key, token) = captured[0]
    assert key == first
    assert_event_lease(db, 'alice', generation.run_id, (key, token))
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 1
        assert conn.execute('SELECT status FROM agent_event_deliveries').fetchone()[0] == 'leased'
    assert generation.run_id in active_event_generations(db)
    with db.connect() as conn:
        conn.execute('UPDATE agent_event_deliveries SET lease_until=0 WHERE id=?', (first,))
    assert await process_event_deliveries(db, dispatch=dispatch) == 1
    assert len(captured) == 2
    assert captured[0][0].run_id == captured[1][0].run_id
    assert captured[0][1] != captured[1][1]
    with pytest.raises(Exception, match='lease'):
        assert_event_lease(db, 'alice', generation.run_id, captured[0][1])
    assert_event_lease(db, 'alice', generation.run_id, captured[1][1])
    assert GenerationStore(db).latest('alice', generation.conversation_id).run_id == generation.run_id
    assert get_event(db, 'alice', source['id'], first)['result']['mode'] == 'fire'
    _OWNED.clear()
    await shutdown_event_workers()


@pytest.mark.asyncio
async def test_default_external_fire_uses_real_agent_runner_and_persists_response_and_sse(environment,
                                                                                         monkeypatch):
    db, agent, source = environment
    key = send(db, agent, source)
    seen = []

    async def model(profile, history, **kwargs):
        seen.append(history)
        yield 'I handled the authenticated remote event.'

    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    monkeypatch.setattr(generation_routes, 'stream_model', model)
    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', model)
    assert await process_event_deliveries(db) == 1
    with db.connect() as conn:
        run_id = conn.execute('SELECT run_id FROM agent_event_deliveries WHERE id=?', (key,)).fetchone()[0]
    assert run_id
    task = generation_routes._TASKS.get(run_id)
    assert task is not None
    await asyncio.wait_for(task, 10)
    assert GenerationStore(db).get('alice', run_id).status == 'complete'
    assert seen and any('Do research one' in message.get('content', '')
                        for history in seen for message in history)
    assert await process_event_deliveries(db) == 0
    delivery = get_event(db, 'alice', source['id'], key)
    assert delivery['status'] == 'succeeded'
    assert delivery['result']['mode'] == 'fire'
    with db.connect() as conn:
        answer = conn.execute('SELECT text FROM messages WHERE id=?',
                              (GenerationStore(db).get('alice', run_id).response_message_id,)).fetchone()
        assert answer['text'] == 'I handled the authenticated remote event.'
    assert any(event.get('event') == 'on_run_step' for _, event in GenerationStore(db).events('alice', run_id))
    await shutdown_event_workers()


@pytest.mark.asyncio
async def test_one_event_lane_does_not_overtake_its_pending_predecessor(environment):
    db, agent, source = environment
    one = send(db, agent, source, event='a', lane='resource-A')
    two = send(db, agent, source, event='b', lane='resource-A')
    other = send(db, agent, source, event='c', lane='resource-B')
    accepted = []

    async def dispatch(owner, generation, *args, **kwargs):
        accepted.append(generation)

    assert await process_event_deliveries(db, dispatch=dispatch) == 2
    with db.connect() as conn:
        records = {r['id']: r['status'] for r in conn.execute('SELECT id,status FROM agent_event_deliveries')}
        assert records[one] == 'leased' and records[two] == 'pending' and records[other] == 'leased'
        first_run = conn.execute('SELECT run_id FROM agent_event_deliveries WHERE id=?', (one,)).fetchone()[0]
    GenerationStore(db).finish('alice', first_run, status='complete', text='done')
    value = await process_event_deliveries(db, dispatch=dispatch)
    with db.connect() as conn:
        proof = [dict(row) for row in conn.execute('SELECT seq,id,status,available_at,lease_owner,run_id,error_type FROM agent_event_deliveries ORDER BY seq')]
    assert value == 1, proof
    with db.connect() as conn:
        assert conn.execute('SELECT status FROM agent_event_deliveries WHERE id=?', (one,)).fetchone()[0] == 'succeeded'
        assert conn.execute('SELECT status FROM agent_event_deliveries WHERE id=?', (two,)).fetchone()[0] == 'leased'
    assert len(accepted) == 3
    _OWNED.clear()
    await shutdown_event_workers()
