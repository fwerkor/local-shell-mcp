"""Context pressure, LLM checkpoint, durable history and negative recovery."""
import asyncio
import json

import httpx
import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runtime
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, run_agent_loop
from local_shell_mcp.webui.compaction import CompactionFailed, build_summary_carrier_text
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
    usage = [value['data'] for _, value in store.events('a', next_run.run_id)
             if value.get('event') == 'on_context_usage']
    assert [item['compactionStatus'] for item in usage] == ['running', 'complete']
    assert usage[-1]['breakdown']['summaryTokens'] > 0
    assert usage[-1]['breakdown']['messageCount'] == len(state.messages) - 1
    assert state.messages[0]['content'].startswith('<summary>')
    assert state.messages[-1]['content'] == 'last question'
    assert len(state.messages) < len(original)
    assert store.finish('a', next_run.run_id, status='complete', text='Continued safely')
    latest = store.history('a', g.conversation_id)
    assert latest[0]['role'] == 'system' and 'Earlier dialogue' in latest[0]['content']
    assert latest[-1]['content'] == 'Continued safely'


@pytest.mark.asyncio
async def test_summary_failure_stops_generation_and_preserves_history(ctx, monkeypatch):
    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0,) * 8)
    db, store, repo, profile = ctx
    repo.save_setting('a', 'endpoints', {'summarization': {
        'trigger': {'type': 'token_ratio', 'value': 0.01}}})
    g = _conversation(store, count=5, size=75)
    pending, _ = store.begin('a', {'text': 'new question', 'conversationId': g.conversation_id,
                                  'parentMessageId': g.response_message_id})
    attempts = []

    async def empty_summary(*args, **kwargs):
        attempts.append(True)
        if False:
            yield ''

    runner = AgentRunner('a', pending, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=empty_summary, on_text=_emit_noop, profile=profile)
    original = store.history('a', g.conversation_id, message_id=pending.user_message_id)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 10000}), list(original))
    model_calls = []

    async def main_model(*args, **kwargs):
        model_calls.append(True)
        yield 'Must not run'

    with pytest.raises(CompactionFailed, match='model generation stopped'):
        await run_agent_loop(state, stream_tools=main_model, stream_text=main_model,
                             dispatch=None, before_model=runner._before_model, on_text=_emit_noop)
    assert len(attempts) == 9  # initial request plus eight retries
    assert model_calls == []
    assert original == state.messages
    assert not called_summary(store, pending.run_id)
    with pytest.raises(CompactionFailed):
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


def test_multiple_projects_keep_independent_history_and_compaction(ctx):
    db, store, _, _ = ctx
    with db.connect() as connection:
        for project_id in ('project-a', 'project-b'):
            connection.execute(
                'INSERT INTO projects(id, owner, name, description) VALUES(?, ?, ?, ?)',
                (project_id, 'a', project_id, ''),
            )
    jobs = {}
    for project in ('project-a', 'project-b'):
        first, created = store.begin('a', {'text': 'First question for ' + project,
                                            'projectId': project})
        assert created
        store.finish('a', first.run_id, status='complete', text='Original answer for ' + project)
        jobs[project] = first
    a = jobs['project-a']
    b = jobs['project-b']
    before_b = store.history('a', b.conversation_id)
    next_a, created = store.begin('a', {'conversationId': a.conversation_id,
                                         'parentMessageId': a.response_message_id,
                                         'text': 'Summarize project A only.'})
    assert created
    store.stage_summary('a', next_a.run_id, 'Project A checkpoint.', 6)
    store.finish('a', next_a.run_id, status='complete', text='Done A.')
    assert store.history('a', b.conversation_id) == before_b
    assert len(store.history('a', a.conversation_id)) == 2
    assert 'Project A checkpoint' in store.history('a', a.conversation_id)[0]['content']
    with pytest.raises(KeyError):
        store.history('b', a.conversation_id)


