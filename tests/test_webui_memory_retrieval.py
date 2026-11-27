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

def test_detached_child_conversations_are_not_history_sources(state):
    db, workspace, memory = state
    current = chat(workspace)
    project = workspace.create_project('alice', 'private project')['id']
    parent = chat(workspace, projectId=project)
    child = chat(workspace)
    message(workspace, child, 'Confidential detached project transcript')
    with db.connect() as conn:
        conn.execute('UPDATE conversations SET metadata=? WHERE id=?',
                     (json.dumps({'subagentTask': 'child-task', 'parentConversationId': parent}), child))
    result = retrieve(memory, 'alice', '', query='Confidential detached',
                      include_conversations=True, conversation_id=current)
    assert result['results'] == []
    assert 'Confidential' not in recall_context(memory, 'alice', '', query='Confidential detached',
                                               conversation_id=current, filters=None)


def test_bilingual_terms_nfkc_and_exact_identifiers(state):
    _, _, memory = state
    memory.write('alice', 'worker', '远程机器长轮询每隔25秒，心跳间隔12秒。')
    memory.write('alice', 'version', '已发布 v6.0.4.')
    memory.write('alice', 'version_other', '已发布 v6.0.40')
    memory.write('alice', 'function', 'job_tail 允许读取后台任务输出。')
    memory.write('alice', 'function_other', 'job_tail_extra 允许执行其他操作。')
    memory.write('alice', 'compatibility', 'ＡＰＩ access; Straße')

    def keys(query):
        return [row['key'] for row in retrieve(memory, 'alice', '', query=query)['results']]

    assert keys('远程轮询')[0] == 'worker'
    assert keys('ｖ６．０．４')[0] == 'version'
    assert keys('job_tail')[0] == 'function'
    assert keys('api')[0] == 'compatibility'
    assert keys('STRASSE')[0] == 'compatibility'
    assert keys('function_other')[0] == 'function_other'


def test_idf_weights_distinguish_generic_matches(state):
    _, _, memory = state
    # All records share generic words; only one contains the rare term.
    memory.write('alice', 'target', 'mutex prevents duplicate processes')
    for index, suffix in enumerate(('a', 'b', 'c', 'd', 'e', 'f')):
        memory.write('alice', 'generic_' + suffix, f'worker service status {index}')
    found = retrieve(memory, 'alice', '', query='worker service mutex')['results']
    assert found[0]['key'] == 'target'
    # An empty query retains the original listing/pagination contract.
    assert len(retrieve(memory, 'alice', '', limit=2)['results']) == 2
    assert retrieve(memory, 'alice', '', limit=2)['next_page'] == 2


@pytest.mark.parametrize('fts', [True, False])
def test_history_candidates_prioritize_relevance_before_limit(state, fts, monkeypatch):
    from local_shell_mcp.webui import memory_retrieval

    db, workspace, memory = state
    if fts and not db.fts_enabled:
        pytest.skip('SQLite FTS5 unavailable')
    db.fts_enabled = fts
    monkeypatch.setattr(memory_retrieval, '_MAX_CANDIDATES', 5)
    current, previous = chat(workspace), chat(workspace)
    old = message(workspace, previous, 'worker restart mutex deadlock solution')
    for i in range(12):
        message(workspace, previous, f'worker status poll active {i}')
    # Relevant foreign rows must not be able to exhaust the candidate budget.
    foreign = chat(workspace, 'bob')
    for _ in range(8):
        message(workspace, foreign, 'worker restart mutex deadlock solution', owner='bob')
    with db.connect() as conn:
        conn.execute('UPDATE messages SET created_at=? WHERE id=?',
                     (int((time.time() - 365 * 86400) * 1e6), old))
    result = retrieve(memory, 'alice', '', query='worker restart mutex',
                      include_conversations=True, conversation_id=current)
    assert result['results'][0]['message_id'] == old
    assert result['conversation_candidate_limit'] == 5
    assert len(result['results']) == 5
    assert all(row['conversation_id'] == previous for row in result['results'])


