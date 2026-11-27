"""Automatic Memory/Skill prompt fragments are durable conversation snapshots."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import lsm_tool_registry, skill_runtime
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.compaction import build_summary_carrier_text
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import MemoryRepository
from local_shell_mcp.webui.prompt_snapshots import automatic_context
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository, _now


@pytest.fixture
def database(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(lsm_tool_registry, 'available_tools', lambda *a, **kw: [])
    monkeypatch.setattr(skill_runtime, 'list_installed_skills', lambda: {'skills': []})
    get_settings.cache_clear()
    yield SQLiteDatabase(tmp_path / 'state')
    get_settings.cache_clear()


def add_skill(database, identity, body):
    with database.connect() as conn:
        now = _now()
        conn.execute(
            'INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            (identity, 'alice', identity, json.dumps({
                'description': body, 'body': body, 'alwaysApply': True,
            }), now, now),
        )


async def capture(database, generation, *, history=None, agent=None):
    store = GenerationStore(database)
    captured = []

    async def model(profile, messages, **kwargs):
        captured.append(messages)
        yield 'Done'

    async def send(_):
        pass

    runner = AgentRunner('alice', generation, database, store, scopes=set(),
                         grant_expires=None, stream_tools=model, stream_text=model,
                         on_text=send, agent=agent,
                         profile=ProviderConfig('openai', 'mock', 'http://example.test/v1', ''))
    if history is None:
        history = store.history('alice', generation.conversation_id,
                                message_id=generation.user_message_id)
    await runner.run(history)
    assert captured
    assert store.finish('alice', generation.run_id, status='complete', text='Done')
    return captured[0]


@pytest.mark.asyncio
async def test_memory_and_skill_crud_keep_exact_prompt_prefix(database):
    memory = MemoryRepository(database)
    memory.write('alice', 'style', 'Original memory')
    add_skill(database, 'initial-skill', 'Original Skill body')
    store = GenerationStore(database)
    first, _ = store.begin('alice', {'text': 'first request'})
    prefix = await capture(database, first)
    assert 'Original memory' in str(prefix)
    assert 'Original Skill body' in str(prefix)

    memory.write('alice', 'style', 'Edited memory')
    memory.write('alice', 'added', 'Added memory')
    with database.connect() as conn:
        conn.execute("UPDATE webui_skills SET record=? WHERE id='initial-skill'",
                     (json.dumps({'description': 'Edited Skill', 'body': 'Edited Skill'}),))
    add_skill(database, 'added-skill', 'Added Skill')
    # Reopen the Controller database: no in-process cache can satisfy this test.
    database = SQLiteDatabase(database.root)
    store = GenerationStore(database)
    follow, _ = store.begin('alice', {'conversationId': first.conversation_id,
                                      'text': 'different query'})
    after_edit = await capture(database, follow)
    assert after_edit[:len(prefix)] == prefix

    MemoryRepository(database).delete('alice', key='style')
    with database.connect() as conn:
        conn.execute("DELETE FROM webui_skills WHERE id='initial-skill'")
    third, _ = store.begin('alice', {'conversationId': first.conversation_id,
                                     'text': 'third query'})
    after_delete = await capture(database, third)
    assert after_delete[:len(after_edit)] == after_edit
    assert 'Added memory' not in str(after_delete)
    assert 'Added Skill' not in str(after_delete)
    new, _ = store.begin('alice', {'text': 'new conversation'})
    fresh = await capture(database, new)
    assert 'Added memory' in str(fresh)
    assert 'Added Skill' in str(fresh)
    assert 'Original memory' not in str(fresh)
    assert 'Original Skill body' not in str(fresh)


@pytest.mark.asyncio
async def test_empty_fragments_are_frozen_and_summary_stays_separate(database):
    store = GenerationStore(database)
    first, _ = store.begin('alice', {'text': 'first'})
    original = await capture(database, first)
    MemoryRepository(database).write('alice', 'added', 'New memory')
    add_skill(database, 'new', 'New Skill')
    follow, _ = store.begin('alice', {'conversationId': first.conversation_id,
                                      'text': 'second'})
    messages = await capture(database, follow)
    assert messages[:len(original)] == original
    summary = build_summary_carrier_text('earlier turns')
    third, _ = store.begin('alice', {'conversationId': first.conversation_id,
                                     'text': 'continue'})
    messages = await capture(database, third, history=[
        {'role': 'system', 'content': summary},
        {'role': 'user', 'content': 'continue'},
    ])
    assert {'role': 'system', 'content': summary} in messages
    assert 'Use memory proactively' in str(messages)
    assert 'New memory' not in str(messages)
    assert 'New Skill' not in str(messages)


def test_snapshot_scope_owner_and_project_boundaries(database):
    repo = WorkspaceRepository(database)
    cid = repo.create_conversation('alice', {})['conversationId']

    def read(agent, value, owner='alice'):
        return automatic_context(database, owner, cid, cid, agent, 'memory', lambda: value)

    assert read(None, 'shared') == 'shared'
    assert read(None, 'changed') == 'shared'
    assert read(None, 'foreign', owner='bob') == ''
    private = {'id': 'private', 'memory_scope': 'agent'}
    assert read(private, 'private') == 'private'
    assert read({'id': 'another', 'memory_scope': 'agent'}, 'another') == 'another'
    project = repo.create_project('alice', 'New project', '')
    repo.update_conversation('alice', cid, {'projectId': project['id']})
    assert read(None, 'new project') == 'new project'
    repo.delete_conversation('alice', cid)
    with database.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM webui_prompt_snapshots').fetchone()[0] == 0
