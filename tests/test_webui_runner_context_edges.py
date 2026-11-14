"""Negative AgentRunner memory and summarization paths for durable state."""
from __future__ import annotations

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import (
    AgentContext,
    AgentLoopState,
    RuntimeSafetyError,
)
from local_shell_mcp.webui.compaction import build_summary_carrier_text
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import MemoryRepository, tool_definitions
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def runtime(tmp_path):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    profile = ProviderConfig('openai', 'test', 'http://127.0.0.1:10000/v1/chat/completions', '')
    setting = WorkspaceRepository(db)
    job, _ = store.begin('a', {'text': 'initial message'})

    async def empty_stream(*args, **kwargs):
        if False:
            yield 'unused'

    async def emit(_):
        pass

    runner = AgentRunner('a', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=empty_stream, stream_text=empty_stream,
                         on_text=emit, profile=profile)
    return db, store, setting, profile, runner


def test_memory_context_is_agent_opt_in_and_errors_never_fake_empty(runtime, monkeypatch):
    db, _, repo, profile, runner = runtime
    assert runner._memory_context(None) == ''
    repo.save_setting('a', 'endpoints', {'memory': {'tokenLimit': 100},
                                       'agents': {'capabilities': ['memory']}})
    assert 'Persistent memory is available' in runner._memory_context(None)
    assert 'Persistent memory is available' in runner._memory_context({'id': 'a', 'tools': []})
    assert runner._memory_context({'id': 'a', 'tools': ['memory']}) == (
        runner._memory_context({'id': 'other', 'tools': ['memory']}))
    MemoryRepository(db).write('a', 'style', 'Speak concisely.')
    context = runner._memory_context({'id': 'a', 'tools': ['memory']})
    assert 'Speak concisely.' in context
    assert 'Only use the `set_memory`' in context
    repo.save_setting('a', 'user.memories', False)
    assert runner._memory_context({'id': 'a', 'tools': ['memory']}) == ''
    repo.save_setting('a', 'user.memories', True)
    repo.save_setting('a', 'endpoints', {'memory': {'tokenLimit': 100}, 'agents': {}})
    assert 'Persistent memory is available' in runner._memory_context({'id': 'a', 'tools': ['memory']})
    assert 'Only use the `set_memory`' not in runner._memory_context({'id': 'a', 'tools': ['memory']})


@pytest.mark.asyncio
async def test_memory_tool_requires_enabled_runtime_capability(runtime):
    db, store, repo, profile, runner = runtime
    tool = tool_definitions()[0]
    state = AgentLoopState(AgentContext(profile, [tool]), [{'role': 'user', 'content': 'Remember.'}])
    call = ModelToolCall('call-1', 'set_memory', {'key': 'style', 'value': 'I prefer concise responses.'})
    with pytest.raises(RuntimeSafetyError, match='disabled'):
        await runner._invoke(call, state)
    repo.save_setting('a', 'endpoints', {'memory': {}, 'agents': {'capabilities': ['memory']}})
    assert 'Memory set' in await runner._invoke(call, state)
    repo.save_setting('a', 'user.memories', False)
    with pytest.raises(RuntimeSafetyError, match='disabled'):
        await runner._invoke(call, state)


@pytest.mark.asyncio
async def test_summary_skips_manual_disabled_and_handles_update_prompt(runtime):
    db, store, repo, profile, runner = runtime
    initial = store.history('a', runner.generation.conversation_id)
    with pytest.raises(ValueError, match='Nothing to compact'):
        await runner._manual_compact([])
    with pytest.raises(ValueError, match='Nothing to compact'):
        await runner._manual_compact([{'role': 'system', 'content': 'Prior context'}])
    repo.save_setting('a', 'endpoints', {'summarization': {'enabled': False}})
    with pytest.raises(ValueError, match='disabled'):
        await runner._manual_compact(initial)
    repo.save_setting('a', 'endpoints', {'summarization': {'enabled': True}})

    captured = []

    async def summary(_profile, messages, **kwargs):
        captured.append(messages)
        yield 'Updated checkpoint.'

    runner.stream_text = summary
    prior = [{'role': 'system', 'content': build_summary_carrier_text('Prior summary')},
             {'role': 'user', 'content': 'New facts'}]
    result = await runner._summarize_history(prior, manual=False,
                                            prompt='Initial checkpoint.',
                                            update_prompt='Update this checkpoint.', head_count=1)
    assert result == 'Updated checkpoint.'
    assert '<previous-summary>\nPrior summary\n</previous-summary>' in captured[0][-1]['content']
    assert 'Update this checkpoint.' in captured[0][-1]['content']
    assert store.finish('a', runner.generation.run_id, status='complete', text='Done')
    assert store.history('a', runner.generation.conversation_id)[0]['role'] == 'system'


@pytest.mark.asyncio
async def test_summarization_invalid_tool_reply_is_not_checkpointed(runtime):
    db, store, repo, profile, runner = runtime

    async def tool_instead_of_text(*args, **kwargs):
        yield ModelToolCall('h', 'unknown', {'a': 1})

    runner.stream_text = tool_instead_of_text
    with pytest.raises(ValueError, match='tool call instead of text'):
        await runner._summarize_history([{'role': 'user', 'content': 'Long chat'}])
    assert not store.manual_compaction('a', runner.generation.run_id)
    with db.connect() as con:
        row = con.execute('SELECT state FROM runs WHERE id=?', (runner.generation.run_id,)).fetchone()
    assert 'summaryCheckpoint' not in row[0]


@pytest.mark.asyncio
async def test_budget_skips_are_read_only_and_do_not_call_summary(runtime):
    db, store, repo, profile, runner = runtime
    calls = []

    async def summary(*args, **kwargs):
        calls.append(True)
        yield 'summary'

    runner.stream_text = summary
    many = []
    for _i in range(5):
        many.extend([{'role': 'user', 'content': 'Detail ' * 70},
                     {'role': 'assistant', 'content': 'Other ' * 70}])
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 200}), many)
    repo.save_setting('a', 'endpoints', {'summarization': {'enabled': False}})
    await runner._before_model(state)
    assert calls == [] and state.messages == many
    repo.save_setting('a', 'endpoints', {'summarization': {
        'trigger': {'type': 'messages_to_refine', 'value': 9000}}})
    await runner._before_model(state)
    assert calls == [] and state.messages == many
    repo.save_setting('a', 'endpoints', {'summarization': {'enabled': True}})
    state.context.parameters = {'max_context_tokens': 300000}
    await runner._before_model(state)
    assert calls == []
    state.context.parameters = {'max_context_tokens': 200}
    state.messages = [{'role': 'system', 'content': 'Instructions ' * 3000}, *many]
    await runner._before_model(state)
    assert calls == [] and state.messages[0]['role'] == 'system'
    state.context.parameters = {'max_context_tokens': -1}
    await runner._before_model(state)
    assert calls == []
    runner.namespace = 'child'
    state.context.parameters = {'max_context_tokens': 200}
    await runner._before_model(state)
    assert calls == []
