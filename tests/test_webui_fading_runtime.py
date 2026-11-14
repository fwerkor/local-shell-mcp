"""Fading budget v2 persistence and provider-only copy-on-write truncation."""
from __future__ import annotations

import copy
import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, run_agent_loop
from local_shell_mcp.webui.fading import create_fading_tier
from local_shell_mcp.webui.fading_projection import project_faded_provider_messages
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def fade_state(tmp_path):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    job, _ = store.begin('alice', {'text': 'Use a tool'})
    profile = ProviderConfig('openai', 'mock-model', 'http://127.0.0.1:9000/chat', '')
    return db, store, job, profile


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


def test_provider_view_truncation_preserves_full_source_and_pairing():
    original = _history()
    unchanged = copy.deepcopy(original)
    tier = {'v': 2, 'budgetTokens': 170, 'masked': True, 'latched': True}
    projected = project_faded_provider_messages(original, tier)
    assert original == unchanged
    assert projected != original
    assert len(projected[2]['content']) <= 300
    assert projected[2]['tool_call_id'] == 'large-call'
    arguments = json.loads(projected[1]['tool_calls'][0]['function']['arguments'])
    assert arguments['_originalChars'] > 5000
    assert len(projected[1]['tool_calls'][0]['function']['arguments']) <= 100
    assert original[2]['content'].endswith('large data ')
    assert project_faded_provider_messages(original, None) is original
    assert project_faded_provider_messages(original, {'v': 1, 'budgetTokens': 1000, 'masked': True}) is original


def test_fading_provider_projection_never_uses_invalid_truncated_json():
    tiny = {'v': 2, 'budgetTokens': 1, 'masked': True}
    source = [{'role': 'assistant', 'tool_calls': [{'id': 'a', 'function': {'arguments': 'abcde'*1000}}]},
              {'role': 'tool', 'tool_call_id': 'a', 'content': 'long'*5000}]
    messages = project_faded_provider_messages(source, tiny)
    assert json.loads(messages[0]['tool_calls'][0]['function']['arguments']) == {}
    assert len(messages[1]['content']) <= 1
    assert source[0]['tool_calls'][0]['function']['arguments'] == 'abcde'*1000
    assert source[1]['content'] == 'long'*5000


def test_saved_fading_tier_owner_and_model_scope_across_restart(fade_state):
    db, store, job, profile = fade_state
    tier = {'v': 2, 'budgetTokens': 500, 'masked': True, 'latched': True}
    assert store.fading_tier('alice', job.run_id, 'agent-a', 'openai', 'model') is None
    with pytest.raises(KeyError):
        store.fading_tier('bob', job.run_id, 'agent-a', 'openai', 'model')
    with pytest.raises(KeyError):
        store.record_fading_tier('bob', job.run_id, 'agent-a', 'openai', 'model', tier)
    with pytest.raises(ValueError):
        store.record_fading_tier('alice', job.run_id, 'agent-a', 'openai', 'model', {'v': 1})
    store.record_fading_tier('alice', job.run_id, 'agent-a', 'openai', 'model', tier)
    reopened = GenerationStore(SQLiteDatabase(db.root))
    assert reopened.fading_tier('alice', job.run_id, 'agent-a', 'openai', 'model') == tier
    assert reopened.fading_tier('alice', job.run_id, 'agent-b', 'openai', 'model') is None
    assert reopened.fading_tier('alice', job.run_id, 'agent-a', 'openai', 'other') is None
    assert store.finish('alice', job.run_id, status='complete', text='Done')
    with pytest.raises(KeyError):
        store.record_fading_tier('alice', job.run_id, 'agent-a', 'openai', 'model', tier)
    next_job, _ = store.begin('alice', {'text': 'next turn', 'conversationId': job.conversation_id,
                                        'parentMessageId': job.response_message_id})
    assert reopened.fading_tier('alice', next_job.run_id, 'agent-a', 'openai', 'model') == tier


@pytest.mark.asyncio
async def test_runtime_fading_reduces_provider_messages_only_and_keeps_checkpoints(fade_state):
    db, store, job, profile = fade_state
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
    await run_agent_loop(state, stream_tools=stream, stream_text=stream,
        dispatch=lambda *args: None, on_text=emit, before_model=runner._before_model,
        project_messages=runner._project_model_messages)
    assert state.context.fading_tier['masked'] is True
    assert store.fading_tier('alice', job.run_id, 'default', 'openai', 'mock-model') == state.context.fading_tier
    assert observed and len(observed[0][2]['content']) < len(original[2]['content'])
    assert state.messages[2]['content'] == original[2]['content']
    assert state.messages[-1]['content'] == 'Answered the final question.'
    events = [event for _, event in store.events('alice', job.run_id)
              if event.get('event') == 'on_context_usage']
    assert events


