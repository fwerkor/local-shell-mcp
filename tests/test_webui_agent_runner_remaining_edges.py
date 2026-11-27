"""Source-level negative and recovery branches in AgentRunner.

Covers owner revocation, policy deny, malformed tool batch, failed checkpoint,
compaction and child-no-SSE cases using real SQLite.
"""
from __future__ import annotations

import time

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import approval_settings
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, RuntimeSafetyError
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import MemoryRepository
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def runner_state(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    generation, _ = store.begin('local', {'text': 'Remember the previous message.'})
    profile = ProviderConfig('openai', 'mock', 'http://127.0.0.1:1234/v1', '')

    async def stream(*args, **kwargs):
        yield 'A valid answer.'

    async def emit(_):
        pass

    runner = AgentRunner('local', generation, db, store, scopes=set(), grant_expires=None,
                         stream_tools=stream, stream_text=stream, on_text=emit, profile=profile)
    yield db, store, generation, profile, runner
    get_settings.cache_clear()


def test_context_read_failure_fails_closed_not_empty_memory(runner_state, monkeypatch):
    db, store, job, profile, runner = runner_state
    settings = WorkspaceRepository(db)
    settings.save_setting('local', 'endpoints', {'memory': {}, 'agents': {'capabilities': ['memory']}})
    MemoryRepository(db).write('local', 'private_note', 'A private memory.')
    monkeypatch.setattr(MemoryRepository, 'formatted', lambda *_args, **kwargs: {'readFailed': True})
    from local_shell_mcp.webui.memory import MEMORY_TOOL_INSTRUCTIONS

    assert runner._memory_context({'tools': ['memory']}) == MEMORY_TOOL_INSTRUCTIONS
    assert runner._memory_context(None) == MEMORY_TOOL_INSTRUCTIONS
    with pytest.raises(RuntimeSafetyError, match='expired'):
        runner.grant_expires = int(time.time()) - 1
        runner._check_grant()


@pytest.mark.asyncio
async def test_child_completion_does_not_publish_parent_sse(runner_state):
    db, store, job, profile, parent = runner_state
    child = AgentRunner('local', job, db, store, scopes=set(), grant_expires=None,
        stream_tools=parent.stream_tools, stream_text=parent.stream_text, on_text=parent.on_text,
        profile=profile, namespace='child-1')
    call = ModelToolCall('call-child', 'ignored', {})
    await child._save(AgentLoopState(AgentContext(profile, []), [{'role': 'user', 'content': 'hi'}]), [])
    await child._completed(call, {'output': 'done'})
    assert not [event for _, event in store.events('local', job.run_id) if event.get('event') == 'on_run_step_completed']
    saved = child.saver.list(child.config)
    assert any(write[2].get('content') == 'done' for checkpoint in saved for write in checkpoint['pendingWrites']
               if isinstance(write[2], dict))


@pytest.mark.asyncio
async def test_runner_rejects_undeclared_tool_and_duplicate_batches(runner_state, monkeypatch):
    db, store, job, profile, runner = runner_state
    state = AgentLoopState(AgentContext(profile, [{'function': {'name': 'ask_user_question'}},
        {'function': {'name': 'noop'}}]), [{'role': 'user', 'content': 'hello'}])
    with pytest.raises(RuntimeSafetyError, match='not enabled'):
        await runner._invoke(ModelToolCall('call-forbidden', 'not_enabled', {}), state)
    with pytest.raises(ValueError, match='unique'):
        await runner._dispatch([ModelToolCall('same', 'noop', {}), ModelToolCall('same', 'noop', {})], state)
    with pytest.raises(ValueError, match='non-empty'):
        await runner._dispatch([ModelToolCall('', 'noop', {})], state)
    with pytest.raises(ValueError, match='parallel'):
        await runner._dispatch([ModelToolCall('one', 'ask_user_question', {'question': 'why'}),
                                ModelToolCall('two', 'noop', {})], state)


@pytest.mark.asyncio
async def test_policy_deny_produces_tool_output_without_execution(runner_state, monkeypatch):
    db, store, job, profile, runner = runner_state
    from local_shell_mcp.webui import routes

    monkeypatch.setattr(routes, '_repo', lambda: WorkspaceRepository(db))
    monkeypatch.setattr(approval_settings, 'call_decision',
                        lambda _mode, _policy, name, _arguments: {'decision': 'deny', 'reason': 'Blocked by operator'})

    async def forbidden(*args, **kwargs):
        raise AssertionError('A denied tool must not execute')

    monkeypatch.setattr(runner, '_invoke', forbidden)
    call = ModelToolCall('call-denied', 'restricted', {'argument': 'private'})
    state = AgentLoopState(AgentContext(profile, [{'function': {'name': 'restricted'}}]),
                           [{'role': 'user', 'content': 'hello'}])
    await runner._save(state, [])
    result = await runner._dispatch([call], state)
    assert result.messages == [{'role': 'tool', 'tool_call_id': 'call-denied',
                                'content': 'Blocked: Blocked by operator'}]
    assert len([e for _, e in store.events('local', job.run_id) if e.get('event') == 'on_run_step_completed']) == 1


@pytest.mark.asyncio
async def test_pause_failure_and_approval_batch_rejection(runner_state, monkeypatch):
    db, store, job, profile, runner = runner_state
    state = AgentLoopState(AgentContext(profile, []), [{'role': 'user', 'content': 'anything'}])
    await runner._save(state, [])
    monkeypatch.setattr(store, 'pause_for_question', lambda *a, **kw: False)
    with pytest.raises(RuntimeError, match='Unable to save'):
        await runner._pause({'type': 'ask_user_question', 'question': 'Do you approve?'}, state)


@pytest.mark.asyncio
async def test_non_dict_summarization_configuration_uses_safe_defaults(runner_state):
    db, store, job, profile, runner = runner_state
    settings = WorkspaceRepository(db)
    settings.save_setting('local', 'endpoints', {
        'summarization': True, 'agents': {'maxContextTokens': 300}})
    history = [{'role': 'user', 'content': 'message ' * 300},
               {'role': 'assistant', 'content': 'reply ' * 300},
               {'role': 'user', 'content': 'continue'}]
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 300}), history)
    await runner._before_model(state)
    assert any(item.get('role') == 'system' and '<summary>' in str(item.get('content'))
               for item in state.messages)