@pytest.mark.asyncio
async def test_repeated_compact_skip_records_failure_not_new_boundary(ctx):
    db, store, _, profile = ctx
    previous = _conversation(store, count=2, size=3)
    before = store.history('a', previous.conversation_id)
    first, _ = store.begin('a', {'compact': True,
                                  'conversationId': previous.conversation_id,
                                  'parentMessageId': previous.response_message_id})
    store.stage_summary('a', first.run_id, 'Initial completed checkpoint.', 8, manual=True)
    store.finish('a', first.run_id, status='complete', text='')
    repeated, _ = store.begin('a', {'compact': True,
                                     'conversationId': previous.conversation_id,
                                     'parentMessageId': first.response_message_id})
    runner = AgentRunner('a', repeated, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=_empty_text,
                         on_text=_emit_noop, profile=profile)
    with pytest.raises(ValueError, match='Nothing to compact'):
        await runner.run(store.history('a', previous.conversation_id, message_id=repeated.user_message_id))
    assert store.finish('a', repeated.run_id, status='error', error='Nothing to compact')
    history = store.history('a', previous.conversation_id)
    assert history[0]['role'] == 'system'
    assert 'Initial completed checkpoint' in history[0]['content']
    assert len(before) == 4
    with db.connect() as connection:
        assert connection.execute('SELECT count(*) FROM messages WHERE conversation_id=?',
                                  (previous.conversation_id,)).fetchone()[0] == len(before) + 2


def test_completed_summary_survives_process_crash_before_answer(ctx):
    """Upstream retains a finished checkpoint even when the answer fails later."""
    database, store, _, _ = ctx
    prev = _conversation(store, count=4, size=7)
    run, _ = store.begin('a', {
        'conversationId': prev.conversation_id,
        'parentMessageId': prev.response_message_id,
        'text': 'Continue after this summary',
    })
    store.stage_summary('a', run.run_id, 'Four earlier turns completed.', 11, boundary=4)
    # A fresh Controller reopens the same SQLite database and seals orphaned runs.
    restarted = GenerationStore(SQLiteDatabase(database.root))
    assert restarted.recover_orphans() == 1
    assert restarted.latest('a', prev.conversation_id).status == 'interrupted'
    assert restarted.recover_orphans() == 0
    history = restarted.history('a', prev.conversation_id)
    assert history[0]['role'] == 'system'
    assert 'Four earlier turns completed.' in history[0]['content']
    assert not any('User question 0' in str(message.get('content')) for message in history)
    # A new turn must retain the finished checkpoint and not resurrect old context.
    followup, _ = restarted.begin('a', {
        'conversationId': prev.conversation_id,
        'parentMessageId': run.response_message_id,
        'text': 'Can you resume?',
    })
    restored = restarted.history('a', prev.conversation_id, message_id=followup.user_message_id)
    assert restored[0]['role'] == 'system'
    assert restored[-1]['content'] == 'Can you resume?'


def test_failed_summary_followed_by_orphan_recovery_preserves_full_history(ctx):
    database, store, _, _ = ctx
    prev = _conversation(store, count=3, size=2)
    run, _ = store.begin('a', {
        'conversationId': prev.conversation_id,
        'parentMessageId': prev.response_message_id,
        'text': 'Continue without checkpoint',
    })
    restarted = GenerationStore(SQLiteDatabase(database.root))
    assert restarted.recover_orphans() == 1
    history = restarted.history('a', prev.conversation_id)
    assert any('User question 0' in str(item.get('content')) for item in history)
    assert not any(item.get('role') == 'system' and '<summary>' in item.get('content', '')
                   for item in history)


def _tool_exchange(call_id, size):
    return [
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': call_id, 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': 'data ' * size},
    ]


def test_single_turn_compaction_preserves_tool_batch_boundaries():
    from local_shell_mcp.webui.context_budget import split_compaction_history

    original = [
        {'role': 'user', 'content': 'Keep monitoring'},
        *_tool_exchange('old', 250),
        *_tool_exchange('recent', 10),
    ]
    head, tail = split_compaction_history(original, turns=2, tokens=None, tail_budget=80)
    assert head == original[:3]
    assert tail[0]['role'] == 'user'
    assert tail[1:] == original[3:]
    assert original[-1]['tool_call_id'] == 'recent'
    assert split_compaction_history(original[:-1], turns=2, tokens=None, tail_budget=80)[0] == []


