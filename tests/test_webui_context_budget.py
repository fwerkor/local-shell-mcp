"""Context pressure, LLM checkpoint, durable history and negative recovery."""
import asyncio
import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState
from local_shell_mcp.webui.compaction import build_summary_carrier_text
from local_shell_mcp.webui.context_budget import (
    calculate_budget,
    message_token_count,
    should_trigger_summarization,
    split_recent_turns,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def ctx(tmp_path):
    database = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(database)
    repo = WorkspaceRepository(database)
    repo.save_setting('a', 'endpoints', {'summarization': {'enabled': True,
        'retainRecent': {'turns': 2}, 'parameters': {'maxSummaryTokens': 200}}})
    profile = ProviderConfig('openai', 'test', 'https://test.invalid/chat/completions', '')
    return database, store, repo, profile


def _conversation(store, owner='a', count=6, size=240):
    cid = None
    parent = None
    for index in range(count):
        body = {'text': f'User question {index} ' + ('context ' * size)}
        if cid:
            body.update({'conversationId': cid, 'parentMessageId': parent})
        generation, created = store.begin(owner, body)
        assert created
        assert store.finish(owner, generation.run_id, status='complete', text=f'Answer {index} ' + ('detail ' * 5))
        cid = generation.conversation_id
        parent = generation.response_message_id
    return generation


def test_context_budget_and_upstream_trigger_functions():
    messages = [{'role': 'system', 'content': 'System rules.'},
                {'role': 'user', 'content': 'hello world'},
                {'role': 'assistant', 'content': 'sure'}]
    budget = calculate_budget(messages, [], 1000)
    assert budget.max_context_tokens == 1000 and budget.reserve_tokens == 50
    assert budget.available_for_messages + budget.instruction_tokens == 950
    assert budget.message_tokens == sum(map(message_token_count, messages[1:]))
    assert should_trigger_summarization(messages_to_refine_count=1)
    assert not should_trigger_summarization(messages_to_refine_count=0)
    assert should_trigger_summarization(messages_to_refine_count=8,
                                       trigger={'type': 'messages_to_refine', 'value': 5})
    assert not should_trigger_summarization(messages_to_refine_count=3,
                                           trigger={'type': 'messages_to_refine', 'value': 5})
    assert should_trigger_summarization(messages_to_refine_count=3,
                                       trigger={'type': 'remaining_tokens', 'value': 100},
                                       remaining_context_tokens=50)
    assert should_trigger_summarization(messages_to_refine_count=3,
                                       trigger={'type': 'token_ratio', 'value': 0.9},
                                       max_context_tokens=1000, pre_prune_context_tokens=970)
    for trigger in ({'type': 'token_count', 'value': 10}, {'type': 'remaining_tokens', 'value': None},
                    {'type': 'token_ratio', 'value': '0.5'}):
        assert not should_trigger_summarization(messages_to_refine_count=3, trigger=trigger)


def test_pairing_and_recency_never_orphan_tool_results():
    messages = [
        {'role': 'user', 'content': 'first'},
        {'role': 'assistant', 'tool_calls': [{'id': 't1', 'type': 'function', 'function': {'name': 'search', 'arguments': '{}'}}], 'content': None},
        {'role': 'tool', 'tool_call_id': 't1', 'content': 'result'},
        {'role': 'assistant', 'content': 'done'},
        {'role': 'user', 'content': 'second'}, {'role': 'assistant', 'content': 'fine'},
        {'role': 'user', 'content': 'third'},
    ]
    head, tail = split_recent_turns(messages, turns=2)
    assert len(head) == 4 and tail[0]['content'] == 'second'
    assert len(split_recent_turns(messages, turns=0)[0]) == len(messages)
    assert split_recent_turns(messages, turns=10)[0] == []
    assert split_recent_turns(messages, turns=3, tokens=1)[1][0]['content'] == 'third'
    # A call left unanswered at a proposed turn boundary must be retained.
    open_messages = messages[:2] + messages[4:]
    head, tail = split_recent_turns(open_messages, turns=1)
    assert head == open_messages[:2] or not head
    assert not (head and head[-1].get('tool_calls'))


def test_generation_history_unbounded_and_tool_result_pairs(ctx):
    db, store, _, _ = ctx
    last = _conversation(store, count=51, size=1)
    history = store.history('a', last.conversation_id)
    assert len(history) == 102
    assert history[0]['content'].startswith('User question 0')
    with db.connect() as con:
        row = con.execute('SELECT id,content FROM messages WHERE id=?', (last.response_message_id,)).fetchone()
        con.execute('UPDATE messages SET content=? WHERE id=?', (json.dumps([
            {'type': 'think', 'text': 'Private reasoning text'},
            {'type': 'text', 'text': 'The answer'}], ensure_ascii=False), row['id']))
    history = store.history('a', last.conversation_id)
    assert history[-1]['content'] == 'The answer'
    assert history[-1]['reasoning_content'] == 'Private reasoning text'

    # A tool call/result sequence remains paired in the next model input.
    new, _ = store.begin('a', {'text': 'Tools', 'conversationId': last.conversation_id,
                               'parentMessageId': last.response_message_id})
    store.append('a', new.run_id, {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'step_1', 'type': 'tool_call', 'tool_call': {
            'id': 'call_a', 'name': 'file_read', 'args': {'path': 'readme.md'},
            'output': 'File contents', 'type': 'tool_call', 'progress': 1}}}})
    store.finish('a', new.run_id, status='complete', text='Finished')
    messages = store.history('a', new.conversation_id)
    assert messages[-3]['tool_calls'][0]['id'] == 'call_a'
    assert messages[-2] == {'role': 'tool', 'tool_call_id': 'call_a', 'content': 'File contents'}
    assert messages[-1] == {'role': 'assistant', 'content': 'Finished'}


