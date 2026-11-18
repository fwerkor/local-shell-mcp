"""Original Graph RunStep closure, SSE/history visibility, and event actor fences."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner, lsm_tool_registry
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path/'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path/'state')
    monkeypatch.setattr(agent_runner, 'provider_config', lambda _, model: ProviderConfig(
        'openai', model, 'https://example.invalid', ''))
    native = [{'type':'function', 'function':{'name':'run_shell',
               'parameters':{'type':'object','properties':{'command':{'type':'string'}}}}}]
    monkeypatch.setattr(lsm_tool_registry,'available_tools',lambda *args,**kwargs:native)
    yield db,AgentRepository(db),GenerationStore(db)
    get_settings.cache_clear()


def create(repository,name,**kwargs):
    return repository.create('alice', {'name':name,'provider':'openai','model':name,
                                        'tools':['run_shell'],**kwargs})


async def noop(_text):
    pass


@pytest.mark.asyncio
async def test_graph_all_member_tools_close_once_and_restore_source_step_metadata(environment,monkeypatch):
    db,repo,store=environment
    root=create(repo,'root')
    child=create(repo,'child')
    root=repo.update('alice',root['id'],{'edges':[
        {'from':root['id'],'to':child['id'],'edgeType':'direct'}]})
    native=[]

    async def dispatch(owner,cid,call,**kwargs):
        native.append((owner,cid,call.name,call.arguments))
        return json.dumps({'ok':True,'stdout':'done'})

    monkeypatch.setattr(lsm_tool_registry,'call_tool',dispatch)
    run,_=store.begin('alice',{'text':'graph tool calls'},root)

    async def model(profile,history,**kwargs):
        if not any(msg.get('tool_call_id')=='tool-'+profile.model for msg in history):
            yield ModelToolCall('tool-'+profile.model,'run_shell',{'command':'echo '+profile.model})
        else:
            yield profile.model+' finished'

    runner=AgentRunner('alice',run,db,store,scopes=set(),grant_expires=None,
                       stream_tools=model,stream_text=model,on_text=noop,agent=root)
    messages=await runner.run(store.history('alice',run.conversation_id))
    assert len(native)==2
    assert [i[2] for i in native]==['run_shell','run_shell']
    events=[event for _,event in store.events('alice',run.run_id)]
    opened=[e['data'] for e in events if e.get('event')=='on_run_step']
    completed=[e['data']['result'] for e in events if e.get('event')=='on_run_step_completed']
    closed=[e['data'] for e in events if e.get('event')=='on_run_step_closed']
    assert len(opened)==len(completed)==len(closed)==2
    for start,done,terminal in zip(opened,completed,closed,strict=True):
        assert start['id']==done['id']==terminal['id']
        assert terminal['status']=='completed'
        assert terminal['closed_at']>=terminal['created_at']==start['created_at']
        assert start['runId']==run.response_message_id
        assert done['tool_call']['id'] in {'tool-root','tool-child'}
    assert store.finish('alice',run.run_id,status='complete',text=';'.join(
        item['content'] for item in messages if item.get('role')=='assistant' and isinstance(item.get('content'),str)))
    final=[e for e in store.events('alice',run.run_id) if e[1].get('final')][-1][1]
    saved_tools=[part['tool_call'] for part in final['responseMessage']['content']
                 if part.get('type')=='tool_call']
    assert len(saved_tools)==2
    assert {tool['id'] for tool in saved_tools}=={'tool-root','tool-child'}
    assert all(tool['runStepStatus']=='completed' for tool in saved_tools)
    assert all(tool['runStepClosedAt']>0 and tool['runStepDurationMs']>=0 for tool in saved_tools)
    assistant=next(msg for msg in WorkspaceRepository(db).messages('alice',run.conversation_id)['messages']
                   if msg['role']=='assistant')
    assert sum(part.get('type')=='tool_call' for part in assistant['content'])==2


@pytest.mark.asyncio
async def test_source_hidden_sequential_graph_does_not_leak_earlier_agent_stream(environment):
    db,repo,store=environment
    root=create(repo,'stage-one',hide_sequential_outputs=True)
    child=create(repo,'stage-two')
    root=repo.update('alice',root['id'],{'edges':[
        {'from':root['id'],'to':child['id'],'edgeType':'direct'}],
        'resultAgentId':child['id']})
    from local_shell_mcp.webui.graph_topology import admit_agent_graph

    topology=admit_agent_graph('alice',root,repo)
    assert root['hide_sequential_outputs'] is True
    assert root.get('resultAgentId')==child['id']
    assert topology.routing_parallel is False
    run,_=store.begin('alice',{'text':'return final answer only'},root)
    visible=[]

    async def emit(text):
        visible.append(text)

    async def model(profile,history,**kwargs):
        yield 'private-stage-one' if profile.model=='stage-one' else 'public-stage-two'

    runner=AgentRunner('alice',run,db,store,scopes=set(),grant_expires=None,
                       stream_tools=model,stream_text=model,on_text=emit,agent=root)
    result=await runner.run(store.history('alice',run.conversation_id))
    assert visible==['public-stage-two']
    assert any(message.get('content')=='private-stage-one' for message in result)
    assert any(event.get('event')=='on_agent_update' for _,event in store.events('alice',run.run_id))
    assert store.finish('alice',run.run_id,status='complete',text=''.join(visible))
    final=[e for _,e in store.events('alice',run.run_id) if e.get('final')][-1]
    assert final['responseMessage']['text']=='public-stage-two'
    assert 'private-stage-one' not in json.dumps(final['responseMessage'])


@pytest.mark.asyncio
async def test_graph_nodes_inherit_event_source_lease_for_every_model_dispatch(environment,monkeypatch):
    db,repo,store=environment
    root=create(repo,'root')
    child=create(repo,'child')
    root=repo.update('alice',root['id'],{'edges':[
        {'from':root['id'],'to':child['id'],'edgeType':'direct'}]})
    run,_=store.begin('alice',{'text':'trusted event actor'},root)
    observed=[]
    # Trace only actual child _check_grant calls, never override authorization.
    checker=AgentRunner._check_grant

    def traced(self):
        if self.graph_node:
            observed.append(self.event_delivery_lease)
        return checker(self)

    monkeypatch.setattr(AgentRunner,'_check_grant',traced)
    from local_shell_mcp.webui import event_triggers

    monkeypatch.setattr(event_triggers,'assert_event_lease',lambda database,owner,run_id,lease:
                        None if lease==('delivery','lease') else (_ for _ in ()).throw(PermissionError('bad lease')))

    async def model(profile,history,**kwargs):
        yield profile.model

    runner=AgentRunner('alice',run,db,store,scopes=set(),grant_expires=None,
                       stream_tools=model,stream_text=model,on_text=noop,agent=root,
                       event_delivery_lease=('delivery','lease'))
    await runner.run(store.history('alice',run.conversation_id))
    assert observed and all(lease==('delivery','lease') for lease in observed)


@pytest.mark.asyncio
async def test_foreground_subagent_graph_tool_callback_keeps_parent_sse_private(environment):
    database, _, store = environment
    generation, _ = store.begin('alice', {'text': 'Delegate task to a graph team'})

    async def stream(*_args, **_kwargs):
        yield 'unused'

    child = AgentRunner(
        'alice', generation, database, store, scopes=set(), grant_expires=None,
        stream_tools=stream, stream_text=stream, on_text=noop,
        namespace='/subagent:team-call/graph:researcher:activation',
        graph_node=True,
    )
    call = ModelToolCall('private-child-tool', 'run_shell', {'command': 'secret subagent args'})
    await child._completed(call, {'output': 'private intermediate result'})
    visible = [entry for _, entry in store.events('alice', generation.run_id)]
    assert not [entry for entry in visible if entry.get('event') in {
        'on_run_step', 'on_run_step_completed', 'on_run_step_closed', 'attachment',
    }]
    assert store.finish('alice', generation.run_id, status='complete', text='public team result')
    final = store.events('alice', generation.run_id)[-1][1]['responseMessage']
    assert 'secret subagent args' not in json.dumps(final)
    assert 'private intermediate result' not in json.dumps(final)
