"""Checkpoint text boundary and repeated context-size regression tests."""

from __future__ import annotations

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


def test_checkpoint_preserves_visible_text_but_replays_only_unsummarized_suffix(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    run, _ = store.begin('local', {'text': 'Write a report'})
    text = 'Pre-checkpoint explanation. Final short answer.'
    assert store.stage_summary('local', run.run_id, 'Summary of the earlier explanation.', 20,
                               visible_text_boundary=len('Pre-checkpoint explanation. ')) is None
    assert store.finish('local', run.run_id, status='complete', text=text)
    last = store.events('local', run.run_id)[-1][1]['responseMessage']
    assert last['text'] == text
    assert next(part for part in last['content'] if part['type'] == 'text')['text'] == text
    history = store.history('local', run.conversation_id)
    assert history[0]['role'] == 'system' and 'Summary of the earlier explanation' in history[0]['content']
    assert [part['content'] for part in history if part['role'] == 'assistant'] == ['Final short answer.']
    with pytest.raises(ValueError, match='boundary'):
        store.stage_summary('local', run.run_id, 'A valid summary', 4, visible_text_boundary=-1)


@pytest.mark.asyncio
async def test_identical_history_size_can_compact_again_after_checkpoint(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    run, _ = store.begin('local', {'text': 'Reduce context'})
    WorkspaceRepository(db).save_setting('local', 'endpoints', {
        'summarization': {'enabled': True, 'retainRecent': {'turns': 0}},
        'agents': {'maxContextTokens': 120},
    })
    profile = ProviderConfig('openai', 'mock', 'https://example.invalid/v1/chat/completions', '')
    calls = []

    async def summarize(_profile, messages, **kwargs):
        calls.append(messages)
        yield 'Condensed state.'

    async def unused(*args, **kwargs):
        if False:
            yield None

    async def noop(_):
        return None

    runner = AgentRunner('local', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=unused, stream_text=summarize, on_text=noop, profile=profile)
    initial = [{'role': 'user', 'content': 'First query ' * 150},
               {'role': 'assistant', 'content': 'Tool in progress'},
               {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'First result ' * 150}]
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 120}), initial)
    await runner._before_model(state)
    assert len(calls) == 1
    assert runner._last_compaction_attempt_size is None
    assert len(state.messages) == 1
    state.messages.extend([
        {'role': 'assistant', 'content': 'Tool continuing'},
        {'role': 'tool', 'tool_call_id': 'call-2', 'content': 'Second result ' * 150},
    ])
    assert len(state.messages) == len(initial)
    await runner._before_model(state)
    assert len(calls) == 2
    assert state.messages[0]['content'].startswith('<summary>')


def test_multiple_checkpoints_keep_cumulative_covered_tool_ids(tmp_path):
    import json

    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    run, _ = store.begin('local', {'text': 'Summarize two tool results'})
    for i in (1, 2):
        store.append('local', run.run_id, {'event': 'on_run_step_completed', 'data': {
            'result': {'id': f'step-{i}', 'type': 'tool_call', 'tool_call': {
                'id': f'call-{i}', 'name': 'run_shell', 'args': {}, 'output': f'old tool output {i}'}}}})
        store.stage_summary('local', run.run_id, f'Summary after tool {i}.', 10,
                            covered_tool_call_ids=[f'call-{i}'])
    with db.connect() as conn:
        checkpoint = json.loads(conn.execute('SELECT state FROM runs WHERE id=?',
                                             (run.run_id,)).fetchone()['state'])['summaryCheckpoint']
    assert checkpoint['coveredToolCallIds'] == ['call-1', 'call-2']
    assert store.finish('local', run.run_id, status='complete', text='Final conclusion')
    history = store.history('local', run.conversation_id)
    assert all(msg.get('tool_call_id') not in {'call-1', 'call-2'} for msg in history)
    assert 'Summary after tool 2.' in history[0]['content']
