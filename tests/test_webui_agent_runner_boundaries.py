"""Original runner guard branches with real owner-scoped SQLite state."""
from __future__ import annotations

import json

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
    from local_shell_mcp.webui import machine_permissions
    from local_shell_mcp.webui.storage import WorkspaceRepository

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.state')
    # Machine permissions resolve through the shared HTTP repository by
    # default. Keep their lookup on the test database holding this run.
    monkeypatch.setattr(machine_permissions, '_repo', lambda: WorkspaceRepository(db))
    store = GenerationStore(db)
    run, _ = store.begin('local', {'text': 'Test boundaries'})
    yield db, store, run
    get_settings.cache_clear()


async def noop(text):
    pass


def runner(runner_parts, model, *, ask=False, detached=False, text=None, scopes=()):
    db, store, run = runner_parts
    provider = ProviderConfig('openai', 'mock', 'http://localhost:8900/v1/chat/completions', '')
    return AgentRunner('local', run, db, store, scopes=set(scopes), grant_expires=None,
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
    monkeypatch.setattr('local_shell_mcp.webui.agent_runner.SLEEP_TOOLS', [])
    # Memory is enabled by default, so opt out for the explicit no-tools path.
    _repo().save_setting('local', 'user.memories', False)
    streams = []

    async def text_model(profile, messages, **kwargs):
        streams.append(messages)
        yield 'Native-tools-disabled text still streams.'

    async def unexpected_tools(*args, **kwargs):
        pytest.fail('Tool streaming must not run when provider has no declared tools')
        yield ''

    obj = runner(runner_parts, unexpected_tools, text=text_model)
    obj.web_search_enabled = False  # Web tools default on; opt out for text-only path.
    obj.child_configs = []  # Explicit no-subagent scope for the no-tools transport test.
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

    async def lookup(*args, agent_id=None):
        assert agent_id is None
        calls.append('search')
        return 'searched'

    async def execute(*args, agent_id=None):
        assert agent_id is None
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


@pytest.mark.asyncio
async def test_managed_skill_is_callable_in_the_real_agent_loop(runner_parts):
    from local_shell_mcp.webui.storage import _json, _now

    db, store, generation = runner_parts
    with db.connect() as conn:
        now = _now()
        conn.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) '
                     'VALUES(?,?,?,?,?,?)', ('skill-in-loop', 'local', 'test-skill',
                     _json({'name': 'test-skill', 'description': 'Test runtime',
                            'body': 'Read the spec first.'}), now, now))
    seen = []

    async def model(profile, messages, **kwargs):
        seen.append((messages, kwargs))
        if not any(msg.get('role') == 'tool' for msg in messages):
            tools = kwargs.get('tools', [])
            assert {'skill_list', 'skill_load', 'skill_read'} <= {t['function']['name'] for t in tools}
            assert 'skill' not in {t['function']['name'] for t in tools}
            yield ModelToolCall('skill-1', 'skill_load', {'name': 'managed/skill-in-loop'})
        else:
            assert json.loads(messages[-1]['content'])['data']['content'] == 'Read the spec first.'
            yield 'Skill instructions applied.'

    obj = runner(runner_parts, model, scopes={'shell:read'})
    completed = await obj.run(store.history('local', generation.conversation_id))
    assert completed[-1]['content'] == 'Skill instructions applied.'
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_native_skill_tools_read_files_and_respect_local_access(runner_parts):
    from local_shell_mcp.webui.storage import WorkspaceRepository, _json, _now

    db, store, generation = runner_parts
    skill = get_settings().workspace_root / '.agents' / 'skills' / 'native-test'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: native-test\ndescription: Native test\n---\nNative instructions', encoding='utf-8')
    (skill / 'guide.md').write_text('Native guide', encoding='utf-8')
    with db.connect() as conn:
        now = _now()
        for owner in ('local', 'other'):
            conn.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) '
                         'VALUES(?,?,?,?,?,?)', ('db-' + owner, owner, 'native-test',
                         _json({'description': 'Managed test', 'body': 'Managed instructions'}), now, now))
        conn.execute('INSERT INTO webui_skill_files(id,owner,skill_id,path,data,mime,created_at,updated_at) '
                     'VALUES(?,?,?,?,?,?,?,?)',
                     ('reference', 'local', 'db-local', 'guide.md', b'Managed guide', 'text/plain', now, now))

    obj = runner(runner_parts, None, scopes={'shell:read'})
    context = obj._context(None, profile=obj.initial_profile)
    state = AgentLoopState(context, [])

    async def invoke(name, args):
        return json.loads(await obj._invoke(ModelToolCall('skill-call', name, args), state))

    result = await invoke('skill_list', {})
    assert result['ok'], result
    names = {item['name'] for item in result['data']['skills']}
    assert {'native-test', 'managed/db-local'} <= names
    assert 'managed/db-other' not in names
    for name, instructions, guide in (
        ('native-test', 'Native instructions', 'Native guide'),
        ('managed/db-local', 'Managed instructions', 'Managed guide'),
    ):
        loaded = await invoke('skill_load', {'name': name})
        assert instructions in loaded['data']['content']
        assert 'guide.md' in loaded['data']['related_files']
        read = await invoke('skill_read', {'name': name, 'path': 'guide.md'})
        assert read['data']['content'] == guide
    assert (await invoke('skill_load', {'name': 'managed/db-other'}))['isError']
    repo = WorkspaceRepository(db)
    repo.save_setting('local', 'webui.skill.states', {'db-local': False})
    assert (await invoke('skill_load', {'name': 'managed/db-local'}))['isError']
    assert (await invoke('skill_load', {'name': 'native-test'}))['ok']

    repo.save_setting('local', 'agent.machine_policy.conversation.' + generation.conversation_id,
                      {'local': 'none'})
    assert not {'skill_list', 'skill_load', 'skill_read'} & {
        t['function']['name'] for t in obj._context(None, profile=obj.initial_profile).tools
    }
    with pytest.raises(RuntimeSafetyError, match='not granted'):
        await invoke('skill_list', {})


@pytest.mark.asyncio
async def test_readonly_browser_start_is_a_tool_failure_not_a_run_failure(runner_parts, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry, machine_permissions
    from local_shell_mcp.webui.storage import WorkspaceRepository

    db, store, generation = runner_parts
    monkeypatch.setattr(machine_permissions, "_registered_defaults", lambda: {"local": "write"})
    WorkspaceRepository(db).save_setting(
        "local", "agent.machine_policy.conversation." + generation.conversation_id, {"local": "read"},
    )

    async def unexpected_dispatch(*args, **kwargs):
        pytest.fail("A denied browser start must never dispatch")

    monkeypatch.setattr(lsm_tool_registry, "_invoke_registered", unexpected_dispatch)

    async def model(profile, messages, **kwargs):
        if not any(m.get("role") == "tool" for m in messages):
            yield ModelToolCall("denied-start", "browser_session", {"action": "start"})
        else:
            assert messages[-1]["tool_call_id"] == "denied-start"
            assert messages[-1]["content"].startswith("Blocked: ")
            assert "read-only" in messages[-1]["content"]
            yield "The machine is read-only; the browser was not started."

    obj = runner(runner_parts, model, scopes={"shell:read", "shell:write", "browser:use"})
    messages = await obj.run(store.history("local", generation.conversation_id))
    assert messages[-1]["content"] == "The machine is read-only; the browser was not started."
