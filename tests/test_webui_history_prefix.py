"""Provider history remains stable until explicit context compaction."""
from __future__ import annotations

import copy
import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, run_agent_loop
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def history_state(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    job, _ = store.begin('alice', {'text': 'Use a tool'})
    profile = ProviderConfig('openai', 'mock-model', 'http://127.0.0.1:9000/chat', '')
    yield db, store, job, profile
    get_settings.cache_clear()


def _history():
    return [
        {'role': 'user', 'content': 'Read a very large file.'},
        {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'large-call', 'type': 'function', 'function': {
                'name': 'file_read', 'arguments': json.dumps({'path': '/tmp/' + 'x' * 5000}),
            },
        }]},
        {'role': 'tool', 'tool_call_id': 'large-call', 'content': 'large data ' * 7000},
        {'role': 'assistant', 'content': 'I read the tool output.'},
        {'role': 'user', 'content': 'Summarize the contents.'},
    ]


@pytest.mark.asyncio
async def test_history_prefix_stays_stable_under_context_pressure(history_state):
    db, store, job, profile = history_state
    WorkspaceRepository(db).save_setting('alice', 'endpoints', {
        'summarization': {'enabled': False}, 'agents': {'maxContextTokens': 512}})
    observed = []

    async def stream(config, messages, **kwargs):
        observed.append(copy.deepcopy(messages))
        yield 'Answered the final question.'

    async def emit(_):
        pass

    runner = AgentRunner('alice', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=stream, stream_text=stream, on_text=emit, profile=profile)
    original = _history()
    state = AgentLoopState(AgentContext(profile, [], parameters={'max_context_tokens': 512}),
                           copy.deepcopy(original))
    prefix = copy.deepcopy(runner._project_model_messages(state))
    await run_agent_loop(state, stream_tools=stream, stream_text=stream,
        dispatch=lambda *args: None, on_text=emit, before_model=runner._before_model,
        project_messages=runner._project_model_messages)
    assert observed
    tool_message = next(message for message in observed[0] if message['role'] == 'tool')
    assert tool_message['content'] == original[2]['content']
    assert observed[0] == prefix
    projected = runner._project_model_messages(state)
    assert projected[:len(prefix)] == prefix
    assert state.messages[2]['content'] == original[2]['content']
    assert state.messages[-1]['content'] == 'Answered the final question.'
    events = [event for _, event in store.events('alice', job.run_id)
              if event.get('event') == 'on_context_usage']
    assert events


@pytest.mark.asyncio
async def test_automatic_summary_replaces_history_only_at_checkpoint(history_state):
    db, store, job, profile = history_state
    WorkspaceRepository(db).save_setting('alice', 'endpoints', {
        'summarization': {'enabled': True, 'retainRecent': {'turns': 1}},
        'agents': {'maxContextTokens': 512}})

    async def summary(*args, **kwargs):
        yield '## Checkpoint\nRetain the topic.'

    async def emit(_):
        pass

    runner = AgentRunner('alice', job, db, store, scopes=set(), grant_expires=None,
        stream_tools=summary, stream_text=summary, on_text=emit, profile=profile)
    originals = _history()
    state = AgentLoopState(AgentContext(profile, [], parameters={'max_context_tokens': 512}),
                           copy.deepcopy(originals))
    await runner._before_model(state)
    assert any(message.get('role') == 'system' and '<summary>' in str(message.get('content'))
               for message in state.messages)
    assert len(state.messages) < len(originals) + 1


def test_upgrade_removes_only_obsolete_compression_metadata(history_state):
    db, store, job, _ = history_state
    with db.connect() as conn:
        conn.execute("PRAGMA user_version=1")
        conn.execute("UPDATE runs SET state=json_set(state, '$.fadingTiers', json('{}'), "
                     "'$.preserve', 'run') WHERE id=?", (job.run_id,))
        conn.execute("UPDATE conversations SET metadata=json_set(metadata, '$.fadingTiers', json('{}'), "
                     "'$.preserve', 'conversation') WHERE id=?", (job.conversation_id,))
    history = store.history('alice', job.conversation_id)
    reopened = SQLiteDatabase(db.root)
    with reopened.connect() as conn:
        state = json.loads(conn.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0])
        metadata = json.loads(conn.execute("SELECT metadata FROM conversations WHERE id=?",
                                           (job.conversation_id,)).fetchone()[0])
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert 'fadingTiers' not in state and state['preserve'] == 'run'
    assert 'fadingTiers' not in metadata and metadata['preserve'] == 'conversation'
    assert GenerationStore(reopened).history('alice', job.conversation_id) == history
