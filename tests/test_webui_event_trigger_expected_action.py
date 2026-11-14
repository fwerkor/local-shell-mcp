"""Exact original tool action matcher and end-to-end host-observed evidence gate."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner, providers
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    _NO_PARENT,
    enqueue_event,
    get_event,
    matches_expected_action,
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
    child=repo.create('alice',{'name':'action-child','provider':'openai','model':'test','tools':[]})
    parent=repo.create('alice',{'name':'parent','provider':'openai','model':'test','tools':[],
                                'subagents':{'enabled':True,'agent_ids':[child['id']]}})
    run,_=GenerationStore(db).begin('alice',{'text':'delegate'},parent)
    GenerationStore(db).finish('alice',run.run_id,status='complete',text='delegated')
    source=mint_source_key(db,'alice',permissions=('continue',))
    binding=register_bound_child(db,'alice',source['id'],'action-bind',actor_id='action',
                                  parent_conversation_id=run.conversation_id,
                                  parent_message_id=run.response_message_id,target_agent_id=child['id'])
    monkeypatch.setattr(providers,'provider_config',lambda *args: ProviderConfig(
        'openai','test','https://example.invalid',''))
    monkeypatch.setattr(agent_runner,'provider_config',providers.provider_config)
    return db,child,source,binding


def submit(env, *, expected=None, key='one', coalesce=False):
    db,child,source,binding=env
    body={'mode':'continue','event':{'id':key,'type':'repo.updated','occurredAt':123},
          'target':{'agentId':child['id'],'conversationId':binding['threadId'],
                    'parentMessageId':_NO_PARENT,'bindingId':binding['id']},
          'input':'Apply the requested change'}
    if expected is not None:
        body['expectedAction']=expected
    if coalesce:
        body['coalesce']={'key':'not-allowed'}
    return enqueue_event(db,'alice',source['id'],'action-'+key,body)['id']


@pytest.mark.asyncio
async def test_actual_completed_tool_callback_proves_source_expected_action(environment):
    db,child,source,binding=environment
    delivery=submit(environment,expected={'toolName':'file_write',
                                          'argumentSubset':{'path':'src/main.py'}})
    seen=[]
    async def dispatch(owner,run,*args,**kwargs):
        seen.append(run)
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    run=seen[0]
    GenerationStore(db).append('alice',run.run_id,{
        'event':'on_run_step_completed','data':{'result':{'id':'step_tool', 'type':'tool_call',
            'tool_call':{'id':'call-1','name':'file_write',
                         'args':{'path':'src/main.py','content':'real contents'},
                         'output':'file saved'}}}},
    )
    GenerationStore(db).finish('alice',run.run_id,status='complete',text='All done')
    assert await process_event_deliveries(db,dispatch=dispatch)==0
    assert get_event(db,'alice',source['id'],delivery)['status']=='succeeded'


@pytest.mark.asyncio
async def test_model_prose_cannot_substitute_missing_tool_execution_proof(environment):
    db,child,source,binding=environment
    delivery=submit(environment,expected={'toolName':'file_write'})
    seen=[]
    async def dispatch(owner,run,*args,**kwargs):
        seen.append(run)
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    GenerationStore(db).finish('alice',seen[0].run_id,status='complete',
                               text='I wrote the file successfully (only model prose).')
    assert await process_event_deliveries(db,dispatch=dispatch)==0
    status=get_event(db,'alice',source['id'],delivery)
    assert status['status']=='dead'
    assert status['error']['code']=='EXPECTED_ACTION_NOT_OBSERVED'


@pytest.mark.asyncio
async def test_failed_tool_callback_cannot_be_counted_as_proof(environment):
    db,child,source,binding=environment
    delivery=submit(environment,expected={'toolName':'file_write'})
    seen=[]
    async def dispatch(owner,run,*args,**kwargs):
        seen.append(run)
    assert await process_event_deliveries(db,dispatch=dispatch)==1
    GenerationStore(db).append('alice',seen[0].run_id,{
        'event':'on_run_step_completed','data':{'result':{'id':'step_failed','type':'tool_call','tool_call':{
            'name':'file_write','args':{},'output':'Tool failed (PermissionError)'}}}},
    )
    GenerationStore(db).finish('alice',seen[0].run_id,status='complete',text='Failed')
    assert await process_event_deliveries(db,dispatch=dispatch)==0
    assert get_event(db,'alice',source['id'],delivery)['status']=='dead'


def test_expected_actions_cannot_be_attached_to_fire_or_coalesced(environment):
    db,child,source,binding=environment
    expected={'toolName':'file_write'}
    with pytest.raises(ValueError,match='coalesced'):
        submit(environment,expected=expected,coalesce=True)
    with pytest.raises(ValueError,match='object'):
        submit(environment,expected={'toolName':'file_write','argumentSubset':['wrong']})


def test_original_expected_action_matcher_exact_bun_source_differential():
    original=Path(__file__).parent/'fixtures/librechat/original_agent_triggers'
    path='packages/api/src/agents/triggers/expectedAction.ts'
    info=json.loads((Path(__file__).parent.parent/'ui/workspace/UPSTREAM_LOCK.json').read_text())
    lock=next(i for i in info['modules'] if i['repository']=='LibreChat' and i['path']==path)
    assert hashlib.sha256((original/'triggers/expectedAction.ts').read_bytes()).hexdigest()==lock['sha256']
    bun=shutil.which('bun')
    if bun is None:
        if os.environ.get('LSM_REQUIRE_SOURCE_ORACLES')=='1':
            pytest.fail('Pinned source Bun expectedAction differential is required')
        pytest.skip('Bun unavailable outside source CI')
    cases=[
        ({'toolName':'file_write','arguments':{'path':'a','flags':[1,2,3]}},
         {'toolName':'file_write','argumentSubset':{'flags':[1,2,3]}}),
        ({'toolName':'file_write','arguments':'{"path":"a","nested":{"count":2,"ok":true}}'},
         {'toolName':'file_write','argumentSubset':{'nested':{'ok':True}}}),
        ({'toolName':'file_write','arguments':{'flags':[1,2,3]}},
         {'toolName':'file_write','argumentSubset':{'flags':[1,2]}}),
        ({'toolName':'file_write','arguments':{'count':1}},
         {'toolName':'file_write','argumentSubset':{'count':True}}),
        ({'toolName':'search_mcp_foo','arguments':{}},{'toolName':'search'}),
        ({'toolName':'search_mcp_foo','arguments':{}},{'toolName':'search_other'}),
        ({'toolName':'search','arguments':'not-json'},{'toolName':'search','argumentSubset':{}}),
        ({'toolName':'search','arguments':None},{'toolName':'search','argumentSubset':{}}),
    ]
    proc=subprocess.run([bun,str(original/'expected_action_oracle.mjs')],
                         input=json.dumps(cases),text=True,encoding='utf-8',errors='replace',
                         capture_output=True,check=True,timeout=20)
    expected=json.loads(proc.stdout)
    assert [matches_expected_action(evidence,action) for evidence,action in cases]==expected
