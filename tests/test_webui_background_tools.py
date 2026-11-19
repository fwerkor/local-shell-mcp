"""Original ordinary tool run_in_background capability; no second native executor."""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.background_tools import (
    _TOOL_TASKS,
    check_tool_task,
    inject_tools,
    recover_background_tools,
    shutdown_background_tools,
    start_tool_task,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.fixture
def environment(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR',str(tmp_path/'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT',str(tmp_path))
    get_settings.cache_clear()
    db=SQLiteDatabase(tmp_path/'state')
    agent=AgentRepository(db).create('owner',{'name':'root','provider':'openai','model':'test',
                 'tools':['run_shell'],'tool_options':{'run_shell':{'run_in_background':True}}})
    generation,_=GenerationStore(db).begin('owner',{'text':'start tool'},agent)
    yield db,agent,generation
    get_settings.cache_clear()


@pytest.mark.parametrize('name,enabled,expected',[
    ('run_shell', True, True), ('run_shell',False,False), ('file_write',True,False),
    ('lc_transfer_to_other',True,False), ('mcp_tool_call',True,False),
    ('ask_user_question',True,False), ('session_manage',True,False),
])
def test_source_schema_opt_in_does_not_mutate_registry_or_excluded_tools(name,enabled,expected):
    original={'type':'function','function':{'name':name,
              'parameters':{'type':'object','properties':{'command':{'type':'string'}}}}}
    updated,selected=inject_tools([original],{'tool_options':{name:{'run_in_background':enabled}}},
                                  native_names=frozenset({name}))
    assert ('run_in_background' in updated[0]['function']['parameters']['properties']) is expected
    assert (name in selected) is expected
    assert 'run_in_background' not in original['function']['parameters']['properties']


def test_nonobject_and_reserved_source_tool_schema_not_modified():
    tools=[{'type':'function','function':{'name':'run_shell','parameters':{'type':'string'}}},
           {'type':'function','function':{'name':'run_shell','parameters':{
               'type':'object','properties':{'run_in_background':{'type':'string'}}}}}]
    result,selected=inject_tools(tools,{'run_in_background':True},
                                 native_names=frozenset({'run_shell'}))
    assert result==tools and not selected


@pytest.mark.asyncio
async def test_host_native_background_once_then_one_shot_poll_claim(environment):
    db,agent,generation=environment
    gate=asyncio.Event()
    calls=[]

    async def dispatch(call,scopes,grant_expires,authorization):
        calls.append((call,scopes,grant_expires,authorization))
        await gate.wait()
        return 'native shell result'

    call=ModelToolCall('native-1','run_shell',{'command':'echo hi'})
    first=json.loads(await start_tool_task(db,'owner',generation.conversation_id,
           generation.conversation_id,generation.run_id,call,
           scopes=frozenset({'shell:execute'}),grant_expires=None,dispatch=dispatch))
    again=json.loads(await start_tool_task(db,'owner',generation.conversation_id,
           generation.conversation_id,generation.run_id,call,
           scopes=frozenset({'shell:execute'}),grant_expires=None,dispatch=dispatch))
    assert first['background_task_id']==again['background_task_id']
    assert first['status']=='running'
    assert check_tool_task(db,'other',generation.conversation_id,first['background_task_id'])['status']=='not_found'
    assert len(check_tool_task(db,'owner',generation.conversation_id,None))==1
    gate.set()
    await asyncio.wait_for(_TOOL_TASKS[first['background_task_id']],5)
    assert len(calls)==1 and calls[0][3]==generation.conversation_id
    claimed=check_tool_task(db,'owner',generation.conversation_id,first['background_task_id'])
    assert claimed['result']=='native shell result' and claimed['result_claimed'] is True
    assert 'result' not in check_tool_task(db,'owner',generation.conversation_id,first['background_task_id'])
    with pytest.raises(ValueError,match='different arguments'):
        await start_tool_task(db,'owner',generation.conversation_id,generation.conversation_id,
                              generation.run_id,ModelToolCall('native-1','run_shell',{'command':'rm all'}),
                              scopes=frozenset(),grant_expires=None,dispatch=dispatch)
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_cancel_running_native_background_does_not_replay_original_call(environment):
    db,agent,generation=environment
    active=asyncio.Event()
    async def dispatch(call,scopes,grant_expires,auth):
        active.set()
        await asyncio.Event().wait()
    identity=json.loads(await start_tool_task(db,'owner',generation.conversation_id,
              generation.conversation_id,generation.run_id,
              ModelToolCall('native-cancel','run_shell',{'command':'sleep 120'}),
              scopes=frozenset(),grant_expires=None,dispatch=dispatch))['background_task_id']
    await asyncio.wait_for(active.wait(),5)
    assert check_tool_task(db,'owner',generation.conversation_id,identity,'cancel')['status']=='cancellation_requested'
    await asyncio.sleep(.05)
    assert check_tool_task(db,'owner',generation.conversation_id,identity)['status']=='cancelled'
    assert check_tool_task(db,'owner',generation.conversation_id,identity,'cancel')['status']=='not_running'
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_expired_authorization_refuses_to_run_any_native_tool(environment):
    db,agent,generation=environment
    seen=[]
    async def dispatch(*args):
        seen.append(True)
        return 'unsafe'
    identity=json.loads(await start_tool_task(db,'owner',generation.conversation_id,
              generation.conversation_id,generation.run_id,
              ModelToolCall('expired','run_shell',{'command':'echo blocked'}),
              scopes=frozenset(),grant_expires=time.time()-1,dispatch=dispatch))['background_task_id']
    await asyncio.wait_for(_TOOL_TASKS[identity],5)
    assert seen==[]
    receipt=check_tool_task(db,'owner',generation.conversation_id,identity)
    assert receipt['status']=='error' and receipt['error']=='PermissionError'
    await shutdown_background_tools()


def test_startup_recovery_never_replays_possible_irreversible_native_effect(environment):
    db,agent,generation=environment
    now=int(time.time()*1000)
    with db.connect() as conn:
        conn.execute('INSERT INTO agent_background_tools('
                     'id,owner,conversation_id,authorization_conversation_id,parent_run_id,'
                     'parent_tool_call_id,tool_name,argument_hash,status,lease_owner,lease_until,'
                     'created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     ('tooltask_old','owner',generation.conversation_id,generation.conversation_id,
                      generation.run_id,'old','run_shell','hash','running','dead-controller',now-1,now-5000,now))
        conn.execute('INSERT INTO agent_background_tools('
                     'id,owner,conversation_id,authorization_conversation_id,parent_run_id,'
                     'parent_tool_call_id,tool_name,argument_hash,status,lease_owner,lease_until,'
                     'created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     ('tooltask_live','owner',generation.conversation_id,generation.conversation_id,
                      generation.run_id,'live','run_shell','hash2','running','healthy-controller',now+30000,now-5000,now))
    assert recover_background_tools(db)==1
    assert check_tool_task(db,'owner',generation.conversation_id,'tooltask_old')['status']=='uncertain'
    assert check_tool_task(db,'owner',generation.conversation_id,'tooltask_live')['status']=='running'


