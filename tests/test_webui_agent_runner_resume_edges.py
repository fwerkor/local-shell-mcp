"""Original durable graph Actor checkpoint/review/steer resumption boundaries."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from test_webui_agent_runner_boundaries import runner
from test_webui_agent_runner_boundaries import runner_parts as runner_parts

from local_shell_mcp.webui import agent_runner
from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
from local_shell_mcp.webui.providers import ModelToolCall


async def model(*args, **kwargs):
    yield 'resumed'


def checkpoint(obj, *, agent_id=None, pending=None, messages=None, extra=None, writes=None):
    payload = {
        'messages': messages or [{'role': 'user', 'content': 'original'}],
        'step': 1, 'model_turn': 1,
        'agent_id': agent_id,
        'pending_calls': [dict(call_id=call.call_id, name=call.name,
                               arguments=call.arguments, provider_data=call.provider_data)
                          for call in (pending or [])],
        'tool_step_started': True,
        'completed': False,
        'partial_text': 'partial',
        'handoffState': obj.route.snapshot(),
        'graph_commands': [],
        **(extra or {}),
    }
    obj.active_config = obj.saver.put(obj.active_config, {
        'id': 'source-recovered-checkpoint', 'v': 1, 'channel_values': {},
        'channel_versions': {}, 'versions_seen': {},
    }, {'source': 'test', 'step': 0})

    def fake(_config):
        return {'config': obj.active_config, 'checkpoint': {'channel_values': payload},
                'pendingWrites': writes or []}

    obj.saver.get_tuple = fake


@pytest.mark.asyncio
async def test_durable_checkpoint_with_revoked_agent_fails_before_native_replay(runner_parts):
    obj=runner(runner_parts,model)
    checkpoint(obj,agent_id='unknown-deleted-agent')
    with pytest.raises(RuntimeSafetyError,match='no longer available'):
        await obj.run([])


@pytest.mark.asyncio
async def test_durable_recovery_reuses_owned_completed_tool_result_without_invocation(runner_parts, monkeypatch):
    obj=runner(runner_parts,model)
    pending=ModelToolCall('saved-call','plan_manage',{'action':'list'})
    prior={'role':'tool','tool_call_id':'saved-call','content':'durably completed'}
    checkpoint(obj,pending=[pending],writes=[('worker','messages',prior)])
    observed=[]

    async def loop(state, **kwargs):
        observed.append((copy.deepcopy(state.pending_calls),state.messages))
        assert obj.cache
        assert next(iter(obj.cache.values()))['output']=='durably completed'
        return state.messages

    monkeypatch.setattr(agent_runner,'run_agent_loop',loop)
    obj.resume_namespace=obj.namespace
    obj.resume_history=[dict(prior)]
    result=await obj.run([{'role':'user','content':'ignored on restore'}],recursion_limit=23)
    assert len(observed)==1
    assert obj.partial_text=='partial'
    assert obj.cache and obj.active_config['configurable']['checkpoint_id']=='source-recovered-checkpoint'
    assert isinstance(result,list)


@pytest.mark.asyncio
async def test_reviewed_tool_batch_recovery_uses_same_resumed_call_and_finalizes_exactly_once(runner_parts,
                                                                                              monkeypatch):
    obj=runner(runner_parts,model)
    pending=ModelToolCall('approval-call','plan_manage',{'action':'list'})
    checkpoint(obj,pending=[pending],writes=[])
    obj.active_config=obj.saver.put(obj.active_config, {
        'id':'real-checkpoint','v':1,'channel_values':{},'channel_versions':{},'versions_seen':{},
    },{'source':'test','step':0})
    obj.saver.get_tuple=lambda _config:{
        'config':obj.active_config,
        'checkpoint':{'channel_values':{
            'messages':[{'role':'user','content':'request'}], 'step':1,'model_turn':1,
            'agent_id':None,'pending_calls':[dict(call_id=pending.call_id,name=pending.name,
                                                   arguments=pending.arguments,provider_data=None)],
            'tool_step_started':True,'completed':False,'handoffState':obj.route.snapshot(),
        }},'pendingWrites':[],
    }
    monkeypatch.setattr(obj.store,'approved_review',lambda *args:{'namespace':'','actionId':'approval-id'})
    monkeypatch.setattr(obj.store,'approved_batch',lambda *args:SimpleNamespace())
    completed=[]
    monkeypatch.setattr(obj.store,'complete_approval_batch',lambda *a,**kw:completed.append(True))
    invoked=[]

    async def invoke(call,state):
        invoked.append(call.call_id)
        return 'approved-output'

    monkeypatch.setattr(obj,'_invoke',invoke)

    async def approve(batch,*,dispatch,on_completed):
        output=await dispatch(pending)
        assert output=='approved-output'
        await on_completed(SimpleNamespace(call=pending,raw_content=None,content=output))
        assert await dispatch(pending)=='approved-output'

    monkeypatch.setattr(agent_runner,'execute_approval_batch',approve)

    async def loop(state, **kwargs):
        return state.messages

    monkeypatch.setattr(agent_runner,'run_agent_loop',loop)
    await obj.run([])
    assert invoked==['approval-call']
    assert completed==[True]
    assert len(obj.cache)==1


@pytest.mark.asyncio
async def test_durable_steer_recovery_skips_duplicate_ids_and_reinjects_valid_once(runner_parts,monkeypatch):
    obj=runner(runner_parts,model)
    obj.recovery_steers=True
    existing={'role':'user','source':'steer','steerId':'already','id':'steer:already','content':'old'}
    checkpoint(obj,messages=[existing])
    applied=[{'steerId':'already','text':'old'}, {'steerId': 17, 'text':'invalid'},
             {'steerId':'new','text':'latest','files':[]}]
    monkeypatch.setattr(obj.steers,'applied_parts',lambda *args,**kw:applied)
    states=[]

    async def loop(state,**kwargs):
        states.append(state)
        return state.messages

    monkeypatch.setattr(agent_runner,'run_agent_loop',loop)
    result=await obj.run([])
    assert len(result)==2
    assert [msg['steerId'] for msg in result]==['already','new']
    assert states[0].completed is False


@pytest.mark.asyncio
async def test_background_child_namespace_does_not_replay_root_steer_history(runner_parts,monkeypatch):
    obj=runner(runner_parts,model)
    obj.namespace='/subagent:child'
    obj.recovery_steers=True
    checkpoint(obj,messages=[])

    def forbidden(*a,**kw):
        raise AssertionError('An isolated child may not claim parent steer parts')

    monkeypatch.setattr(obj.steers,'applied_parts',forbidden)

    async def loop(state,**kwargs):
        assert kwargs['should_preempt'] is None
        return state.messages

    monkeypatch.setattr(agent_runner,'run_agent_loop',loop)
    assert await obj.run([])==[{'role':'user','content':'original'}]


@pytest.mark.asyncio
async def test_task_control_injection_persists_new_messages_then_acknowledges(runner_parts,monkeypatch):
    obj=runner(runner_parts,model)
    messages=[{'id':'command','role':'user','content':'control'}]
    seen=[]

    class Host:
        def assert_execution_lease(self, task):
            return None

        def pending(self, task, boundary, known):
            seen.append(('pending',boundary,known))
            return messages if len(seen)==1 else []

        def acknowledge(self, task, boundary, ids):
            seen.append(('ack',boundary,ids))

        def has_interrupt(self, task):
            return False

    obj.task_control_host=Host()
    obj.task_control_id='owned-task'
    obj.namespace='/subagent:owned-task'
    saved=[]

    async def save(state,calls):
        saved.append(copy.deepcopy(state.messages))

    monkeypatch.setattr(obj,'_save',save)

    async def loop(state,**kwargs):
        assert await kwargs['inject_controls'](state,'tool') is True
        assert await kwargs['inject_controls'](state,'tool') is False
        assert kwargs['should_preempt']() is False
        assert await kwargs['on_boundary'](state,'tool') is False
        assert await kwargs['on_stream_chunk']() is False
        return state.messages

    monkeypatch.setattr(agent_runner,'run_agent_loop',loop)
    output=await obj.run([])
    assert messages[0] in output
    assert len(saved)==1
    assert [item[0] for item in seen].count('ack')==2
