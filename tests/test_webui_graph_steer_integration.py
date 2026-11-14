"""Unmerged Graph/HITL draft cross-contract: in-flight steer reaches active graph node."""
from __future__ import annotations

import pytest
from wakeup_helpers import environment as environment

pytest.importorskip('langgraph')

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.steering import SteeringStore


@pytest.mark.asyncio
async def test_preemptive_steer_is_replayed_to_model_inside_serial_graph(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.state')
    repo, store = AgentRepository(db), GenerationStore(db)
    monkeypatch.setattr(agent_runner, 'provider_config', lambda _, model: ProviderConfig(
        'openai', model, 'http://localhost:1234/chat/completions', ''))
    root = repo.create('local', {'name': 'root', 'provider': 'openAI', 'model': 'root', 'tools': []})
    child = repo.create('local', {'name': 'child', 'provider': 'openAI', 'model': 'child', 'tools': []})
    root = repo.update('local', root['id'], {'edges': [{'from': root['id'], 'to': child['id'], 'edgeType': 'direct'}]})
    job, _ = store.begin('local', {'text': 'original'}, root)
    messages_seen = []

    async def model(profile, messages, **kwargs):
        messages_seen.append((profile.model, list(messages)))
        if profile.model == 'root' and len([p for p, _ in messages_seen if p == 'root']) == 1:
            SteeringStore(db).enqueue('local', {
                'conversationId': job.conversation_id,
                'generationCreatedAt': job.generation_created_at,
                'clientSteerId': 'switch-topic', 'text': 'New topic please', 'preempt': True,
            }, preempt_capable=True)
            yield 'partial'
            yield 'obsolete text'
        else:
            if profile.model == 'root':
                assert messages[-1]['source'] == 'steer'
                assert 'New topic please' in messages[-1]['content']
            yield profile.model + ' continued'

    async def noop(text):
        pass

    injected = []

    async def on_injected():
        state, _ = store.resume_snapshot('local', job.run_id)
        assert any(part.get('type') == 'steer' for part in state['aggregatedContent'])
        injected.append(True)

    runner = AgentRunner('local', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=noop,
                         agent=root, on_injected=on_injected)
    outcome = await runner.run(store.history('local', job.conversation_id))
    assert [name for name, _ in messages_seen] == ['root', 'root', 'child']
    assert outcome[-1]['content'] == 'child continued'
    assert injected == [True]
    assert any(event.get('event') == 'on_steer_applied' for _, event in store.events('local', job.run_id))
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_parallel_graph_steer_is_applied_once_without_stale_tool_dispatch(tmp_path, monkeypatch):
    """Concurrent foreground nodes share one owner/epoch-fenced queue."""
    import asyncio

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.state')
    repo, store = AgentRepository(db), GenerationStore(db)
    monkeypatch.setattr(agent_runner, 'provider_config', lambda _, model: ProviderConfig(
        'openai', model, 'http://localhost:1234/chat/completions', ''))
    root, left, right = [repo.create('local', {'name': name, 'provider': 'openAI',
                                             'model': name, 'tools': []})
                         for name in ('root', 'left', 'right')]
    root = repo.update('local', root['id'], {'edges': [
        {'from': root['id'], 'to': [left['id'], right['id']], 'edgeType': 'direct'}]})
    job, _ = store.begin('local', {'text': 'original'}, root)
    observed = []
    started = asyncio.Event()

    async def model(profile, messages, **kwargs):
        observed.append((profile.model, list(messages)))
        if profile.model == 'root':
            yield 'root output'
        elif profile.model == 'left' and not any(m.get('source') == 'steer' for m in messages):
            SteeringStore(db).enqueue('local', {
                'conversationId': job.conversation_id,
                'generationCreatedAt': job.generation_created_at,
                'clientSteerId': 'parallel-once', 'text': 'change direction', 'preempt': True,
            }, preempt_capable=True)
            started.set()
            yield 'partial-left'
            yield 'obsolete-left'
        elif profile.model == 'right':
            await started.wait()
            yield 'right output'
        else:
            assert messages[-1].get('source') == 'steer'
            yield 'left revised'

    async def noop(text):
        pass

    runner = AgentRunner('local', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=noop, agent=root)
    result = await runner.run(store.history('local', job.conversation_id))
    applied = [event for _, event in store.events('local', job.run_id)
               if event.get('event') == 'on_steer_applied']
    assert len(applied) == 1
    assert sum(any(m.get('source') == 'steer' for m in message)
               for name, message in observed if name in {'left', 'right'}) == 1
    assert sum(m.get('content') == 'left revised' for m in result) == 1
    assert all(m.get('content') != 'obsolete-left' for m in result)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_graph_node_fences_revoked_completion_wakeup_lease(environment, monkeypatch):
    """A leased root graph must not lose fencing when it enters a child node."""
    from wakeup_helpers import begin_automatic

    from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
    from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks

    db, repo, store, _, parent, parent_run = environment
    child = repo.create('local', {'name': 'graph-child', 'provider': 'openAI',
                                  'model': 'graph-child', 'tools': []})
    parent = repo.update('local', parent['id'], {'edges': [
        {'from': parent['id'], 'to': child['id'], 'edgeType': 'direct'}]})
    host, task_id, job = await begin_automatic(environment)
    with db.connect() as conn:
        token = conn.execute('SELECT lease_owner FROM subagent_wakeups WHERE task_id=?',
                             (task_id,)).fetchone()[0]

    called = []
    revoked = False
    original_check = AgentRunner._check_grant

    def check(self):
        nonlocal revoked
        if self.graph_node and self.root_agent['id'] == child['id'] and not revoked:
            with db.connect() as conn:
                conn.execute("UPDATE subagent_wakeups SET lease_owner='second-controller' "
                             "WHERE task_id=?", (task_id,))
            revoked = True
        return original_check(self)

    monkeypatch.setattr(AgentRunner, '_check_grant', check)

    async def model(profile, messages, **kwargs):
        called.append(profile.model)
        yield 'model ran'

    async def noop(text):
        pass

    runner = AgentRunner('local', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=noop,
                         agent=parent, wakeup_lease=(task_id, token))
    with pytest.raises(RuntimeSafetyError, match='lease'):
        await runner.run(store.history('local', job.conversation_id))
    assert called == ['parent']
    assert revoked
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_tool_only_chunk_checks_revoked_wakeup_lease_before_dispatch(environment, monkeypatch):
    """Token fencing is checked for a streamed tool proposal with no text."""
    from wakeup_helpers import begin_automatic

    from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
    from local_shell_mcp.webui.providers import ModelToolCall
    from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks

    db, repo, store, _, parent, _ = environment
    host, task_id, job = await begin_automatic(environment)
    with db.connect() as conn:
        token = conn.execute('SELECT lease_owner FROM subagent_wakeups WHERE task_id=?',
                             (task_id,)).fetchone()[0]

    async def model(profile, messages, **kwargs):
        with db.connect() as conn:
            conn.execute("UPDATE subagent_wakeups SET lease_owner='competing-controller' "
                         "WHERE task_id=?", (task_id,))
        yield ModelToolCall('untrusted-proposal', 'plan_manage', {'action': 'list'})

    async def noop(text):
        pass

    runner = AgentRunner('local', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=model, on_text=noop,
                         agent=parent, wakeup_lease=(task_id, token))
    with pytest.raises(RuntimeSafetyError, match='lease'):
        await runner.run(store.history('local', job.conversation_id))
    assert store.get('local', job.run_id).status == 'running'
    await shutdown_subagent_tasks()