@pytest.mark.asyncio
async def test_actual_agent_runner_dispatches_original_native_tool_with_stripped_param(environment,monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry
    db,agent,generation=environment
    tools=[{'type':'function','function':{'name':'run_shell','parameters':{
        'type':'object','properties':{'command':{'type':'string'}}}}}]
    monkeypatch.setattr(lsm_tool_registry,'available_tools',lambda *args,**kwargs:tools)
    monkeypatch.setattr(agent_runner,'provider_config',lambda *args: ProviderConfig(
        'openai','test','https://example.invalid',''))
    entered=asyncio.Event()
    gate=asyncio.Event()
    seen=[]
    async def native(owner,cid,call,**kwargs):
        seen.append((owner,cid,call.arguments,kwargs))
        entered.set()
        await gate.wait()
        return 'handled by native call_tool'
    monkeypatch.setattr(lsm_tool_registry,'call_tool',native)
    async def model(*args,**kwargs):
        yield 'model'
    async def quiet(text):
        pass
    runner=agent_runner.AgentRunner('owner',generation,db,GenerationStore(db),scopes=frozenset(),
                grant_expires=None,stream_tools=model,stream_text=model,on_text=quiet,agent=agent)
    context=runner._context(agent)
    definitions={tool['function']['name']:tool for tool in context.tools}
    assert 'run_in_background' in definitions['run_shell']['function']['parameters']['properties']
    assert 'check_background_task' in definitions
    state=SimpleNamespace(context=context)
    reply=json.loads(await runner._invoke(ModelToolCall('real-native','run_shell',{
        'command':'echo hi','run_in_background':True}),state))
    assert reply['status']=='running'
    await asyncio.wait_for(entered.wait(),5)
    assert seen[0][2]=={'command':'echo hi'}
    assert seen[0][1]==generation.conversation_id
    gate.set()
    await asyncio.wait_for(_TOOL_TASKS[reply['background_task_id']],5)
    receipt=json.loads(await runner._invoke(ModelToolCall('check','check_background_task',{
        'background_task_id':reply['background_task_id']}),state))
    assert receipt['result']=='handled by native call_tool'
    with pytest.raises(Exception,match='not enabled'):
        await runner._invoke(ModelToolCall('blocked','file_write',{
            'path':'file','run_in_background':True}),state)
    await shutdown_background_tools()


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [
    ModelToolCall('', 'run_shell', {'command':'x'}),
    ModelToolCall('id1', 'subagent', {'name':'child'}),
    ModelToolCall('id1', 'run_shell', 'not-an-object'),
])
async def test_invalid_or_excluded_native_calls_never_allocate_task(environment, invalid):
    db, agent, generation = environment

    async def untrusted(*args):
        raise AssertionError('Excluded calls never execute')

    with pytest.raises(ValueError, match='not eligible'):
        await start_tool_task(db, 'owner', generation.conversation_id,
                              generation.conversation_id, generation.run_id,
                              invalid, scopes=frozenset(), grant_expires=None,
                              dispatch=untrusted)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_background_tools').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_owned_parent_and_authorization_conversation_are_required(environment):
    db, agent, generation = environment

    async def no_execute(*args):
        raise AssertionError('Invalid authorization must not execute')

    call = ModelToolCall('owner-check', 'run_shell', {'command':'echo x'})
    with pytest.raises(PermissionError, match='active owned parent'):
        await start_tool_task(db, 'intruder', generation.conversation_id,
                              generation.conversation_id, generation.run_id, call,
                              scopes=frozenset(), grant_expires=None, dispatch=no_execute)
    with pytest.raises(PermissionError, match='authorization scope'):
        await start_tool_task(db, 'owner', generation.conversation_id,
                              'foreign-conversation', generation.run_id, call,
                              scopes=frozenset(), grant_expires=None, dispatch=no_execute)
    GenerationStore(db).finish('owner', generation.run_id, status='complete', text='done')
    with pytest.raises(PermissionError, match='active owned parent'):
        await start_tool_task(db, 'owner', generation.conversation_id,
                              generation.conversation_id, generation.run_id, call,
                              scopes=frozenset(), grant_expires=None, dispatch=no_execute)


