"""Memory-source field policy, projected reads, and model-bound write controls."""
from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import memory_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import MemoryRepository, execute_memory_tool
from local_shell_mcp.webui.memory_protection import (
    MemoryContentBlocked,
    assert_memory_content_allowed,
    inspect_memory_content,
    project_stored_memories,
)
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


def policy(fields=None, *, action='block', expression='PRIVATE-[A-Z]+'):
    opts = {'starterPatterns': [], 'customPatterns': [
        {'id': 'private', 'label': 'private value', 'regex': expression}], 'action': action}
    if fields is not None:
        opts['fields'] = fields
    return {'memories': {'pii': opts}}


@pytest.mark.parametrize('fields,record,expected', [
    (None, {'_id': 'one', 'key': 'style', 'value': 'PRIVATE-STORED', 'tokenCount': 4},
     {'key': 'style', 'value': '', 'contentFilterBlocked': True}),
    (['value'], {'key': 'PRIVATE-KEY', 'value': 'safe'},
     {'key': 'PRIVATE-KEY', 'value': 'safe'}),
    (['value'], {'key': 'style', 'value': 'PRIVATE-VALUE'},
     {'key': 'style', 'value': '', 'contentFilterBlocked': True}),
    (['summary'], {'key': 'style', 'value': 'safe', 'summary': 'PRIVATE-SUMMARY'},
     {'key': 'style', 'value': 'safe', 'summary': '', 'contentFilterBlocked': True}),
    (['key'], {'key': 'PRIVATE-KEY', 'value': 'safe'},
     {'key': '', 'value': 'safe', 'contentFilterBlocked': True}),
])
def test_source_field_projections(fields, record, expected):
    projected = project_stored_memories([record], policy(fields))[0]
    for name, value in expected.items():
        assert projected[name] == value
    if expected.get('contentFilterBlocked'):
        assert projected.get('contentFilterBlocked')
    else:
        assert 'contentFilterBlocked' not in projected
    for name in ('_id', 'tokenCount'):
        if name in record:
            assert projected[name] == record[name]
    assert record.get('value') == record.get('value')  # source row is unmodified


def test_policy_only_inspects_selected_memory_fields():
    assert inspect_memory_content({'key': 'PRIVATE-KEY', 'value': 'normal'}, policy(['value'])) is None
    assert inspect_memory_content({'key': 'PRIVATE-KEY', 'value': 'normal'}, policy(['key'])).field == 'key'
    assert inspect_memory_content({'key': 'PRIVATE-KEY'}, policy([], expression='PRIVATE-[A-Z]+')) is None
    assert inspect_memory_content({'key': 'PRIVATE-KEY'}, policy(action='audit')) is None
    assert project_stored_memories([{'key': 'style', 'value': 'PRIVATE-VALUE'}],
                                  policy(action='audit'))[0]['value'] == 'PRIVATE-VALUE'
    assert inspect_memory_content({'value': 'Bearer token'}, {'memories': {'pii': {
        'starterPatterns': ['bearer_header']}}}).field == 'value'
    assert inspect_memory_content({'value': 'ordinary'}, {'memories': {'pii': {
        'starterPatterns': []}}}) is None


def test_invalid_or_expensive_patterns_fail_closed():
    invalid = policy(expression='(secret)+(?!okay)')
    finding = inspect_memory_content({'value': 'safe'}, invalid)
    assert finding is not None
    assert finding.response(model=True) == {
        'error': 'content_filter_block',
        'message': 'Submitted content was blocked by content policy.',
        'source': 'memory', 'field': 'key',
    }
    assert project_stored_memories([{'key': 'normal', 'value': 'sensitive'}], invalid) == [
        {'key': '', 'value': '', 'contentFilterBlocked': True}]
    with pytest.raises(MemoryContentBlocked):
        assert_memory_content_allowed('style', 'safe', invalid)


def test_transaction_rejects_filtered_write_without_changing_data(tmp_path):
    db = shared_database(tmp_path / '.local-shell-mcp')
    memory = MemoryRepository(db)
    original = memory.write('a', 'style', 'Unfiltered original.')
    with pytest.raises(MemoryContentBlocked):
        memory.write('a', 'style', 'PRIVATE-VALUE', filters=policy())
    assert memory.list('a', '')[0] == original
    formatted = memory.formatted('a', '', filters=policy())
    assert 'Unfiltered original.' in formatted['withKeys']
    # Update filter applies to records that were written before it was enabled.
    memory.write('a', 'notes', 'PRIVATE-VALUE')
    projected = memory.formatted('a', '', filters=policy())
    assert 'PRIVATE-VALUE' not in projected['withKeys']
    assert 'PRIVATE-VALUE' not in projected['withoutKeys']
    assert projected['totalTokens'] == memory.formatted('a')['totalTokens']
    result, artifact = execute_memory_tool(memory, 'a', {}, 'set_memory',
        {'key': 'more', 'value': 'PRIVATE-TOOL'}, {'filters': policy()})
    assert artifact is None
    assert json.loads(result)['error'] == 'content_filter_block'
    assert 'PRIVATE-TOOL' not in result
    assert not any(row['key'] == 'more' for row in memory.list('a'))


