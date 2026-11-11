"""Source-protocol Memory integration/transaction/offline regression cases."""
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase, shared_database
from local_shell_mcp.webui import memory_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import (
    MemoryRepository,
    agent_partition,
    execute_memory_tool,
    format_memory_context,
    memory_enabled,
    tool_definitions,
)
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.tokenizer import _encoding, count_tokens


@pytest.fixture
def db(tmp_path):
    return SQLiteDatabase(tmp_path / '.local-shell-mcp')


@pytest.fixture
def appdb(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir)
    from local_shell_mcp.webui.storage import WorkspaceRepository
    repo = WorkspaceRepository(database)
    repo.save_setting('local', 'endpoints', {'memory': {'tokenLimit': 35, 'charLimit': 10000},
                                          'agents': {'capabilities': ['memory']}})
    yield database, repo
    get_settings.cache_clear()


def test_memory_atomic_owner_partition_and_replacement(db):
    m = MemoryRepository(db)
    original = m.write('first', 'style', 'I prefer concise responses.', token_limit=10)
    assert original['tokenCount'] == count_tokens(original['value'], exact=False)
    assert m.formatted('first')['totalTokens'] == original['tokenCount']
    replacement = m.write('first', 'style', 'A short answer.', token_limit=10)
    assert replacement['_id'] == original['_id']
    agent = m.write('first', 'style', 'Answer with detail.', agent_id='agent_a')
    assert m.list('first', '')[0]['value'] == 'A short answer.'
    assert m.list('first', 'agent_a')[0]['_id'] == agent['_id']
    assert not m.list('second')
    assert not m.delete('second', key='style')
    assert not m.delete('first', entry_id=agent['_id'], agent_id='')
    assert m.list('first', 'agent_a')[0]['value'] == 'Answer with detail.'
    # Same DB after restarting the controller, without reinitializing schema.
    reopened = MemoryRepository(SQLiteDatabase(db.root))
    assert reopened.list('first', '')[0]['value'] == 'A short answer.'
    assert 'key' in reopened.formatted('first')['withKeys']


def test_memory_rename_conflicts_rollback_and_delete(db):
    m = MemoryRepository(db)
    a = m.write('a', 'first_key', 'Original value.')
    b = m.write('a', 'second_key', 'Other value.')
    with pytest.raises(FileExistsError):
        m.write('a', 'second_key', 'Overwrite.', existing_id=a['_id'])
    assert {x['key']: x['value'] for x in m.list('a')} == {'first_key': 'Original value.', 'second_key': 'Other value.'}
    changed = m.write('a', 'renamed', 'New value.', existing_id=a['_id'])
    assert changed['_id'] == a['_id'] and m.list('a', '')[0]['key'] in {'renamed', 'second_key'}
    with pytest.raises(KeyError):
        m.write('b', 'stolen', 'No.', existing_id=b['_id'])
    assert not m.delete('b', entry_id=b['_id'])
    assert m.delete('a', entry_id=b['_id'])
    assert m.delete_all('a') == 1


def test_memory_limit_concurrent_writes_and_reserved_keys(db):
    m = MemoryRepository(db)
    with pytest.raises(ValueError):
        m.write('a', 'Invalid', 'Value')
    with pytest.raises(ValueError):
        m.write('a', 'nothing', 'Value')
    with pytest.raises(ValueError):
        m.write('a', 'valid', '')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda n: _write_capped(m, n), range(8)))
    assert sum(result is True for result in results) <= 2
    assert m.formatted('a')['totalTokens'] <= 5


def _write_capped(store, n):
    try:
        store.write('a', 'key_' + chr(97 + n), 'Some text.', token_limit=5)
        return True
    except OverflowError:
        return False


def test_memory_format_definitions_and_tool_artifacts(db):
    m = MemoryRepository(db)
    assert format_memory_context(None) is None
    assert format_memory_context('')
    assert format_memory_context('known').endswith('known')
    defs = tool_definitions(['style', 'notes'])
    assert [d['function']['name'] for d in defs] == ['set_memory', 'delete_memory']
    assert 'Must be one of' in defs[0]['function']['parameters']['properties']['key']['description']
    assert agent_partition({'id': 'agent_a____1', 'memory_scope': 'agent'}) == 'agent_a'
    agent = {'id': 'agent_a', 'memory_scope': 'agent'}
    message, artifact = execute_memory_tool(m, 'a', agent, 'set_memory',
                                            {'key': 'style', 'value': 'I use Markdown.'}, {'validKeys': ['style']})
    assert message.startswith('Memory set for key') and artifact['memory']['agentId'] == 'agent_a'
    assert 'Invalid key' in execute_memory_tool(m, 'a', agent, 'set_memory',
                                              {'key': 'other', 'value': 'no'}, {'validKeys': ['style']})[0]
    assert m.list('a', 'agent_a')[0]['key'] == 'style'
    assert execute_memory_tool(m, 'a', agent, 'delete_memory', {'key': 'style'}, {})[1]['memory']['type'] == 'delete'
    assert m.list('a', 'agent_a') == []


