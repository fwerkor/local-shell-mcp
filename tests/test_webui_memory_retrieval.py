"""Recall reads only scoped, visible text and saved memory, with bounded injection."""
import json
import time

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.memory import MemoryRepository, execute_memory_tool
from local_shell_mcp.webui.memory_retrieval import recall_context, retrieve
from local_shell_mcp.webui.storage import WorkspaceRepository
from local_shell_mcp.webui.tokenizer import count_tokens


@pytest.fixture
def state(tmp_path):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    return db, WorkspaceRepository(db), MemoryRepository(db)


def chat(workspace, owner='alice', **fields):
    return workspace.create_conversation(owner, fields)['conversationId']


def message(workspace, cid, text, *, owner='alice', role='user', content=None):
    payload = {'role': role, 'text': text}
    if content is not None:
        payload['content'] = content
    return workspace.add_message(owner, cid, payload)['messageId']


def test_find_and_empty_value_deletion(state):
    _, _, memory = state
    memory.write('alice', 'coding_style', 'Use concise Go code.')
    memory.write('alice', 'private_style', 'Other scope', agent_id='agent_a')
    memory.write('bob', 'coding_style', 'Bob secret')
    result, artifact = execute_memory_tool(memory, 'alice', {}, 'find_memory',
        {'query': 'coding_style'}, {})
    assert artifact is None
    assert [r['key'] for r in json.loads(result)['results']] == ['coding_style']
    assert execute_memory_tool(memory, 'alice', {}, 'set_memory',
        {'key': 'coding_style'}, {})[1] is None
    assert len(memory.list('alice', '')) == 1
    assert execute_memory_tool(memory, 'alice', {}, 'set_memory',
        {'key': 'coding_style', 'value': ''}, {})[1]['memory']['type'] == 'delete'
    assert not memory.list('alice', '')
    assert len(memory.list('alice', 'agent_a')) == 1
    assert execute_memory_tool(memory, 'alice', {}, 'find_memory', {'page': -1}, {})[1] is None


@pytest.mark.parametrize('fts', [True, False])
def test_history_text_scope_chinese_and_pagination(state, fts):
    db, workspace, memory = state
    if not db.fts_enabled and fts:
        pytest.skip('SQLite FTS5 unavailable')
    db.fts_enabled = fts
    current = chat(workspace)
    previous = chat(workspace)
    older = chat(workspace)
    other = chat(workspace, 'bob')
    project = workspace.create_project('alice', 'project')['id']
    in_project = chat(workspace, projectId=project)
    disabled = chat(workspace)
    workspace.save_setting('alice', 'conversation.permissions.' + disabled, {'memory': False})
    agent = AgentRepository(db).create('alice', {
        'name': 'Private agent', 'provider': 'openAI', 'model': 'mock',
        'memory_scope': 'agent', 'tools': ['memory']})
    private = chat(workspace, agent_id=agent['id'])
    old_id = message(workspace, older, '数据库实验五：旧的方案')
    new_id = message(workspace, previous, '数据库实验五：新的方案', role='assistant',
                     content=[{'type': 'text', 'text': '数据库实验五：新的方案'},
                              {'type': 'tool_call', 'tool_call': {'output': 'SECRET TOOL'}}])
    # Explicit timestamps guarantee the recency test is deterministic.
    with db.connect() as connection:
        connection.execute('UPDATE messages SET created_at=? WHERE id=?',
                           (int((time.time()-90*86400)*1e6), old_id))
    message(workspace, previous, '数据库实验五 secret tool only', role='assistant',
            content=[{'type': 'tool_call', 'tool_call': {'output': '数据库实验五 secret tool only'}}])
    message(workspace, previous, '数据库实验五 secret role', role='tool')
    message(workspace, current, '数据库实验五 current')
    message(workspace, other, '数据库实验五 foreign', owner='bob')
    message(workspace, in_project, '数据库实验五 project')
    message(workspace, private, '数据库实验五 private')
    message(workspace, disabled, '数据库实验五 disabled')
    for page, expected in [(1, new_id), (2, old_id)]:
        found = retrieve(memory, 'alice', '', query='数据库实验五',
            include_conversations=True, conversation_id=current, page=page, limit=1)
        assert [r['message_id'] for r in found['results']] == [expected]
        assert found['next_page'] == (2 if page == 1 else None)
        assert 'SECRET TOOL' not in json.dumps(found)
    assert not retrieve(memory, 'alice', '', query='数据库实验五',
        conversation_id=current)['results']
    assert not retrieve(memory, 'alice', '', query='数据库实验五',
        include_conversations=True, conversation_id=other)['results']
    scoped = retrieve(memory, 'alice', agent['id'], query='数据库实验五',
        include_conversations=True, conversation_id=current)
    assert [r['conversation_id'] for r in scoped['results']] == [private]
    # A two-character query must also work with the trigram index enabled.
    assert retrieve(memory, 'alice', '', query='实验', include_conversations=True,
                    conversation_id=current)['results']