@pytest.mark.asyncio
async def test_default_threshold_compacts_one_long_running_turn(ctx):
    db, store, repo, profile = ctx
    run, _ = store.begin('a', {'text': 'Keep monitoring'})
    repo.save_setting('a', 'endpoints', {})
    calls = []

    async def summarize(_profile, messages, **kwargs):
        calls.append(messages)
        yield 'Continue monitoring; old data was read.'

    runner = AgentRunner('a', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summarize, on_text=_emit_noop,
                         profile=profile)
    original = [{'role': 'user', 'content': 'Keep monitoring'},
                *_tool_exchange('old', 700), *_tool_exchange('recent', 10)]
    budget = calculate_budget([*runner._conversation_context(), *original], [], 1000)
    input_tokens = budget.message_tokens + budget.instruction_tokens + budget.tool_schema_tokens
    below = int(input_tokens / 0.84)
    above = int(input_tokens / 0.86)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': below}), list(original))
    await runner._before_model(state)
    assert not calls and state.messages == original
    state.context.parameters = {'max_context_tokens': above}
    await runner._before_model(state)
    assert len(calls) == 1
    assert state.messages[0]['content'].startswith('<summary>')
    assert state.messages[-2:] == original[-2:]
    assert all(message.get('tool_call_id') != 'old' for message in state.messages)
    assert store.finish('a', run.run_id, status='complete', text='Continued')
    history = store.history('a', run.conversation_id)
    assert history[0]['role'] == 'system'
    assert not any(message.get('tool_call_id') == 'old' for message in history)
    assert any(message.get('tool_call_id') == 'recent' for message in history)


@pytest.mark.asyncio
async def test_live_compaction_is_owner_scoped_durable_and_bypasses_threshold(ctx):
    db, store, _, profile = ctx
    run, _ = store.begin('a', {'text': 'Keep monitoring'})
    with pytest.raises(ValueError):
        store.request_live_compaction('b', run.conversation_id)
    receipt = store.request_live_compaction('a', run.conversation_id)
    assert store.request_live_compaction('a', run.conversation_id) == receipt
    request_id = receipt['requestId']
    reopened = GenerationStore(SQLiteDatabase(db.root))
    assert reopened.live_compaction_status('a', run.run_id, request_id) == 'pending'
    with pytest.raises(KeyError):
        reopened.live_compaction_status('b', run.run_id, request_id)

    async def summarize(_profile, messages, **kwargs):
        yield 'Monitoring task, continuing safely.'

    runner = AgentRunner('a', run, db, reopened, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summarize, on_text=_emit_noop,
                         profile=profile)
    original = [{'role': 'user', 'content': 'Keep monitoring'},
                *_tool_exchange('old', 300), *_tool_exchange('recent', 5)]
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 100000}), original)
    await runner._before_model(state)
    assert reopened.live_compaction_status('a', run.run_id, request_id) == 'complete'
    assert reopened.live_compaction_request('a', run.run_id) is None
    assert state.messages[0]['role'] == 'system'
    assert not reopened.manual_compaction('a', run.run_id)
    summaries = [value['data']['result']['summary'] for _, value in reopened.events('a', run.run_id)
                 if value.get('event') == 'on_run_step_completed'
                 and 'summary' in value.get('data', {}).get('result', {})]
    assert summaries[-1]['initiatedBy'] == 'live'


@pytest.mark.asyncio
async def test_live_compaction_failure_preserves_messages_and_reports_result(ctx, monkeypatch):
    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0,) * 8)
    db, store, _, profile = ctx
    run, _ = store.begin('a', {'text': 'Keep monitoring'})
    receipt = store.request_live_compaction('a', run.conversation_id)
    runner = AgentRunner('a', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=_empty_text, on_text=_emit_noop,
                         profile=profile)
    original = [{'role': 'user', 'content': 'Keep monitoring'},
                *_tool_exchange('old', 300), *_tool_exchange('recent', 5)]
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 10000}), list(original))
    with pytest.raises(CompactionFailed):
        await runner._before_model(state)
    assert state.messages == original
    assert store.live_compaction_status('a', run.run_id, receipt['requestId']) == 'failed'
    next_receipt = store.request_live_compaction('a', run.conversation_id)
    assert next_receipt != receipt
    assert store.finish('a', run.run_id, status='complete', text='Done')
    assert store.live_compaction_status('a', run.run_id, next_receipt['requestId']) == 'failed'