@pytest.mark.asyncio
async def test_memory_http_crud_preference_and_partitions(appdb):
    database, repo = appdb
    app = Starlette(routes=memory_routes.memory_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as cli:
        created = await cli.post('/api/memories', json={'key': 'style', 'value': 'I like concise answers.'})
        assert created.status_code == 201, created.text
        memory_id = created.json()['memory']['_id']
        assert (await cli.post('/api/memories', json={'key': 'style', 'value': 'duplicate'})).status_code == 409
        got = (await cli.get('/api/memories')).json()
        assert got['memories'][0]['_id'] == memory_id and got['totalTokens'] > 0
        changed = await cli.patch('/api/memories/id/' + memory_id,
                                  json={'key': 'answer_style', 'value': 'I like detailed answers.'})
        assert changed.status_code == 200 and changed.json()['memory']['_id'] == memory_id
        assert (await cli.delete('/api/memories/style')).status_code == 404
        assert (await cli.patch('/api/memories/preferences', json={'memories': False})).status_code == 200
        assert not memory_enabled(repo, 'local')
        # Opting out cannot block the route needed to opt back in.
        assert (await cli.patch('/api/memories/preferences', json={'memories': True})).status_code == 200
        assert memory_enabled(repo, 'local')
        assert (await cli.delete('/api/memories/id/' + memory_id)).status_code == 200
        assert (await cli.get('/api/memories')).json()['memories'] == []
        agent = AgentRepository(database).create('local', {'name': 'Writer', 'provider': 'openAI', 'model': 'test'})
        row = await cli.post('/api/memories', json={'key': 'response_style', 'value': 'Use lists.', 'agentId': agent['id']})
        assert row.status_code == 201, row.text
        assert (await cli.get('/api/memories')).json()['totalTokens'] == 0
        assert (await cli.patch('/api/memories/id/' + row.json()['memory']['_id'],
                                params={'agentId': 'wrong'}, json={'value': 'not mine'})).status_code == 404
        assert (await cli.delete('/api/memories/response_style', params={'agentId': agent['id']})).status_code == 200
        assert (await cli.post('/api/memories', json={'key': 'BAD', 'value': 'no'})).status_code == 400


@pytest.mark.asyncio
async def test_memory_runner_calls_its_tools_and_restores_from_durable_sqlite(appdb, monkeypatch):
    database, settings = appdb
    agent = AgentRepository(database).create('local', {
        'name': 'Rememberer', 'provider': 'openAI', 'model': 'test',
        'tools': ['memory'], 'memory_scope': 'agent',
    })
    store = GenerationStore(database)
    generation, _ = store.begin('local', {'text': 'Remember I prefer short replies.'}, agent)
    seen = []

    async def stream_tools(profile, history, **kwargs):
        seen.append((history, kwargs['tools']))
        if not any(message.get('role') == 'tool' for message in history):
            yield ModelToolCall('memory-call', 'set_memory', {'key': 'style', 'value': 'The user prefers short replies.'})
        else:
            yield 'Saved.'

    async def stream_text(*args, **kwargs):
        yield 'fallback'

    async def emit(_):
        pass

    profile = ProviderConfig('openai', 'test', 'https://test.invalid', '')
    runner = AgentRunner('local', generation, database, store, scopes=set(), grant_expires=None,
                         stream_tools=stream_tools, stream_text=stream_text, on_text=emit, agent=agent, profile=profile)
    result = await runner.run(store.history('local', generation.conversation_id))
    assert result[-1]['content'] == 'Saved.'
    assert 'set_memory' in [t['function']['name'] for t in seen[0][1]]
    assert any('Persistent memory' in m.get('content','') for m in seen[0][0] if isinstance(m.get('content'), str))
    assert MemoryRepository(database).list('local', agent['id'])[0]['key'] == 'style'
    assert MemoryRepository(SQLiteDatabase(database.root)).list('local', agent['id'])[0]['value'] == 'The user prefers short replies.'
    assert 'memory' in runner.memory_artifacts['memory-call']


def test_offline_tokenizer_never_downloads_and_parity(monkeypatch):
    import tiktoken
    from tiktoken.load import load_tiktoken_bpe
    reference = tiktoken.get_encoding('o200k_base')
    original = load_tiktoken_bpe
    def guarded(path, *args, **kwargs):
        assert not path.startswith('http')
        return original(path, *args, **kwargs)
    monkeypatch.setattr('tiktoken.load.load_tiktoken_bpe', guarded)
    _encoding.cache_clear()
    for value in ('hello world', '南京大学', 'a'*400, 'Multilingual: 你好, world!'):
        assert count_tokens(value) == len(reference.encode(value))