def test_native_skill_tools_follow_normal_registry(runner_state, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry, skill_runtime
    from local_shell_mcp.webui.storage import _json, _now

    db, _, _, profile, runner = runner_state
    tools = [
        {'type': 'function', 'function': {'name': name}}
        for name in ('skill_list', 'skill_load', 'skill_read', 'file_read')
    ]
    monkeypatch.setattr(lsm_tool_registry, 'available_tools', lambda *a, **kw: tools)
    monkeypatch.setattr(skill_runtime, 'list_installed_skills', lambda: {'skills': []})
    now = _now()
    with db.connect() as conn:
        conn.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) '
                     'VALUES(?,?,?,?,?,?)',
                     ('managed', 'local', 'managed', _json({
                         'name': 'managed', 'description': 'Managed Skill',
                         'body': 'Trusted by activation',
                     }), now, now))
    shown = {tool['function']['name'] for tool in runner._context(None, profile=profile).tools}
    assert 'skill' not in shown
    assert {'file_read', 'skill_list', 'skill_load', 'skill_read'} <= shown
    restricted = {tool['function']['name'] for tool in
                  runner._context(None, profile=profile, selected_tools=[]).tools}
    assert not {'skill_list', 'skill_load', 'skill_read', 'file_read'} & restricted
    delegated = {tool['function']['name'] for tool in runner._context(
        {'id': 'legacy', 'skills_enabled': True, 'tools': ['file_read']}, profile=profile,
        selected_tools=('file_read',)).tools}
    assert {'skill_list', 'skill_load', 'skill_read', 'file_read'} <= delegated
    # A disabled managed record does not remove the native tool definitions.
    WorkspaceRepository(db).save_setting('local', 'webui.skill.states', {'managed': False})
    hidden = {tool['function']['name'] for tool in runner._context(None, profile=profile).tools}
    assert 'skill' not in hidden
    assert {'skill_list', 'skill_load', 'skill_read'} <= hidden


@pytest.mark.asyncio
async def test_native_skill_tools_use_normal_dispatch(runner_state, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry

    _, _, _, profile, runner = runner_state
    async def native(owner, conversation, call, **kwargs):
        return call.name

    monkeypatch.setattr(lsm_tool_registry, 'call_tool', native)
    for name in ('skill_list', 'skill_load', 'skill_read'):
        context = AgentContext(profile, [{'type': 'function', 'function': {'name': name}}])
        state = AgentLoopState(context, [{'role': 'user', 'content': 'Inspect skills'}])
        assert await runner._invoke(ModelToolCall('native-call', name, {}), state) == name


def test_server_web_preference_controls_tool_exposure(runner_state):
    db, _, job, profile, runner = runner_state
    repo = WorkspaceRepository(db)
    def names():
        return {tool['function']['name'] for tool in runner._context(None, profile=profile).tools}

    assert {'web_search', 'web_fetch'} <= names()
    repo.save_setting('local', 'conversation.permissions.' + job.conversation_id, {'web': False})
    assert not {'web_search', 'web_fetch'} & names()
    repo.save_setting('local', 'conversation.permissions.' + job.conversation_id, {'web': True})
    assert {'web_search', 'web_fetch'} <= names()


@pytest.mark.asyncio
async def test_background_skill_dispatch_preserves_hosted_context(runner_state, monkeypatch):
    from local_shell_mcp.skill_ops import managed_skill_context
    from local_shell_mcp.webui import background_tools, lsm_tool_registry

    database, _, _, profile, runner = runner_state
    agent = {'id': 'saved', 'skills_enabled': True, 'skills_scope': 'none'}
    runner._injected_background_names['saved'] = frozenset({'skill_load'})
    tools = [{'function': {'name': 'skill_load', 'parameters': {'properties': {
        'run_in_background': {'type': 'boolean'},
    }}}}]
    state = AgentLoopState(AgentContext(profile, tools, agent=agent), [])
    observed = []

    async def native(owner, conversation, call, **kwargs):
        observed.append(managed_skill_context.get())
        assert 'run_in_background' not in call.arguments
        return 'loaded'

    async def start(*args, scopes, grant_expires, dispatch, **kwargs):
        assert managed_skill_context.get() is None
        return await dispatch(args[5], scopes, grant_expires, args[3])

    monkeypatch.setattr(lsm_tool_registry, 'call_tool', native)
    monkeypatch.setattr(background_tools, 'start_tool_task', start)
    call = ModelToolCall('bg', 'skill_load', {'name': 'x', 'run_in_background': True})
    assert await runner._invoke(call, state) == 'loaded'
    assert observed == [(database, 'local', agent)]
    assert managed_skill_context.get() is None
