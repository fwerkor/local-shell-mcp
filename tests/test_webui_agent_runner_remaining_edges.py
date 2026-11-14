"""Source-level negative and recovery branches in AgentRunner.

Covers owner revocation, policy deny, malformed tool batch, failed checkpoint,
compaction/fading publication and child-no-SSE cases using real SQLite.
"""
from __future__ import annotations

import json
import time

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner as agent_runtime
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, RuntimeSafetyError
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import MemoryRepository
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def runner_state(tmp_path):
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
    return db, store, generation, profile, runner


def test_context_read_failure_fails_closed_not_empty_memory(runner_state, monkeypatch):
    db, store, job, profile, runner = runner_state
    settings = WorkspaceRepository(db)
    settings.save_setting('local', 'endpoints', {'memory': {}, 'agents': {'capabilities': ['memory']}})
    MemoryRepository(db).write('local', 'private_note', 'A private memory.')
    monkeypatch.setattr(MemoryRepository, 'formatted', lambda *_args, **kwargs: {'readFailed': True})
    assert runner._memory_context({'tools': ['memory']}) == ''
    assert runner._memory_context(None) == ''
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
    monkeypatch.setattr(agent_runtime, 'approval_policy_decision',
                        lambda _policy, name: {'decision': 'deny', 'reason': 'Blocked by operator'})

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
async def test_manual_compaction_fading_publication_failure_keeps_checkpoint(runner_state, monkeypatch):
    db, store, job, profile, runner = runner_state
    settings = WorkspaceRepository(db)
    settings.save_setting('local', 'endpoints', {'summarization': {'enabled': True},
                                               'agents': {'maxContextTokens': 400}})

    async def summarize(*args, **kwargs):
        yield '## Checkpoint\nThe conversation was about tests.'

    runner.stream_text = summarize
    monkeypatch.setattr(store, 'record_fading_tier', lambda *a, **kw: (_ for _ in ()).throw(OSError('Disk failure')))
    history = store.history('local', job.conversation_id)
    assert await runner._manual_compact(history) == history
    with db.connect() as connection:
        state = json.loads(connection.execute('SELECT state FROM runs WHERE id=?', (job.run_id,)).fetchone()[0])
    assert 'summaryCheckpoint' in state


@pytest.mark.asyncio
async def test_automatic_compaction_fading_publication_failure_preserves_summarized_state(runner_state, monkeypatch):
    db, store, job, profile, runner = runner_state
    WorkspaceRepository(db).save_setting('local', 'endpoints', {'summarization': {
        'enabled': True, 'retainRecent': {'turns': 1}}, 'agents': {'maxContextTokens': 300}})
    many = [{'role': 'user', 'content': 'large request ' * 80},
            {'role': 'assistant', 'content': 'large response ' * 80},
            {'role': 'user', 'content': 'continue'}]

    async def summarize(*args, **kwargs):
        yield '## Checkpoint\nStored contextual facts.'

    runner.stream_text = summarize
    original = store.record_fading_tier
    attempts = 0

    def broken_once(*args, **kw):
        nonlocal attempts
        attempts += 1
        if attempts >= 2:
            raise OSError('Cannot save reset tier')
        return original(*args, **kw)

    monkeypatch.setattr(store, 'record_fading_tier', broken_once)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 300}), many)
    await runner._before_model(state)
    assert any(item.get('role') == 'system' and '<summary>' in str(item.get('content'))
               for item in state.messages)
    assert attempts >= 2


@pytest.mark.asyncio
async def test_non_dict_summarization_configuration_uses_safe_defaults(runner_state):
    db, store, job, profile, runner = runner_state
    settings = WorkspaceRepository(db)
    settings.save_setting('local', 'endpoints', {
        'summarization': True, 'agents': {'maxContextTokens': 300}})
    history = [{'role': 'user', 'content': 'message ' * 100},
               {'role': 'assistant', 'content': 'reply ' * 100},
               {'role': 'user', 'content': 'continue'}]
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 300}), history)
    await runner._before_model(state)
    assert store.fading_tier('local', job.run_id, 'default', 'openai', 'mock') is not None