@pytest.mark.asyncio
@pytest.mark.parametrize('quota', ['conversation', 'user'])
async def test_bounded_original_background_concurrency_is_fenced_in_sqlite(environment, quota):
    db, agent, generation = environment
    second, _ = GenerationStore(db).begin('owner', {'text':'another auth context'}, agent)
    original = generation.conversation_id
    other = second.conversation_id
    now = int(time.time() * 1000)
    limit = 10 if quota == 'conversation' else 40
    with db.connect() as conn:
        for i in range(limit):
            conn.execute('INSERT INTO agent_background_tools('
                         'id,owner,conversation_id,authorization_conversation_id,parent_run_id,'
                         'parent_tool_call_id,tool_name,argument_hash,status,lease_owner,lease_until,'
                         'created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (f'tooltask_quota_{quota}_{i}', 'owner', original,
                          original if quota == 'conversation' else other,
                          generation.run_id, f'quota-{i}', 'run_shell', 'stub', 'running',
                          'controller', now + 60_000, now, now))

    async def no_execute(*args):
        raise AssertionError('Concurrent quota exhausted')

    expected = 'Conversation' if quota == 'conversation' else 'User'
    with pytest.raises(PermissionError, match=expected + ' background task limit'):
        await start_tool_task(db, 'owner', original, original, generation.run_id,
                              ModelToolCall('over-quota', 'run_shell', {'command':'true'}),
                              scopes=frozenset(), grant_expires=None, dispatch=no_execute)