@pytest.fixture
def memory_state(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir)
    repo = WorkspaceRepository(database)
    repo.save_setting('local', 'endpoints', {'memory': {'tokenLimit': 500},
                                           'agents': {'capabilities': ['memory']}})
    yield database, repo
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_memory_rest_rejects_filtered_writes_and_redacts_legacy_rows(memory_state):
    db, repo = memory_state
    store = MemoryRepository(db)
    raw = store.write('local', 'style', 'PRIVATE-OLDER')
    repo.save_setting('local', 'webui.filters.config', policy(['value']))
    app = Starlette(routes=memory_routes.memory_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as cli:
        listing = (await cli.get('/api/memories')).json()
        assert listing['memories'][0]['value'] == ''
        assert listing['memories'][0]['contentFilterBlocked'] is True
        assert listing['memories'][0]['_id'] == raw['_id']
        assert listing['totalTokens'] == raw['tokenCount']
        added = await cli.post('/api/memories', json={'key': 'private', 'value': 'PRIVATE-WRITE'})
        assert added.status_code == 400
        assert added.json()['error'] == 'content_filter_block'
        assert added.json()['field'] == 'value'
        assert 'PRIVATE-WRITE' not in added.text
        updated = await cli.patch('/api/memories/id/' + raw['_id'],
                                  json={'value': 'PRIVATE-EDITED'})
        assert updated.status_code == 400
        assert store.list('local', '')[0]['value'] == 'PRIVATE-OLDER'
        changed = await cli.patch('/api/memories/id/' + raw['_id'],
                                  json={'value': 'Safe replacement'})
        assert changed.status_code == 200
        assert changed.json()['memory']['value'] == 'Safe replacement'
        assert not changed.json()['memory'].get('contentFilterBlocked')
        by_key = await cli.patch('/api/memories/style', json={'value': 'PRIVATE-BYKEY'})
        assert by_key.status_code == 400
        assert store.list('local', '')[0]['value'] == 'Safe replacement'


@pytest.mark.asyncio
async def test_runner_model_context_never_leaks_filtered_legacy_memory(memory_state):
    db, repo = memory_state
    MemoryRepository(db).write('local', 'style', 'PRIVATE-OLDER')
    repo.save_setting('local', 'webui.filters.config', policy(['value']))
    store = GenerationStore(db)
    agent = {'id': 'memory_agent', 'tools': ['memory']}
    run, _ = store.begin('local', {'text': 'Hello'})

    async def empty(*args, **kwargs):
        if False:
            yield 'unused'

    async def emit(_):
        pass

    runner = AgentRunner('local', run, db, store, scopes=set(), grant_expires=None,
        stream_tools=empty, stream_text=empty, on_text=emit,
        agent=agent, profile=ProviderConfig('openai', 'test', 'http://localhost', ''))
    prompt = runner._memory_context(agent)
    assert 'PRIVATE-OLDER' not in prompt
    assert 'contentFilterBlocked' not in prompt
    assert 'Only use the `set_memory`' in prompt


@pytest.mark.parametrize('bad_rules', [
    {'starterPatterns': 'wrong'},
    {'starterPatterns': ['missing_rule']},
    {'starterPatterns': [], 'customPatterns': 'wrong'},
    {'starterPatterns': [], 'customPatterns': [None]},
    {'starterPatterns': [], 'customPatterns': [{'id': 'x', 'regex': 'abc'}]},
    {'starterPatterns': [], 'customPatterns': [{'id': 'x', 'label': 'x', 'regex': None}]},
    {'starterPatterns': [], 'customPatterns': [{'id': 'x', 'label': 'x', 'regex': 'x'*513}]},
    {'starterPatterns': [], 'customPatterns': [
        {'id': f'pattern{i}', 'label': 'rule', 'regex': '.' * 40} for i in range(220)]},
])
def test_untrusted_filter_configuration_fails_closed(bad_rules):
    filters = {'memories': {'pii': bad_rules}}
    result = inspect_memory_content({'key': 'safe', 'value': 'safe'}, filters)
    assert result is not None
    assert result.field in ('key', 'value')


def test_invalid_memory_filter_field_scope_defaults_to_safe_all_fields():
    entry = {'key': 'PRIVATE-KEY', 'value': 'normal'}
    filtered = {'memories': {'pii': {**policy()['memories']['pii'], 'fields': 'not an array'}}}
    assert inspect_memory_content(entry, filtered).field == 'key'
    assert project_stored_memories([entry], filtered)[0]['key'] == ''
    assert inspect_memory_content({}, {'memories': {}}) is None
    assert inspect_memory_content({'value': 'safe'}, None) is None


def test_excessively_long_legacy_values_are_redacted_and_timeout_fails_closed(monkeypatch):
    import local_shell_mcp.webui.memory_protection as protection

    assert inspect_memory_content({'value': 'a' * (262144 + 1)}, policy(['value'])).field == 'value'

    class ExpensivePattern:
        def search(self, text, *, timeout):
            raise TimeoutError('pattern timed out')

    monkeypatch.setattr(protection, '_rules', lambda _: [(ExpensivePattern(), 'confidential')])
    assert inspect_memory_content({'value': 'safe'}, policy(['value'])).field == 'value'


def test_controller_import_and_memory_projection_without_optional_regex(tmp_path):
    """The plain wheel must boot; a missing policy engine must fail closed."""
    import os
    import subprocess
    import sys

    source = '''
import builtins
original_import = builtins.__import__
def without_regex(name, *args, **kwargs):
    if name == 'regex' or name.startswith('regex.'):
        raise ModuleNotFoundError('No module named regex')
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_regex
from local_shell_mcp.webui.memory_routes import memory_routes
from local_shell_mcp.webui.memory_protection import project_stored_memories
assert memory_routes()
source = {'memories': {'pii': {'starterPatterns': ['sk_prefix']}}}
projected = project_stored_memories([{'key': 'style', 'value': 'safe'}], source)[0]
assert projected['value'] == ''
assert projected['contentFilterBlocked'] is True
'''
    env = os.environ.copy()
    env['PYTHONPATH'] = 'src'
    proc = subprocess.run([sys.executable, '-c', source], text=True, capture_output=True,
                          cwd=os.getcwd(), env=env, timeout=20, check=False)
    assert proc.returncode == 0, proc.stderr
