"""Memory negative paths: authorization, partitions, quotas and failed writes."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.memory import (
    MemoryLimitExceeded,
    MemoryRepository,
    agent_partition,
    execute_memory_tool,
    memory_config,
    memory_enabled,
)
from local_shell_mcp.webui.memory_routes import _write, memory_routes
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = shared_database(get_settings().state_dir.resolve())
    repo = WorkspaceRepository(db)
    yield db, repo
    get_settings.cache_clear()


def _enable(repo, config=None):
    repo.save_setting('local', 'endpoints', {'memory': config or {'tokenLimit': 1000},
                                           'agents': {'capabilities': ['memory']}})


def test_memory_is_explicit_opt_in_and_deployment_is_readable(state):
    _, repo = state
    assert not memory_enabled(repo, 'local')
    assert memory_config(repo, 'local') is None
    _enable(repo)
    assert memory_enabled(repo, 'local')
    assert memory_enabled(repo, 'local', tools=True)
    repo.save_setting('local', 'user.memories', False)
    assert not memory_enabled(repo, 'local')
    repo.save_setting('local', 'user.memories', True)
    repo.save_setting('local', 'endpoints', {'memory': {'tokenLimit': 12}, 'agents': {}})
    assert memory_enabled(repo, 'local')
    assert not memory_enabled(repo, 'local', tools=True)
    repo.save_setting('local', 'webui.memory.config', {'disabled': True})
    assert not memory_enabled(repo, 'local')
    repo.save_setting('local', 'webui.memory.config', {'validKeys': ['style']})
    assert memory_config(repo, 'local')['validKeys'] == ['style']
    assert agent_partition({}) == ''
    assert agent_partition({'id': 'a', 'memory_scope': 'user'}) == ''
    assert agent_partition({'id': 12, 'memory_scope': 'agent'}) == ''


def test_memory_formatted_read_failure_not_misrepresented_as_empty(state, monkeypatch):
    db, repo = state
    store = MemoryRepository(db)
    store.write('local', 'style', 'Remember this.')
    with patch.object(store, 'list', side_effect=sqlite3.OperationalError('read failed')):
        failed = store.formatted('local')
    assert failed['readFailed'] and failed['withKeys'] is None
    with pytest.raises(ValueError):
        store.delete('local')
    with pytest.raises(ValueError):
        store.write('local', 'style', 'a' * 20, char_limit=3)
    with pytest.raises(ValueError):
        store.write('local', 'style', '\t \n')


def test_memory_quota_error_artifacts_and_transaction_guards(state):
    db, _ = state
    store = MemoryRepository(db)
    first = store.write('local', 'first', 'A short response.')
    count = first['tokenCount']
    with pytest.raises(MemoryLimitExceeded) as excluded:
        store.write('local', 'second', 'New record.', token_limit=count)
    assert excluded.value.kind == 'already_exceeded'
    artifact = excluded.value.artifact()['memory']
    assert artifact['type'] == 'error' and artifact['key'] == 'system'
    with pytest.raises(MemoryLimitExceeded) as excluded:
        store.write('local', 'second', 'Another long response.', token_limit=count+1)
    assert excluded.value.kind == 'would_exceed'
    def tool(name, args, cfg):
        return execute_memory_tool(store, 'local', {}, name, args, cfg)
    assert tool('set_memory', {'key': 1, 'value': 'No.'}, {}) == ('Invalid key', None)
    assert tool('set_memory', {'key': 'new', 'value': None}, {})[1] is None
    assert tool('set_memory', {'key': 'a' * 1001, 'value': 'No.'}, {})[0].startswith('Key exceeds')
    assert tool('set_memory', {'key': 'valid', 'value': 'something long'}, {'charLimit': 2})[0].startswith('Value exceeds')
    assert tool('delete_memory', {'key': 'unknown'}, {}) == ('Failed to delete memory for key "unknown"', None)
    message, artifact = tool('set_memory', {'key': 'second', 'value': 'New.'}, {'tokenLimit': count})
    assert 'exceeded' in message and artifact['memory']['type'] == 'error'
    message, artifact = tool('set_memory', {'key': 'second', 'value': 'Two more words.'}, {'tokenLimit': count+1})
    assert 'exceed' in message and artifact['memory']['type'] == 'error'
    assert len(store.list('local')) == 1


def test_memory_tool_error_paths_do_not_claim_write(state):
    db, _ = state
    store = MemoryRepository(db)
    def set_tool():
        return execute_memory_tool(store, 'local', {}, 'set_memory',
                                   {'key': 'style', 'value': 'Hello world'}, {})

    def delete_tool():
        return execute_memory_tool(store, 'local', {}, 'delete_memory', {'key': 'style'}, {})
    for exc in (OverflowError(), ValueError(), sqlite3.IntegrityError(), KeyError(), RuntimeError()):
        with patch.object(store, 'write', side_effect=exc):
            message, artifact = set_tool()
            assert artifact is None
            assert 'Memory set' not in message
    for exc in (ValueError(), RuntimeError()):
        with patch.object(store, 'delete', side_effect=exc):
            message, artifact = delete_tool()
            assert artifact is None
            assert 'Memory deleted' not in message


@pytest.mark.asyncio
async def test_memory_http_route_guards_and_error_statuses(state):
    db, repo = state
    app = Starlette(routes=memory_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/memories')).status_code == 403
        _enable(repo, {'tokenLimit': 20, 'charLimit': 20})
        bad = [
            ({'key': '', 'value': 'yes'}, 400),
            ({'key': 'yes', 'value': ''}, 400),
            ({'key': 'a' * 1001, 'value': 'yes'}, 400),
            ({'key': 'Bad', 'value': 'yes'}, 400),
            ({'key': 'yes', 'value': 'a' * 21}, 400),
            ({'key': 'valid', 'value': 'OK', 'agentId': 'nonexistent'}, 404),
        ]
        for payload, expected in bad:
            assert (await client.post('/api/memories', json=payload)).status_code == expected
        assert (await client.patch('/api/memories/preferences', json={'memories': 'true'})).status_code == 400
        first = (await client.post('/api/memories', json={'key': 'style', 'value': 'Hello.'})).json()['memory']
        assert (await client.delete('/api/memories/id/notreal')).status_code == 404
        assert (await client.patch('/api/memories/id/notreal', json={'value': 'Here.'})).status_code == 404
        assert (await client.patch('/api/memories/id/' + first['_id'], json={'value': ''})).status_code == 400
        assert (await client.patch('/api/memories/id/' + first['_id'], json={
            'key': 'BAD', 'value': 'Here.'})).status_code == 400
        assert (await client.patch('/api/memories/style', json={'value': 'Here.'})).status_code == 200
        assert (await client.patch('/api/memories/nonexistent', json={'value': 'Here.'})).status_code == 404
        assert (await client.post('/api/memories', json={'key': 'second', 'value': 'Yes.'})).status_code == 201
        assert (await client.patch('/api/memories/style', json={
            'key': 'second', 'value': 'Hey.'})).status_code == 409
        assert (await client.patch('/api/memories/id/' + first['_id'], json={
            'key': 'second', 'value': 'Hey.'})).status_code == 409
        _enable(repo, {'tokenLimit': 1, 'charLimit': 20})
        assert (await client.patch('/api/memories/style', json={
            'value': 'Several words here'})).status_code == 400
        _enable(repo, {'tokenLimit': 20, 'charLimit': 20})
        assert (await client.delete('/api/memories/style')).status_code == 200
        assert (await client.delete('/api/memories/second')).status_code == 200
        agent = AgentRepository(db).create('local', {'name': 'Agent A', 'provider': 'openAI', 'model': 'dummy'})
        agent_id = agent['id']
        response = await client.post('/api/memories', json={'key': 'note', 'value': 'Value', 'agentId': agent_id})
        assert response.status_code == 201
        assert (await client.get('/api/memories')).json()['memories'][0]['agentName'] == 'Agent A'
        assert (await client.patch('/api/memories/id/' + response.json()['memory']['_id'],
                                   params={'agentId': 'z' * 129}, json={'value': 'Modified'})).status_code == 400
        assert (await client.patch('/api/memories/id/' + response.json()['memory']['_id'],
                                   params={'agentId': 'unknown'}, json={'value': 'Modified'})).status_code == 404
        assert (await client.delete('/api/memories/note', params={'agentId': agent_id})).status_code == 200
        assert (await client.delete('/api/memories/note', params={'agentId': agent_id})).status_code == 404


def test_http_write_helper_preserves_rollback_on_synthetic_failures(state):
    db, repo = state
    store = MemoryRepository(db)
    from starlette.exceptions import HTTPException
    for exception, expected in ((FileExistsError('dup'), 409), (KeyError('gone'), 404),
                                (OverflowError('quota'), 400), (ValueError('bad'), 400)):
        with patch.object(store, 'write', side_effect=exception):
            with pytest.raises(HTTPException) as caught:
                _write(store, 'local', {}, 'style', 'Hello')
            assert caught.value.status_code == expected