@pytest.mark.asyncio
async def test_live_compaction_requested_during_tool_batch_resumes_model(ctx):
    from local_shell_mcp.webui.agent_runtime import ToolBatchOutput, run_agent_loop
    from local_shell_mcp.webui.providers import ModelToolCall

    db, store, _, profile = ctx
    run, _ = store.begin('a', {'text': 'Keep monitoring'})
    called = []
    receipt = None

    async def summarize(_profile, messages, **kwargs):
        assert any(message.get('tool_call_id') == 'old' for message in messages)
        assert not any(message.get('tool_call_id') == 'live' for message in messages)
        yield 'Prior results have been processed; continue monitoring.'

    async def model(_profile, messages, **kwargs):
        called.append(list(messages))
        if len(called) == 1:
            yield ModelToolCall('live', 'read', {})
        else:
            assert messages[0]['content'].startswith('<summary>')
            assert messages[-1]['tool_call_id'] == 'live'
            yield 'Continued after compaction.'

    async def dispatch(calls, state):
        nonlocal receipt
        assert calls[0].call_id == 'live'
        receipt = store.request_live_compaction('a', run.conversation_id)
        assert store.live_compaction_status('a', run.run_id, receipt['requestId']) == 'pending'
        return ToolBatchOutput([{'role': 'tool', 'tool_call_id': 'live', 'content': 'current data'}])

    runner = AgentRunner('a', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=model, stream_text=summarize, on_text=_emit_noop, profile=profile)
    context = AgentContext(profile, [{'type': 'function', 'function': {'name': 'read'}}],
                           {'max_context_tokens': 100000})
    state = AgentLoopState(context, [{'role': 'user', 'content': 'Keep monitoring'},
                                     *_tool_exchange('old', 300)])
    result = await run_agent_loop(state, stream_tools=model, stream_text=model, dispatch=dispatch,
                                  before_model=runner._before_model, on_text=_emit_noop)
    assert len(called) == 2
    assert result[-1]['content'] == 'Continued after compaction.'
    assert store.live_compaction_status('a', run.run_id, receipt['requestId']) == 'complete'


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_fragment", [False, True])
async def test_oversized_tool_result_fragmented_checkpoint_is_atomic(ctx, fail_fragment):
    db, store, _, profile = ctx
    run, _ = store.begin('a', {'text': 'Read the entire result'})
    original = [{'role': 'user', 'content': 'Read the entire result'},
                *_tool_exchange('huge', 18000), *_tool_exchange('recent', 5)]
    original[2]['content'] += ' END_OF_TOOL_RESULT'
    fragments = []

    async def summarize(_profile, messages, **kwargs):
        if any(message.get('role') == 'tool' for message in messages):
            raise ValueError('context length exceeded')
        assert sum(map(message_token_count, messages)) + kwargs['max_tokens'] <= 8192
        fragments.append(messages[0]['content'])
        assert not called_summary(store, run.run_id)
        if fail_fragment and len(fragments) == 2:
            raise ValueError('provider disconnected')
        if len(fragments) > 1:
            assert 'Checkpoint fragment' in messages[-1]['content']
        yield 'Checkpoint fragment ' + str(len(fragments))

    runner = AgentRunner('a', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summarize, on_text=_emit_noop,
                         profile=profile)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 8192}), list(original))
    if fail_fragment:
        with pytest.raises(CompactionFailed):
            await runner._before_model(state)
    else:
        await runner._before_model(state)
    assert len(fragments) >= 2
    snapshots = [value['data'] for _, value in store.events('a', run.run_id)
                 if value.get('event') == 'on_context_usage']
    if fail_fragment:
        assert state.messages == original
        assert not called_summary(store, run.run_id)
        assert snapshots[-1]['compactionStatus'] == 'failed'
    else:
        assert any('END_OF_TOOL_RESULT' in fragment for fragment in fragments)
        assert called_summary(store, run.run_id)
        assert state.messages[-2:] == original[-2:]
        assert snapshots[-1]['compactionStatus'] == 'complete'
        assert snapshots[-1]['breakdown']['messageTokens'] < 100


@pytest.mark.asyncio
async def test_auto_compaction_can_recover_after_more_than_three_failures(ctx, monkeypatch):
    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0,) * 8)
    db, store, repo, profile = ctx
    run, _ = store.begin('a', {'text': 'Keep reading'})
    repo.save_setting('a', 'endpoints', {'summarization': {
        'trigger': {'type': 'token_ratio', 'value': 0.05},
        'parameters': {'maxSummaryTokens': 200}}})
    attempts = []

    async def summarize(_profile, messages, **kwargs):
        attempts.append(messages)
        if len(attempts) <= 4:
            yield 'Uncommitted partial summary'
            raise httpx.ReadError('temporary provider failure')
        yield 'Recovered summary.'

    runner = AgentRunner('a', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summarize, on_text=_emit_noop,
                         profile=profile)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 10000}),
                           [{'role': 'user', 'content': 'Keep reading'},
                            *_tool_exchange('initial', 600)])
    model_calls = []

    async def main_model(_profile, messages, **kwargs):
        assert called_summary(store, run.run_id)
        assert 'Recovered summary.' in messages[0]['content']
        assert 'Uncommitted partial summary' not in messages[0]['content']
        model_calls.append(True)
        yield 'Continued.'

    await run_agent_loop(state, stream_tools=main_model, stream_text=main_model,
                         dispatch=None, before_model=runner._before_model, on_text=_emit_noop)
    assert len(attempts) == 5
    assert len(model_calls) == 1
    assert called_summary(store, run.run_id)
    assert state.messages[0]['content'].startswith('<summary>')


