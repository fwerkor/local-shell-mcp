"""Original AgentRunner approval/graph-tool boundary conditions and durable SSE."""
from __future__ import annotations

import pytest
from test_webui_agent_runner_boundaries import runner
from test_webui_agent_runner_boundaries import runner_parts as runner_parts

from local_shell_mcp.webui import agent_runner, approval_settings
from local_shell_mcp.webui.agent_runtime import AgentLoopState, AgentSuspended, RuntimeSafetyError
from local_shell_mcp.webui.providers import ModelToolCall


async def model(*args, **kwargs):
    yield 'reply'


def ready(parts, *, detached=False, ask=False):
    obj = runner(parts, model, detached=detached, ask=ask)
    obj.active_config = obj.saver.put(obj.active_config, {
        "v": 1, "id": "initial-test-checkpoint", "channel_values": {},
        "channel_versions": {}, "versions_seen": {},
    }, {"source": "test", "step": 0})
    return obj, AgentLoopState(obj._context(None, profile=obj.initial_profile), [])


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [
    [ModelToolCall('dup','plan_manage',{'action':'list'}),
     ModelToolCall('dup','plan_manage',{'action':'list'})],
    [ModelToolCall('','plan_manage',{'action':'list'})],
])
async def test_tool_batch_rejects_duplicate_and_empty_ids_before_checkpoint(runner_parts, invalid):
    obj, state = ready(runner_parts)
    with pytest.raises(ValueError, match='non-empty and unique'):
        await obj._dispatch(invalid, state)


@pytest.mark.asyncio
async def test_tool_batch_rejects_not_enabled_and_can_skip_namespace_only_step(runner_parts, monkeypatch):
    obj, state = ready(runner_parts)
    with pytest.raises(RuntimeSafetyError, match='not enabled'):
        await obj._dispatch([ModelToolCall('unknown','not-enabled',{})], state)
    obj.namespace = '/subagent:one'
    observed = []

    async def fake_execute(calls, invoke, **kwargs):
        observed.extend(calls)
        return ['tool done']

    monkeypatch.setattr(agent_runner, 'execute_tool_batch', fake_execute)
    result = await obj._dispatch([ModelToolCall('plan','plan_manage',{'action':'list'})], state)
    assert len(observed)==1 and result.messages[0]['content']=='tool done'
    with obj.database.connect() as db:
        assert not db.execute("SELECT 1 FROM generation_events WHERE run_id=? "
                              "AND json_extract(data,'$.event')='on_run_step'",
                              (obj.generation.run_id,)).fetchone()


@pytest.mark.asyncio
@pytest.mark.parametrize('decision,detached', [('deny',False), ('ask',True), ('ask',False)])
async def test_policy_deny_background_approval_or_human_pause_follow_original_fence(runner_parts,monkeypatch,
                                                                                     decision,detached):
    obj, state = ready(runner_parts,detached=detached)
    monkeypatch.setattr(approval_settings,'call_decision',lambda *args:
                        {'decision':decision,'reason':'policy denied'})
    seen=[]

    async def fake_execute(calls, invoke, **kwargs):
        seen.extend(kwargs['settled'].values())
        return [r['output'] for r in kwargs['settled'].values()]

    monkeypatch.setattr(agent_runner,'execute_tool_batch',fake_execute)
    if decision=='ask' and not detached:
        with pytest.raises(AgentSuspended):
            await obj._dispatch([ModelToolCall('id-approval','plan_manage',{'action':'list'})],state)
        assert obj.store.pending_action(obj.owner,obj.generation.run_id)
    else:
        result=await obj._dispatch([ModelToolCall('id-deny','plan_manage',{'action':'list'})],state)
        expected='Approval required' if detached else 'policy denied'
        assert expected in result.messages[0]['content']
        assert seen and expected in seen[0]['output']


@pytest.mark.asyncio
@pytest.mark.parametrize('detached,multiple',[(False,False),(False,True),(True,False)])
async def test_ask_user_background_denial_parallel_constraint_or_pause(runner_parts,monkeypatch,
                                                                        detached,multiple):
    obj,state=ready(runner_parts,detached=detached,ask=True)
    monkeypatch.setattr(approval_settings,'call_decision',lambda *args:None)

    async def fake_execute(calls, invoke, **kwargs):
        return [r['output'] for r in kwargs['settled'].values()]

    monkeypatch.setattr(agent_runner,'execute_tool_batch',fake_execute)
    calls=[ModelToolCall('ask','ask_user_question',{'questions':[{
        'id':'choice','question':'Choose?',
        'options':[{'label':'Yes','value':'yes'},{'label':'No','value':'no'}]}]})]
    if multiple:
        calls.append(ModelToolCall('plan','plan_manage',{'action':'list'}))
    if detached:
        assert 'ask_user_question' not in {tool['function']['name'] for tool in state.context.tools}
        with pytest.raises(RuntimeSafetyError,match='Tool is not enabled'):
            await obj._dispatch(calls,state)
    elif multiple:
        with pytest.raises(ValueError,match='cannot run in parallel'):
            await obj._dispatch(calls,state)
    else:
        with pytest.raises(AgentSuspended):
            await obj._dispatch(calls,state)


@pytest.mark.asyncio
async def test_unpersistable_human_action_is_rejected_without_executing_tool(runner_parts,monkeypatch):
    obj,state=ready(runner_parts)
    monkeypatch.setattr(obj.store,'pause_for_approval',lambda *a,**kw:False)
    monkeypatch.setattr(obj.store,'pause_for_question',lambda *a,**kw:False)
    for approval in (True,False):
        with pytest.raises(RuntimeError,match='Unable to save pending'):
            await obj._pause({'type':'policy'},state,approval=approval)


@pytest.mark.asyncio
async def test_source_handoff_command_must_be_inside_running_graph(runner_parts,monkeypatch):
    obj,state=ready(runner_parts)
    command={'graph':True,'goto':'child','update':{}}

    async def fake_execute(calls, invoke, **kwargs):
        return [command]

    monkeypatch.setattr(agent_runner,'execute_tool_batch',fake_execute)
    monkeypatch.setattr(agent_runner,'combine_handoff_commands',lambda commands:commands)
    monkeypatch.setattr(obj.route,'finalize',lambda *a,**kw:None)
    call=ModelToolCall('handoff','plan_manage',{'action':'list'})
    with pytest.raises(RuntimeSafetyError,match='active StateGraph'):
        await obj._dispatch([call],state)
    obj.graph_node=True
    result=await obj._dispatch([call],state)
    assert result.graph_commands==[command]
