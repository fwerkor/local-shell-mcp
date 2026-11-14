"""Original runner guard branches with real owner-scoped SQLite state."""
from __future__ import annotations

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentLoopState, RuntimeSafetyError
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.routes import _repo


@pytest.fixture
def runner_parts(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.state')
    store = GenerationStore(db)
    run, _ = store.begin('local', {'text': 'Test boundaries'})
    yield db, store, run
    get_settings.cache_clear()


async def noop(text):
    pass


def runner(runner_parts, model, *, ask=False, detached=False, text=None):
    db, store, run = runner_parts
    provider = ProviderConfig('openai', 'mock', 'http://localhost:8900/v1/chat/completions', '')
    return AgentRunner('local', run, db, store, scopes=set(), grant_expires=None,
                       stream_tools=model, stream_text=text or model, on_text=noop,
                       profile=provider, ask_user_enabled=ask, background_deny=detached)


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_name', ['plan_manage', 'ask_user_question'])
async def test_detached_runner_blocks_human_tools_without_side_effects(runner_parts, tool_name):
    if tool_name == 'plan_manage':
        _repo().save_setting('local', 'endpoints', {'agents': {
            'toolApproval': {'enabled': True, 'ask': ['plan_manage']},
        }})
    seen = []

    async def model(profile, messages, **kwargs):
        seen.append(messages)
        if not any(m.get('role') == 'tool' for m in messages):
            arguments = {'action': 'list'} if tool_name == 'plan_manage' else {'question': 'Confirm?'}
            yield ModelToolCall('tool-to-block', tool_name, arguments)
        else:
            assert messages[-1]['tool_call_id'] == 'tool-to-block'
            assert messages[-1]['content'].startswith('Blocked:')
            yield 'The protected action never executed.'

    obj = runner(runner_parts, model, ask=True, detached=True)
    messages = await obj.run(runner_parts[1].history('local', runner_parts[2].conversation_id))
    assert messages[-1]['content'] == 'The protected action never executed.'
    assert len(seen) == 2
    assert runner_parts[1].pending_action('local', runner_parts[2].run_id) is None


@pytest.mark.asyncio
async def test_text_only_provider_path_when_no_native_tools(runner_parts, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry

    monkeypatch.setattr(lsm_tool_registry, 'available_tools', lambda *a, **kw: [])
    streams = []

    async def text_model(profile, messages, **kwargs):
        streams.append(messages)
        yield 'Native-tools-disabled text still streams.'

    async def unexpected_tools(*args, **kwargs):
        pytest.fail('Tool streaming must not run when provider has no declared tools')
        yield ''

    obj = runner(runner_parts, unexpected_tools, text=text_model)
    messages = await obj.run(runner_parts[1].history('local', runner_parts[2].conversation_id))
    assert messages[-1]['content'] == 'Native-tools-disabled text still streams.'
    assert len(streams) == 1


@pytest.mark.asyncio
async def test_enabled_registry_and_nested_mcp_error_guards(runner_parts, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry, nested_mcp
    from local_shell_mcp.webui.subagent_task_host import SQLiteSubagentTaskHost

    async def model(*a, **kw):
        yield 'Unused'

    obj = runner(runner_parts, model)
    state = AgentLoopState(obj._context(None, profile=obj.initial_profile), [])
    with pytest.raises(RuntimeSafetyError, match='not enabled'):
        await obj._invoke(ModelToolCall('blocked', 'not-registered', {}), state)

    async def forbidden(*args, **kwargs):
        raise PermissionError('Revoked current machine grant')

    monkeypatch.setattr(lsm_tool_registry, 'call_tool', forbidden)
    with pytest.raises(RuntimeSafetyError, match='Revoked current machine'):
        await obj._invoke(ModelToolCall('native', 'plan_manage', {'action': 'list'}), state)

    async def broken(*args, **kwargs):
        raise RuntimeError('secret information must not appear in output')

    monkeypatch.setattr(lsm_tool_registry, 'call_tool', broken)
    assert await obj._invoke(ModelToolCall('native-2', 'plan_manage', {'action': 'list'}), state) == \
        'Tool failed (RuntimeError)'

    calls = []

    async def lookup(*args):
        calls.append('search')
        return 'searched'

    async def execute(*args):
        calls.append('call')
        return 'called'

    monkeypatch.setattr(nested_mcp, 'discover', lookup)
    monkeypatch.setattr(nested_mcp, 'approved_call', execute)
    for name in ('mcp_tool_search', 'mcp_tool_call', 'check_background_task'):
        state.context.tools.append({'function': {'name': name}})
    assert await obj._invoke(ModelToolCall('search', 'mcp_tool_search', {}), state) == 'searched'
    assert await obj._invoke(ModelToolCall('call', 'mcp_tool_call', {}), state) == 'called'
    assert calls == ['search', 'call']

    async def check(self, args, *, tool_call_id, parent_run_id, parent_agent_id):
        assert tool_call_id == 'task-poll' and parent_run_id == runner_parts[2].run_id
        return 'queued child'

    monkeypatch.setattr(SQLiteSubagentTaskHost, 'check', check)
    assert await obj._invoke(ModelToolCall('task-poll', 'check_background_task', {}), state) == 'queued child'