def test_recall_budget_and_live_filters(state):
    _, workspace, memory = state
    current = chat(workspace)
    previous = chat(workspace)
    memory.write('alice', 'style', 'Use concise Go code.')
    memory.write('alice', 'large', 'unrelated detail ' * 400)
    memory.write('alice', 'sensitive', 'Go PRIVATE-SECRET')
    message(workspace, previous, 'Go implementation in the previous conversation.')
    message(workspace, previous, 'Go PRIVATE-CHAT')
    filters = {'memories': {'pii': {'fields': ['value'], 'starterPatterns': [],
        'customPatterns': [{'id': 'secret', 'label': 'protected', 'regex': 'PRIVATE-[A-Z]+'}]}}}
    context = recall_context(memory, 'alice', '', query='Go', conversation_id=current,
                             filters=filters, budget=160)
    assert 'Use concise Go code.' in context
    assert 'previous conversation' in context
    assert 'PRIVATE-' not in context and 'unrelated detail' not in context
    assert count_tokens(context, exact=False) <= 160

@pytest.mark.parametrize('fts', [True, False])
def test_run_agent_history_scope_is_not_conversation_selection(state, fts):
    from local_shell_mcp.webui.generations import GenerationStore

    db, workspace, memory = state
    if not db.fts_enabled and fts:
        pytest.skip('SQLite FTS5 unavailable')
    db.fts_enabled = fts
    agents = AgentRepository(db)
    private = agents.create('alice', {
        'name': 'Private agent', 'provider': 'openAI', 'model': 'mock',
        'memory_scope': 'agent', 'tools': ['memory']})
    store = GenerationStore(db)
    current = chat(workspace)
    run, _ = store.begin('alice', {'text': 'Confidential project detail'}, private)
    assert store.finish('alice', run.run_id, status='complete', text='Confidential project response')
    with db.connect() as connection:
        assert connection.execute('SELECT agent_id FROM conversations WHERE id=?',
                                  (run.conversation_id,)).fetchone()[0] is None

    def search(partition=''):
        return retrieve(memory, 'alice', partition, query='Confidential project',
                        include_conversations=True, conversation_id=current)['results']

    assert search() == []
    assert {item['message_id'] for item in search(private['id'])} == {
        run.user_message_id, run.response_message_id}
    assert 'Confidential' not in recall_context(memory, 'alice', '', query='Confidential project',
                                               conversation_id=current, filters=None)
    # A subsequent public reply can quote private history, so a mixed chat
    # must not become a shared source, nor a purely private source.
    public, _ = store.begin('alice', {'conversationId': run.conversation_id,
                                      'text': 'Confidential project followup'})
    assert store.finish('alice', public.run_id, status='complete', text='Confidential project followup answer')
    assert search() == []
    assert search(private['id']) == []
    # A change to the current agent config does not declassify earlier turns.
    with db.connect() as connection:
        connection.execute("UPDATE agents SET config=json_set(config,'$.memory_scope','personal') WHERE id=?",
                           (private['id'],))
    assert search() == []