def test_summary_checkpoint_is_persisted_without_removing_originals(ctx):
    db, store, _, _ = ctx
    prev = _conversation(store, count=5, size=1)
    before = store.history('a', prev.conversation_id)
    follow, _ = store.begin('a', {'text': 'new question', 'conversationId': prev.conversation_id,
                                  'parentMessageId': prev.response_message_id})
    with db.connect() as con:
        original_count = con.execute('SELECT count(*) FROM messages WHERE conversation_id=?',
                                     (prev.conversation_id,)).fetchone()[0]
    carrier = build_summary_carrier_text('The previous five turns establish context.')
    store.stage_summary('a', follow.run_id, 'The previous five turns establish context.', len(carrier), boundary=10)
    assert store.finish('a', follow.run_id, status='complete', text='The follow-up answer')
    with db.connect() as con:
        after_count = con.execute('SELECT count(*) FROM messages WHERE conversation_id=?',
                                  (prev.conversation_id,)).fetchone()[0]
        content = json.loads(con.execute('SELECT content FROM messages WHERE id=?',
                                         (follow.response_message_id,)).fetchone()[0])
    assert after_count == original_count + 1
    assert content[0]['type'] == 'summary' and content[0]['boundary']
    assert content[0]['tokenCount'] == len(carrier)
    assert len(store.history('a', prev.conversation_id)) == 2
    assert store.history('a', prev.conversation_id)[0]['content'] == carrier
    assert store.history('a', prev.conversation_id)[1]['content'] == 'The follow-up answer'
    assert len(before) == 10
    with pytest.raises(KeyError):
        store.history('b', prev.conversation_id)
    # Two independent reopened SQLite handles see the same durable state.
    assert len(GenerationStore(SQLiteDatabase(db.root)).history('a', prev.conversation_id)) == 2


def test_failed_and_cancelled_compaction_keep_full_history(ctx):
    db, store, _, _ = ctx
    prev = _conversation(store, count=3, size=1)
    g, _ = store.begin('a', {'text': 'Still here', 'conversationId': prev.conversation_id,
                             'parentMessageId': prev.response_message_id})
    with pytest.raises(ValueError):
        store.stage_summary('a', g.run_id, '', 0)
    assert store.finish('a', g.run_id, status='error', error='Model connection failed')
    history = store.history('a', prev.conversation_id)
    assert any('User question 0' in item.get('content', '') for item in history)
    assert not any(item.get('role') == 'system' and '<summary>' in item.get('content', '') for item in history)
    g2, _ = store.begin('a', {'text': 'Cancelled request', 'conversationId': prev.conversation_id,
                              'parentMessageId': g.response_message_id})
    assert store.finish('a', g2.run_id, status='aborted')
    assert any('User question 0' in item.get('content', '') for item in store.history('a', prev.conversation_id))


async def _empty_text(*args, **kwargs):
    if False:
        yield ''


@pytest.mark.asyncio
async def test_runtime_auto_compacts_with_real_model_callback_and_resume(ctx):
    db, store, _, profile = ctx
    g = _conversation(store, count=5, size=80)
    next_run, _ = store.begin('a', {'text': 'last question', 'conversationId': g.conversation_id,
                                   'parentMessageId': g.response_message_id})
    called = []

    async def summarize(profile, messages, **kwargs):
        called.append(messages)
        assert 'checkpoint' in messages[-1]['content'].lower()
        yield 'Earlier dialogue contains several questions and responses.'

    async def emit(_): pass
    runner = AgentRunner('a', next_run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summarize, on_text=emit, profile=profile)
    original = store.history('a', g.conversation_id, message_id=next_run.user_message_id)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 300}), original)
    await runner._before_model(state)
    assert called
    assert state.messages[0]['content'].startswith('<summary>')
    assert state.messages[-1]['content'] == 'last question'
    assert len(state.messages) < len(original)
    assert store.finish('a', next_run.run_id, status='complete', text='Continued safely')
    latest = store.history('a', g.conversation_id)
    assert latest[0]['role'] == 'system' and 'Earlier dialogue' in latest[0]['content']
    assert latest[-1]['content'] == 'Continued safely'