@pytest.mark.asyncio
async def test_claim_control_rejects_invalid_or_cross_owner_identifiers(environment):
    db, agent, generation = environment
    assert check_tool_task(db, 'owner', generation.conversation_id, 'wrong-id')['status'] == 'not_found'
    assert check_tool_task(db, 'owner', generation.conversation_id, 13)['status'] == 'not_found'
    assert check_tool_task(db, 'owner', generation.conversation_id, 'tooltask_no-such')['status'] == 'not_found'

    async def completed(*args):
        return 'result'

    identity = json.loads(await start_tool_task(
        db, 'owner', generation.conversation_id, generation.conversation_id, generation.run_id,
        ModelToolCall('control', 'run_shell', {'command':'true'}),
        scopes=frozenset(), grant_expires=None, dispatch=completed))['background_task_id']
    await asyncio.wait_for(_TOOL_TASKS[identity], 5)
    invalid = check_tool_task(db, 'owner', generation.conversation_id, identity, action='nonsense')
    assert invalid['status'] == 'invalid_control'
    assert invalid['result_available'] is True
    assert check_tool_task(db, 'other', generation.conversation_id, identity)['status'] == 'not_found'
    assert check_tool_task(db, 'owner', 'other-conversation', identity)['status'] == 'not_found'
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_cross_controller_lease_loss_marks_task_unsafe_without_duplicate_execution(environment,
                                                                                        monkeypatch):
    from local_shell_mcp.webui import background_tools

    db, agent, generation = environment
    monkeypatch.setattr(background_tools, '_HEARTBEAT_SECONDS', .015)
    started = asyncio.Event()
    executed = []

    async def native(*args):
        executed.append(True)
        started.set()
        await asyncio.Event().wait()

    identity = json.loads(await start_tool_task(db, 'owner', generation.conversation_id,
        generation.conversation_id, generation.run_id,
        ModelToolCall('revoked', 'run_shell', {'command':'sleep 5'}),
        scopes=frozenset(), grant_expires=None, dispatch=native))['background_task_id']
    await asyncio.wait_for(started.wait(), 5)
    task = _TOOL_TASKS[identity]
    with db.connect() as conn:
        conn.execute('UPDATE agent_background_tools SET lease_owner=?,lease_until=? WHERE id=?',
                     ('different-controller', int(time.time() * 1000) - 1, identity))
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
    receipt = check_tool_task(db, 'owner', generation.conversation_id, identity)
    assert receipt['status'] == 'uncertain'
    assert receipt['error'] == 'LEASE_EXPIRED_UNKNOWN_RESULT'
    assert executed == [True]
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_remote_cancel_is_persisted_and_polled_by_original_lease_owner(environment,
                                                                             monkeypatch):
    from local_shell_mcp.webui import background_tools

    db, agent, generation = environment
    monkeypatch.setattr(background_tools, '_HEARTBEAT_SECONDS', .015)
    started = asyncio.Event()

    async def native(*args):
        started.set()
        await asyncio.Event().wait()

    identity = json.loads(await start_tool_task(db, 'owner', generation.conversation_id,
        generation.conversation_id, generation.run_id,
        ModelToolCall('cross-controller', 'run_shell', {'command':'sleep 5'}),
        scopes=frozenset(), grant_expires=None, dispatch=native))['background_task_id']
    await asyncio.wait_for(started.wait(), 5)
    running = _TOOL_TASKS.pop(identity)
    # Simulate another Controller: the caller can only set the SQLite cancel intent.
    requested = check_tool_task(db, 'owner', generation.conversation_id, identity, action='cancel')
    assert requested['status'] == 'cancellation_requested'
    await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 5)
    assert check_tool_task(db, 'owner', generation.conversation_id, identity)['status'] == 'cancelled'
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_shutdown_marks_ongoing_nonidempotent_native_effect_uncertain(environment):
    db, agent, generation = environment
    started = asyncio.Event()

    async def native(*args):
        started.set()
        await asyncio.Event().wait()

    identity = json.loads(await start_tool_task(db, 'owner', generation.conversation_id,
        generation.conversation_id, generation.run_id,
        ModelToolCall('shutdown', 'run_shell', {'command':'sleep 5'}),
        scopes=frozenset(), grant_expires=None, dispatch=native))['background_task_id']
    await asyncio.wait_for(started.wait(), 5)
    await shutdown_background_tools()
    receipt = check_tool_task(db, 'owner', generation.conversation_id, identity)
    assert receipt['status'] == 'uncertain'
    assert receipt['error'] == 'INTERRUPTED_UNKNOWN_RESULT'


def test_persisted_background_result_claim_replays_exact_original_only_to_same_tool_call(environment):
    db, _, generation = environment
    now = int(time.time() * 1000)
    identity = 'tooltask_claim_replay'
    with db.connect() as conn:
        conn.execute('INSERT INTO agent_background_tools('
                     'id,owner,conversation_id,authorization_conversation_id,parent_run_id,'
                     'parent_tool_call_id,tool_name,argument_hash,status,result,created_at,updated_at) '
                     'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                     (identity, 'owner', generation.conversation_id, generation.conversation_id,
                      generation.run_id, 'original-call', 'run_shell', 'hash',
                      'completed', 'durable result', now-500, now))
    kwargs = {'claimant_run_id': generation.run_id, 'claimant_call_id': 'poll-call-one'}
    first = check_tool_task(db, 'owner', generation.conversation_id, identity, **kwargs)
    assert first['result'] == 'durable result' and first['result_claimed']
    assert check_tool_task(db, 'owner', generation.conversation_id, identity, **kwargs) == first
    different_call = check_tool_task(db, 'owner', generation.conversation_id, identity,
                                     claimant_run_id=generation.run_id, claimant_call_id='poll-call-two')
    assert 'result' not in different_call
    with db.connect() as conn:
        claim = conn.execute('SELECT claimant_run_id,claimant_call_id FROM agent_background_tool_claims '
                             'WHERE task_id=?', (identity,)).fetchone()
        assert tuple(claim) == (generation.run_id, 'poll-call-one')
