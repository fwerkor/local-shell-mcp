"""External source delivery durable errors, revocation and cross-Controller resume."""
from __future__ import annotations

import asyncio

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner, providers
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    _OWNED,
    _WORKERS,
    active_event_generations,
    assert_event_lease,
    enqueue_event,
    get_event,
    mint_source_key,
    process_event_deliveries,
    revoke_source_key,
    shutdown_event_workers,
    start_event_worker,
)
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture
def environment(tmp_path,monkeypatch):
    db = SQLiteDatabase(tmp_path/'data')
    agent = AgentRepository(db).create('alice',{'name':'root','provider':'openai',
                                                'model':'example','tools':[]})
    key = mint_source_key(db,'alice', permissions=('fire',))
    monkeypatch.setattr(providers,'provider_config',lambda *args: ProviderConfig(
        'openai','example','https://example.invalid',''))
    monkeypatch.setattr(agent_runner,'provider_config',providers.provider_config)
    yield db,agent,key
    _OWNED.clear()


def event(agent,id):
    return {'mode':'fire','event':{'id':id,'type':'resource.ready','occurredAt':123},
            'target':{'agentId':agent['id']},'input':'Research '+id}


def send(env,id='a'):
    db,agent,key=env
    return enqueue_event(db,'alice',key['id'],'idempotency-'+id,event(agent,id))['id']


@pytest.mark.asyncio
async def test_source_revocation_invalidates_existing_running_actor_and_queued_work(environment):
    db,agent,key=environment
    first=send(environment,'first')
    second=send(environment,'second')
    seen=[]
    async def dispatch(owner,generation,profile,agent,**kwargs):
        seen.append((generation,kwargs['event_delivery_lease']))
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    # Same source/agent/mode lane is serialized by the original contract.
    assert all(item[0].run_id in active_event_generations(db) for item in seen)
    assert revoke_source_key(db,'alice',key['id']) is True
    assert await process_event_deliveries(db,dispatch=dispatch)==0
    for generation,lease in seen:
        with pytest.raises(Exception,match='lease'):
            assert_event_lease(db,'alice',generation.run_id,lease)
    for identity in (first,second):
        assert get_event(db,'alice',key['id'],identity)['error']['code']=='SOURCE_REVOKED'
    await shutdown_event_workers()


@pytest.mark.asyncio
async def test_expired_source_and_removed_agent_dead_letter_without_running_provider(environment):
    db,agent,key=environment
    source=send(environment,'expired')
    with db.connect() as conn:
        conn.execute('UPDATE agent_event_source_keys SET expires_at=0 WHERE id=?',(key['id'],))
    async def unexpected(*args,**kwargs):
        raise AssertionError('revoked event cannot dispatch model')
    assert await process_event_deliveries(db,dispatch=unexpected)==0
    assert get_event(db,'alice',key['id'],source)['error']['code']=='SOURCE_REVOKED'
    fresh_key=mint_source_key(db,'alice',permissions=('fire',))
    missing=enqueue_event(db,'alice',fresh_key['id'],'gone',event(agent,'gone'))['id']
    assert AgentRepository(db).delete('alice',agent['id'])
    assert await process_event_deliveries(db,dispatch=unexpected)==0
    assert get_event(db,'alice',fresh_key['id'],missing)['error']['code']=='AGENT_NOT_FOUND'
    await shutdown_event_workers()


@pytest.mark.asyncio
async def test_source_provider_creation_failure_is_idempotently_retried_after_admission(environment,monkeypatch):
    db,agent,key=environment
    source=send(environment)
    first=[True]
    def sometimes_provider(*args):
        if first[0]:
            first[0]=False
            raise RuntimeError('temporary provider unavailable')
        return ProviderConfig('openai','example','https://example.invalid','')
    monkeypatch.setattr(providers,'provider_config',sometimes_provider)
    admitted=[]
    async def dispatch(owner,generation,profile,agent,**kwargs):
        admitted.append(generation)
    assert await process_event_deliveries(db,dispatch=dispatch)==0
    assert get_event(db,'alice',key['id'],source)['status']=='pending'
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==1
        conn.execute('UPDATE agent_event_deliveries SET available_at=0 WHERE id=?',(source,))
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    assert len(admitted)==1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==1
        saved=conn.execute('SELECT attempts,run_id FROM agent_event_deliveries WHERE id=?',
                           (source,)).fetchone()
        assert saved['attempts']==1 and saved['run_id']==admitted[0].run_id
    await shutdown_event_workers()


@pytest.mark.asyncio
async def test_original_source_retry_reuses_same_root_and_dead_letters_after_eight_failures(environment):
    db,agent,key=environment
    source=send(environment)
    generations=[]
    async def dispatch(owner,generation,*args,**kwargs):
        generations.append(generation.run_id)
        raise OSError('transient scheduler failure should never leak')
    for attempt in range(1,9):
        assert await process_event_deliveries(db,dispatch=dispatch)==0
        status=get_event(db,'alice',key['id'],source)
        assert status['attempts']==attempt
        assert status['status']==('dead' if attempt==8 else 'pending')
        assert 'transient scheduler failure' not in str(status)
        with db.connect() as conn:
            conn.execute('UPDATE agent_event_deliveries SET available_at=0 WHERE id=?',(source,))
    assert len(set(generations))==1
    assert len(generations)==8
    assert get_event(db,'alice',key['id'],source)['error']['code']=='DELIVERY_FAILED'
    await shutdown_event_workers()


@pytest.mark.asyncio
async def test_two_controller_workers_race_to_claim_same_enqueued_delivery_once(environment):
    db,agent,key=environment
    send(environment)
    seen=[]
    async def dispatch(owner,generation,*args,**kwargs):
        seen.append(generation.run_id)
    results=await asyncio.gather(process_event_deliveries(db,dispatch=dispatch),
                                 process_event_deliveries(db,dispatch=dispatch))
    assert sum(results)==1 and len(seen)==1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==1
    await shutdown_event_workers()


@pytest.mark.asyncio
async def test_event_worker_singleton_and_stop(environment,monkeypatch):
    from local_shell_mcp.webui import event_triggers
    db,agent,key=environment
    monkeypatch.setattr(event_triggers,'process_event_deliveries',lambda *args,**kwargs: asyncio.sleep(0))
    await start_event_worker(db)
    worker=_WORKERS[str(db.path)]
    await start_event_worker(db)
    assert _WORKERS[str(db.path)] is worker and not worker.done()
    await shutdown_event_workers()
    assert not _WORKERS and worker.done()
