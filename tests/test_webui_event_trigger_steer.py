"""Original remote Steer uses the existing PR358 SQLite injection and SSE receipts."""
from __future__ import annotations

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    enqueue_event,
    get_event,
    mint_source_key,
    process_event_deliveries,
    revoke_source_key,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.steering import SteeringStore


@pytest.fixture
def environment(tmp_path):
    db = SQLiteDatabase(tmp_path / 'data')
    agent = AgentRepository(db).create('alice', {
        'name': 'target', 'provider': 'openai', 'model': 'test', 'tools': [],
    })
    generation, _ = GenerationStore(db).begin('alice', {'text': 'Run a task'}, agent)
    source = mint_source_key(db, 'alice', permissions=('steer',))
    return db, agent, generation, source


def send(env, *, key='event-1', preempt=True, agent_id=None, created_at=None):
    db, agent, generation, source = env
    payload = {
        'mode': 'steer',
        'event': {'id': key, 'type': 'resource.update', 'occurredAt': 1786967999000},
        'target': {'agentId': agent_id or agent['id'],
                   'conversationId': generation.conversation_id,
                   'generationCreatedAt': generation.generation_created_at if created_at is None else created_at,
                   'preempt': preempt},
        'input': 'New event detail',
    }
    return enqueue_event(db, 'alice', source['id'], key, payload)['id']


@pytest.mark.asyncio
async def test_authenticated_remote_steer_reuses_existing_fifo_and_generation_sse(environment):
    db, agent, generation, source = environment
    delivery = send(environment)
    assert await process_event_deliveries(db) == 1
    result = get_event(db, 'alice', source['id'], delivery)
    assert result['status'] == 'succeeded'
    assert result['result']['mode'] == 'steer'
    assert result['result']['status'] == 'queued'
    assert result['result']['preempt'] is True
    store = SteeringStore(db)
    queued = store.pending('alice', generation.run_id)
    assert len(queued) == 1 and queued[0]['steerId'] == result['result']['steerId']
    assert queued[0]['text'] == 'New event detail'
    applied = store.drain('alice', generation.run_id, boundary='stream')
    assert len(applied) == 1
    assert any(event.get('event') == 'on_steer_applied'
               for _, event in GenerationStore(db).events('alice', generation.run_id))
    assert await process_event_deliveries(db) == 0
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_source_steer_crash_after_fifo_commit_retries_without_duplicate_effect(environment,
                                                                                     monkeypatch):
    db, agent, generation, source = environment
    delivery = send(environment)
    actual = SteeringStore.enqueue
    seen = []

    def crash_after_commit(self, owner, body, **kwargs):
        response = actual(self, owner, body, **kwargs)
        seen.append(response['steerId'])
        if len(seen) == 1:
            raise OSError('crash after SQLite enqueue before acknowledgement')
        return response

    monkeypatch.setattr(SteeringStore, 'enqueue', crash_after_commit)
    assert await process_event_deliveries(db) == 0
    with db.connect() as conn:
        row = conn.execute('SELECT attempts,status FROM agent_event_deliveries WHERE id=?',
                           (delivery,)).fetchone()
        assert row['attempts'] == 1 and row['status'] == 'pending'
        conn.execute('UPDATE agent_event_deliveries SET available_at=0 WHERE id=?', (delivery,))
    assert await process_event_deliveries(db) == 1
    assert seen == [seen[0], seen[0]]
    assert len(SteeringStore(db).pending('alice', generation.run_id)) == 1
    assert get_event(db, 'alice', source['id'], delivery)['result']['replayed'] is True


@pytest.mark.asyncio
async def test_remote_steer_agent_or_generation_epoch_mismatch_cannot_inject(environment):
    db, agent, generation, source = environment
    foreign = AgentRepository(db).create('alice', {'name':'foreign', 'provider':'openai',
                                                    'model':'test', 'tools':[]})
    bad_agent = send(environment, key='wrong-agent', agent_id=foreign['id'])
    bad_run = send(environment, key='wrong-generation', created_at=generation.generation_created_at + 1)
    assert await process_event_deliveries(db) == 0
    with db.connect() as conn:
        for delivery in (bad_agent, bad_run):
            record = conn.execute('SELECT status FROM agent_event_deliveries WHERE id=?', (delivery,)).fetchone()
            assert record['status'] == 'dead'
    assert SteeringStore(db).pending('alice', generation.run_id) == []


@pytest.mark.asyncio
async def test_remote_steer_revoked_key_rejects_fifo_and_stays_dead(environment):
    db, agent, generation, source = environment
    delivery = send(environment)
    assert revoke_source_key(db, 'alice', source['id']) is True
    assert await process_event_deliveries(db) == 0
    assert get_event(db, 'alice', source['id'], delivery)['status'] == 'dead'
    assert SteeringStore(db).pending('alice', generation.run_id) == []