@pytest.mark.parametrize('fts', [True, False])
def test_history_short_terms_compatibility_and_original_snippets(state, fts):
    db, workspace, memory = state
    if fts and not db.fts_enabled:
        pytest.skip('SQLite FTS5 unavailable')
    db.fts_enabled = fts
    current, previous = chat(workspace), chat(workspace)
    # The two Chinese bigrams are not a contiguous trigram in the document.
    chinese = message(workspace, previous, '远程机器长轮询每隔25秒。')
    text = '无关背景。' * 600 + 'ＡＰＩ access; Straße' + ' 后续内容。' * 300
    unicode_id = message(workspace, previous, text)
    message(workspace, previous, 'apiary means a place for bees')

    def search(query):
        return retrieve(memory, 'alice', '', query=query, include_conversations=True,
                        conversation_id=current)['results']

    assert search('远程轮询')[0]['message_id'] == chinese
    for query in ('API', 'ＳＴＲＡＳＳＥ'):
        result = search(query)[0]
        assert result['message_id'] == unicode_id
        assert 'ＡＰＩ access; Straße' in result['text']
        assert len(result['text']) <= 1402
    # Exact FTS candidates and fallback candidates must be deduplicated.
    normal = message(workspace, previous, '远程轮询已恢复。')
    ids = [entry['message_id'] for entry in search('远程轮询')]
    assert ids.count(normal) == 1
    assert ids[0] == normal


def test_fts_runtime_failure_falls_back_to_scoped_ranking(state):
    db, workspace, memory = state
    if not db.fts_enabled:
        pytest.skip('SQLite FTS5 unavailable')
    current, previous = chat(workspace), chat(workspace)
    expected = message(workspace, previous, 'worker restart mutex')
    with db.connect() as conn:
        conn.execute('DROP TABLE message_search')
    found = retrieve(memory, 'alice', '', query='worker restart', include_conversations=True,
                     conversation_id=current)
    assert found['results'][0]['message_id'] == expected


@pytest.mark.parametrize('fts', [True, False])
def test_history_prefilter_keeps_short_ascii_and_normalized_unicode_matches(state, fts):
    db, workspace, memory = state
    if fts and not db.fts_enabled:
        pytest.skip('SQLite FTS5 unavailable')
    db.fts_enabled = fts
    current, previous = chat(workspace), chat(workspace)
    indexed = message(workspace, previous, 'worker restart')
    short_ascii = message(workspace, previous, 'Go language')
    short_unicode = message(workspace, previous, 'ＧＯ语言')
    compatible = message(workspace, previous, 'ＡＰＩ endpoint')
    folded = message(workspace, previous, 'Straße')
    message(workspace, previous, 'ongoing apiary')

    def ids(query):
        return {row['message_id'] for row in retrieve(
            memory, 'alice', '', query=query, include_conversations=True,
            conversation_id=current)['results']}

    # The short-token channel must still find ASCII and Unicode rows that
    # have no indexed match for the longer term.
    assert ids('worker Go') == {indexed, short_ascii, short_unicode}
    assert ids('API') == {compatible}
    assert ids('STRASSE') == {folded}


def test_fts_substring_false_positives_do_not_exhaust_candidates(state, monkeypatch):
    from local_shell_mcp.webui import memory_retrieval

    db, workspace, memory = state
    if not db.fts_enabled:
        pytest.skip('SQLite FTS5 unavailable')
    monkeypatch.setattr(memory_retrieval, '_MAX_CANDIDATES', 5)
    current, previous = chat(workspace), chat(workspace)
    for _ in range(12):
        message(workspace, previous, 'apiary')
    target = message(workspace, previous, 'API configuration ' + 'deployment notes ' * 100)
    assert [row['message_id'] for row in retrieve(
        memory, 'alice', '', query='api', include_conversations=True,
        conversation_id=current)['results']] == [target]


@pytest.mark.parametrize('text', [
    'go restart', 'ongoing go2 go_2', 'restartgo', '中文go测试',
    'go中文restart', 'égo', 'goé', 'go²', 'GO', 'ＧＯ', 'go\u0301',
    'Straße, API, job_tail', 'go ' * 1000,
])
def test_fast_word_matching_preserves_tokenizer_boundaries(text):
    from local_shell_mcp.webui.memory_retrieval import _CJK, _WORD, _word_hit, normalize

    text = normalize(text)
    words = set(_WORD.findall(_CJK.sub(' ', text)))
    for token in ('go', 'restart', 'strasse', 'api', 'job', 'tail'):
        assert _word_hit(text, token) == (token in words)