@pytest.mark.asyncio
async def test_source_summary_resets_v2_tier_after_checkpoint(fade_state):
    db, store, job, profile = fade_state
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
    assert state.context.fading_tier == create_fading_tier(512)
    assert store.fading_tier('alice', job.run_id, 'default', 'openai', 'mock-model') == create_fading_tier(512)
    assert any(message.get('role') == 'system' and '<summary>' in str(message.get('content'))
               for message in state.messages)
    assert len(state.messages) < len(originals) + 1


def test_fading_projection_handles_non_dict_parts_and_malformed_tool_declarations():
    payload = [None, 1, {'role': 'assistant', 'tool_calls': [
        None, {'id': 'missing'}, {'id': 'badargs', 'function': {'arguments': 1000}},
        {'id': 'short', 'function': {'arguments': '{}'}},
    ]}, {'role': 'tool', 'content': 'short'}, {'role': 'user', 'content': 'hello'}]
    tier = {'v': 2, 'budgetTokens': 256, 'masked': False}
    projected = project_faded_provider_messages(payload, tier)
    assert projected == payload and projected is not payload
    assert projected[0] is None and projected[1] == 1
    assert projected[3]['content'] == 'short'


def test_fading_projection_calibrated_provider_budget_and_escaped_json_arguments():
    original = [{'role': 'assistant', 'tool_calls': [{'function': {
        'arguments': '\\' * 5000}}]},
        {'role': 'tool', 'content': 'Z' * 5000},
        None, {'role': 'assistant', 'content': None},
        {'role': 'assistant', 'content': 'I completed the tool read.'}]
    rendered = project_faded_provider_messages(original, {
        'v': 2, 'budgetTokens': 2000, 'masked': True}, max_tool_result_chars=350)
    params = rendered[0]['tool_calls'][0]['function']['arguments']
    assert len(params) <= 1200
    assert json.loads(params)['_originalChars'] == 5000
    assert len(rendered[1]['content']) <= 350
    assert original[1]['content'] == 'Z' * 5000
    assert rendered[2] is None


def test_clip_bounded_head_and_tail_always_respect_cap():
    from local_shell_mcp.webui.fading_projection import _clip

    assert _clip('abc', 12) == 'abc'
    assert _clip('abcdef' * 30, 15).endswith('…')
    assert len(_clip('z' * 500, 40)) <= 40
    assert len(_clip('z' * 500, 5)) == 5
    assert _clip('z' * 500, 40) != 'z' * 500


@pytest.mark.asyncio
async def test_manual_compaction_resets_persisted_fading_hysteresis(fade_state):
    db, store, previous, profile = fade_state
    store.finish('alice', previous.run_id, status='complete', text='Original answer.')
    manual, _ = store.begin('alice', {'conversationId': previous.conversation_id,
        'parentMessageId': previous.response_message_id, 'compact': True})
    WorkspaceRepository(db).save_setting('alice', 'endpoints', {
        'summarization': {'enabled': True}, 'agents': {'maxContextTokens': 512}})
    store.record_fading_tier('alice', manual.run_id, 'default', 'openai', 'mock-model',
        {'v': 2, 'budgetTokens': 170, 'masked': True, 'latched': True})

    async def summary(*args, **kwargs):
        yield '## Checkpoint\nRestored the prior turn.'

    async def emit(_):
        pass

    runner = AgentRunner('alice', manual, db, store, scopes=set(), grant_expires=None,
        stream_tools=summary, stream_text=summary, on_text=emit, profile=profile)
    history = store.history('alice', previous.conversation_id)
    assert await runner.run(history) == history
    assert store.fading_tier('alice', manual.run_id, 'default', 'openai', 'mock-model') == create_fading_tier(512)
    assert store.finish('alice', manual.run_id, status='complete', text='')
    persisted = GenerationStore(SQLiteDatabase(db.root))
    assert persisted.fading_tier('alice', manual.run_id, 'default', 'openai', 'mock-model') == create_fading_tier(512)
