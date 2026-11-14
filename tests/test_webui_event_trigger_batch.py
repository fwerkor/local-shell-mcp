"""Source observational bound child: 750 ms/8 events/512 KiB durable coalescing."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner, providers
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    _NO_PARENT,
    enqueue_event,
    mint_source_key,
    process_event_deliveries,
    register_bound_child,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture
def environment(tmp_path, monkeypatch):
    db=SQLiteDatabase(tmp_path/'data')
    repo=AgentRepository(db)
    child=repo.create('owner',{'name':'child','provider':'openai','model':'test','tools':[]})
    parent=repo.create('owner',{'name':'parent','provider':'openai','model':'test','tools':[],
                                'subagents':{'enabled':True,'agent_ids':[child['id']]}})
    root,_=GenerationStore(db).begin('owner',{'text':'delegate event actor'},parent)
    GenerationStore(db).finish('owner',root.run_id,status='complete',text='Authorized')
    key=mint_source_key(db,'owner',permissions=('continue',))
    binding=register_bound_child(db,'owner',key['id'],'binding-key-1',actor_id='actor',
                                  parent_conversation_id=root.conversation_id,
                                  parent_message_id=root.response_message_id,
                                  target_agent_id=child['id'])
    monkeypatch.setattr(providers,'provider_config',lambda *args: ProviderConfig(
        'openai','test','https://example.invalid',''))
    monkeypatch.setattr(agent_runner,'provider_config',providers.provider_config)
    return db,child,key,binding


def submit(env,number,*,kind='observe',batch_key='nearby',coalesce=True,ordering_key=None):
    db,child,key,binding=env
    payload={'mode':'continue', 'event':{'id':f'event-{number}','type':kind,
             'occurredAt':10000-number, 'payload':{'index':number}},
             'target':{'agentId':child['id'], 'conversationId':binding['threadId'],
                       'parentMessageId':_NO_PARENT,'bindingId':binding['id']},
             'input':f'Input #{number}'}
    if coalesce:
        payload['coalesce']={'key':batch_key}
    if ordering_key:
        payload['orderingKey']=ordering_key
    return enqueue_event(db,'owner',key['id'],f'stable-{number}',payload)['id']


@pytest.mark.asyncio
async def test_original_750ms_observational_child_batch_structured_and_receipts(environment):
    db,child,key,binding=environment
    delivery_ids=[submit(environment,i,kind='alpha' if i<2 else 'beta') for i in range(3)]
    with db.connect() as conn:
        rows=conn.execute('SELECT id,batch_root_id,batch_count,available_at FROM agent_event_deliveries '
                          'ORDER BY seq').fetchall()
        assert rows[0]['batch_count']==3
        assert all(row['batch_root_id']==delivery_ids[0] for row in rows[1:])
        assert rows[0]['available_at']>0
    assert await process_event_deliveries(db, dispatch=lambda *args,**kwargs: None)==0
    with db.connect() as conn:
        conn.execute('UPDATE agent_event_deliveries SET available_at=0 WHERE id=?',(delivery_ids[0],))
    captured=[]
    async def dispatch(owner,generation,*args,**kwargs):
        captured.append(generation)
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    assert len(captured)==1
    with db.connect() as conn:
        message=conn.execute('SELECT text FROM messages WHERE id=?',
                             (captured[0].user_message_id,)).fetchone()['text']
    batch=json.loads(message)
    assert batch['kind']=='librechat.agent_event_batch'
    assert batch['version']==1 and batch['count']==3
    assert batch['summary']['eventTypes']==[{'type':'alpha','count':2},
                                            {'type':'beta','count':1}]
    assert [event['deliveryId'] for event in batch['events']]==[
        'stable-2','stable-1','stable-0']
    GenerationStore(db).finish('owner',captured[0].run_id,status='complete',text='Processed batch')
    assert await process_event_deliveries(db,dispatch=dispatch)==0
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==2  # parent + one batch child
        assert conn.execute("SELECT count(*) FROM agent_event_deliveries WHERE status='succeeded'").fetchone()[0]==3


@pytest.mark.asyncio
async def test_batch_fills_at_eight_then_next_delivery_becomes_separate_root(environment):
    db,child,key,binding=environment
    ids=[submit(environment,i) for i in range(9)]
    with db.connect() as conn:
        roots=conn.execute('SELECT id,batch_count,batch_root_id FROM agent_event_deliveries '
                           'WHERE batch_root_id IS NULL ORDER BY seq').fetchall()
        assert [(row['id'],row['batch_count']) for row in roots]==[(ids[0],8),(ids[8],1)]
        conn.execute('UPDATE agent_event_deliveries SET available_at=0 WHERE batch_root_id IS NULL')
    dispatched=[]
    async def dispatch(owner,generation,*args,**kwargs):
        dispatched.append(generation)
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    assert len(dispatched)==1
    GenerationStore(db).finish('owner',dispatched[0].run_id,status='complete',text='Group1')
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    assert len(dispatched)==2
    assert dispatched[0].run_id!=dispatched[1].run_id


@pytest.mark.parametrize('bad', [
    {'key':''}, {'key':'a'*129}, {'key':55}, [], True,
])
def test_invalid_batch_key_never_creates_writable_child_delivery(environment,bad):
    db,child,key,binding=environment
    payload={'mode':'continue','event':{'id':'bad','type':'resource','occurredAt':1},
             'target':{'agentId':child['id'],'conversationId':binding['threadId'],
                       'parentMessageId':_NO_PARENT,'bindingId':binding['id']},
             'input':'bad batch','coalesce':bad}
    with pytest.raises(ValueError):
        enqueue_event(db,'owner',key['id'],'invalid-batch',payload)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0]==0


def test_distinct_ordering_lanes_cannot_silently_merge_same_child_event(environment):
    db,child,key,binding=environment
    submit(environment,1,ordering_key='one')
    submit(environment,2,ordering_key='two')
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries '
                            'WHERE batch_root_id IS NULL').fetchone()[0]==2