@pytest.mark.asyncio
async def test_fragment_retry_keeps_completed_prefix(ctx, monkeypatch):
    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0,) * 8)
    db, store, _, profile = ctx
    run, _ = store.begin('a', {'text': 'Read every fragment'})
    requests = []

    async def summarize(_profile, messages, **kwargs):
        if any(message.get('role') == 'tool' for message in messages):
            raise httpx.HTTPStatusError('oversized', request=httpx.Request('POST', profile.url),
                                        response=httpx.Response(504))
        requests.append(messages)
        assert not called_summary(store, run.run_id)
        if len(requests) == 2:
            yield 'Discard this partial fragment'
            raise httpx.ReadError('temporary disconnect')
        yield 'Successful fragment ' + str(len(requests))

    runner = AgentRunner('a', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summarize, on_text=_emit_noop,
                         profile=profile)
    original = [{'role': 'user', 'content': 'Read every fragment'},
                *_tool_exchange('huge', 18000), *_tool_exchange('recent', 5)]
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 8192}), list(original))
    await runner._before_model(state)
    assert len(requests) >= 3
    assert requests[1] == requests[2]
    assert 'Successful fragment 1' in requests[2][-1]['content']
    assert 'Discard this partial fragment' not in str(state.messages)
    assert called_summary(store, run.run_id)


@pytest.mark.asyncio
async def test_summary_permanent_provider_failure_does_not_retry(ctx, monkeypatch):
    monkeypatch.setattr(agent_runtime, "_MODEL_RETRY_DELAYS", (0,) * 8)
    db, store, _, profile = ctx
    run, _ = store.begin('a', {'text': 'Preserve context'})
    attempts = []

    async def summarize(*args, **kwargs):
        attempts.append(True)
        raise httpx.HTTPStatusError('unauthorized', request=httpx.Request('POST', profile.url),
                                    response=httpx.Response(401))
        if False:
            yield ''

    runner = AgentRunner('a', run, db, store, scopes=set(), grant_expires=None,
                         stream_tools=_empty_text, stream_text=summarize, on_text=_emit_noop,
                         profile=profile)
    original = [{'role': 'user', 'content': 'Preserve context'},
                *_tool_exchange('huge', 18000), *_tool_exchange('recent', 5)]
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 8192}), list(original))
    with pytest.raises(CompactionFailed) as error:
        await runner._before_model(state)
    assert len(attempts) == 1
    assert state.messages == original
    assert not called_summary(store, run.run_id)
    from local_shell_mcp.webui.error_diagnostics import generation_failure
    assert 'Context compaction failed' in json.loads(generation_failure(error.value, run.run_id))['message']


def test_live_compaction_rejects_active_graph_agent(ctx):
    from local_shell_mcp.webui.agents import AgentRepository

    db, store, _, _ = ctx
    agents = AgentRepository(db)
    root = agents.create('a', {'name': 'Root', 'provider': 'openAI', 'model': 'test'})
    child = agents.create('a', {'name': 'Child', 'provider': 'openAI', 'model': 'test'})
    graph = agents.update('a', root['id'], {'edges': [
        {'from': root['id'], 'to': child['id'], 'edgeType': 'direct'},
    ]})
    run, _ = store.begin('a', {'text': 'Run graph'}, graph)
    with db.connect() as conn:
        assert conn.execute('SELECT agent_id FROM conversations WHERE id=?',
                            (run.conversation_id,)).fetchone()[0] is None
        assert conn.execute('SELECT agent_id FROM runs WHERE id=?',
                            (run.run_id,)).fetchone()[0] == graph['id']
    with pytest.raises(ValueError, match='multi-agent graphs'):
        store.request_live_compaction('a', run.conversation_id)
    assert store.live_compaction_request('a', run.run_id) is None

    single, _ = store.begin('a', {'text': 'Run single agent'}, child)
    receipt = store.request_live_compaction('a', single.conversation_id)
    assert receipt['runId'] == single.run_id