@pytest.mark.asyncio
async def test_summary_failure_does_not_truncate_or_retrigger_empty(ctx):
    db, store, _, profile = ctx
    g = _conversation(store, count=5, size=75)
    pending, _ = store.begin('a', {'text': 'new question', 'conversationId': g.conversation_id,
                                  'parentMessageId': g.response_message_id})
    runner = AgentRunner('a', pending, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=_empty_text, on_text=_emit_noop, profile=profile)
    original = store.history('a', g.conversation_id, message_id=pending.user_message_id)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 270}), list(original))
    await runner._before_model(state)
    assert original == state.messages
    assert not called_summary(store, pending.run_id)
    await runner._before_model(state)
    assert original == state.messages


async def _emit_noop(_): pass


def called_summary(store, run_id):
    with store.database.connect() as db:
        row = db.execute('SELECT state FROM runs WHERE id=?', (run_id,)).fetchone()
    return 'summaryCheckpoint' in json.loads(row[0])


@pytest.mark.asyncio
async def test_cancelled_summary_does_not_persist_checkpoint(ctx):
    db, store, _, profile = ctx
    prev = _conversation(store, count=5, size=80)
    g, _ = store.begin('a', {'text': 'new prompt', 'conversationId': prev.conversation_id,
                             'parentMessageId': prev.response_message_id})

    async def cancel(*a, **kw):
        yield 'Partial summary'
        raise asyncio.CancelledError()

    runner = AgentRunner('a', g, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=cancel, on_text=_emit_noop, profile=profile)
    original = store.history('a', g.conversation_id, message_id=g.user_message_id)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 320}), list(original))
    with pytest.raises(asyncio.CancelledError):
        await runner._before_model(state)
    assert state.messages == original
    assert not called_summary(store, g.run_id)


@pytest.mark.asyncio
async def test_manual_compaction_uses_same_run_state_and_no_dummy_user_message(ctx):
    db, store, _, profile = ctx
    prev = _conversation(store, count=3, size=10)
    existing = store.history('a', prev.conversation_id)
    manual, created = store.begin('a', {
        'conversationId': prev.conversation_id, 'parentMessageId': prev.response_message_id,
        'compact': True,
    })
    assert created and store.manual_compaction('a', manual.run_id)
    with db.connect() as con:
        assert con.execute('SELECT count(*) FROM messages WHERE conversation_id=?',
                           (prev.conversation_id,)).fetchone()[0] == len(existing)
    seen = []

    async def summary(_profile, messages, **kwargs):
        seen.append(messages)
        yield 'The earlier conversation discussed three questions.'

    runner = AgentRunner('a', manual, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summary, on_text=_emit_noop, profile=profile)
    result = await runner.run(existing)
    assert result == existing and seen
    assert store.finish('a', manual.run_id, status='complete', text='')
    contents = store.history('a', manual.conversation_id)
    assert len(contents) == 1 and contents[0]['role'] == 'system'
    assert 'earlier conversation' in contents[0]['content']
    with db.connect() as con:
        row = con.execute('SELECT content FROM messages WHERE id=?', (manual.response_message_id,)).fetchone()
    assert json.loads(row[0])[0]['initiatedBy'] == 'user'


def test_manual_invalid_and_failed_compaction_preserves_history(ctx):
    db, store, _, _ = ctx
    prev = _conversation(store, count=2, size=2)
    with pytest.raises(ValueError):
        store.begin('a', {'compact': True, 'text': '', 'conversationId': 'new'})
    with pytest.raises(ValueError):
        store.begin('a', {'compact': True, 'conversationId': prev.conversation_id,
                          'parentMessageId': prev.response_message_id, 'isRegenerate': True})
    g, _ = store.begin('a', {'compact': True, 'conversationId': prev.conversation_id,
                             'parentMessageId': prev.response_message_id})
    assert store.finish('a', g.run_id, status='error', error='Summary provider unavailable')
    with db.connect() as con:
        content = json.loads(con.execute('SELECT content FROM messages WHERE id=?', (g.response_message_id,)).fetchone()[0])
    assert content[-1]['initiatedBy'] == 'user'
    assert content[-1]['type'] == 'error'
    assert any('User question 0' in m['content'] for m in store.history('a', prev.conversation_id))
