"""Provider-confirmed usage, source cumulative ratio and SQLite resume."""
from __future__ import annotations

import json

import httpx
import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, run_agent_loop
from local_shell_mcp.webui.context_budget import calculate_budget, context_usage_snapshot
from local_shell_mcp.webui.context_calibration import TokenCalibration, clamp_calibration_ratio
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.provider_tool_protocols import stream_native_tools
from local_shell_mcp.webui.providers import (
    ModelToolCall,
    ModelUsage,
    ProviderConfig,
    _usage_frame,
    stream_model,
    stream_model_with_tools,
)
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.mark.parametrize('provider_input,raw,instructions,expected', [
    (200, 100, 100, 1.0),
    (110, 50, 10, 2.0),
    (10, 100, 10, 1.0),
    (10, 0, 5, 1.0),
    (20, 10, 30, 1.0),
    (200, 20, 0, 5.0),
    (15, 20, 5, 0.5),
])
def test_source_ratio_gates_and_clamp(provider_input, raw, instructions, expected):
    value = TokenCalibration().observe(provider_input_tokens=provider_input,
                                       raw_sent_this_turn=raw, instruction_overhead=instructions)
    assert value.ratio == expected


def test_calibration_cumulative_from_source_no_ema_and_untrusted_serialization():
    cal = TokenCalibration()
    cal = cal.observe(provider_input_tokens=120, raw_sent_this_turn=100, instruction_overhead=20)
    assert cal.ratio == 1.0
    cal = cal.observe(provider_input_tokens=180, raw_sent_this_turn=100, instruction_overhead=20)
    assert cal.ratio == 1.3
    assert cal.cumulative_raw_sent == 200
    assert cal.cumulative_provider_reported == 260
    assert TokenCalibration.from_dict(cal.to_dict()) == cal
    assert TokenCalibration.from_dict({'cumulativeRawSent': -1, 'cumulativeProviderReported': 9}) == TokenCalibration()
    assert TokenCalibration.from_dict({'cumulativeRawSent': True, 'cumulativeProviderReported': 20}) == TokenCalibration()
    assert TokenCalibration.from_dict(None) == TokenCalibration()
    assert clamp_calibration_ratio(float('inf')) == 1
    assert clamp_calibration_ratio(float('nan')) == 1
    assert clamp_calibration_ratio(60) == 5
    assert clamp_calibration_ratio(-5) == .5
    assert cal.observe(provider_input_tokens=10**15, raw_sent_this_turn=1, instruction_overhead=0) == cal
    assert cal.observe(provider_input_tokens=True, raw_sent_this_turn=1, instruction_overhead=0) == cal


def test_calibrated_budget_only_scales_message_tokens_and_tool_subset():
    messages = [{'role': 'system', 'content': 'Policy is fixed'},
                {'role': 'user', 'content': 'Read the file'},
                {'role': 'tool', 'content': 'Returned result'}]
    old = calculate_budget(messages, [], 200, calibration_ratio=1)
    increased = calculate_budget(messages, [], 200, calibration_ratio=2.5)
    assert increased.instruction_tokens == old.instruction_tokens
    assert increased.message_tokens > old.message_tokens
    assert increased.remaining_context_tokens < old.remaining_context_tokens
    snapshot = context_usage_snapshot(messages, [], 200, calibration_ratio=2.5)
    assert snapshot['calibrationRatio'] == 2.5
    assert snapshot['breakdown']['toolMessageTokens'] <= snapshot['breakdown']['messageTokens']
    assert context_usage_snapshot(messages, [], 200, calibration_ratio=float('nan'))['calibrationRatio'] == 1


def test_sqlite_calibration_survives_restart_and_model_partition(tmp_path):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    job, _ = store.begin('a', {'text': 'Hello'})
    assert store.token_calibration('a', job.run_id, 'openai', 'model') == TokenCalibration()
    with pytest.raises(KeyError):
        store.token_calibration('b', job.run_id, 'openai', 'model')
    with pytest.raises(KeyError):
        store.record_token_calibration('b', job.run_id, 'openai', 'model', TokenCalibration())
    with pytest.raises(TypeError):
        store.record_token_calibration('a', job.run_id, 'openai', 'model', {})
    updated = TokenCalibration(40, 80, 2.0)
    store.record_token_calibration('a', job.run_id, 'openai', 'model', updated)
    reopened = GenerationStore(SQLiteDatabase(db.root))
    assert reopened.token_calibration('a', job.run_id, 'openai', 'model') == updated
    assert reopened.token_calibration('a', job.run_id, 'openai', 'other') == TokenCalibration()
    assert store.finish('a', job.run_id, status='complete', text='ok')
    with pytest.raises(KeyError):
        store.record_token_calibration('a', job.run_id, 'openai', 'model', updated)
    next_job, _ = reopened.begin('a', {'text': 'Continue', 'conversationId': job.conversation_id,
                                      'parentMessageId': job.response_message_id})
    assert reopened.token_calibration('a', next_job.run_id, 'openai', 'model') == updated
    assert reopened.token_calibration('a', next_job.run_id, 'anthropic', 'model') == TokenCalibration()


@pytest.mark.parametrize('provider,event,expected', [
    ('openai', {'usage': {'prompt_tokens': 120, 'completion_tokens': 15}}, ModelUsage('openai', 120, 15)),
    ('openai', {'usage': {'prompt_tokens': True, 'completion_tokens': 2}}, None),
    ('openai', {'usage': {'prompt_tokens': -1, 'completion_tokens': 2}}, None),
    ('anthropic', {'type': 'message_start', 'message': {'usage': {'input_tokens': 60, 'output_tokens': 0}}},
     ModelUsage('anthropic', 60, 0)),
    ('google', {'usageMetadata': {'promptTokenCount': 90, 'candidatesTokenCount': 25}},
     ModelUsage('google', 90, 25)),
])
def test_provider_usage_frame_adapters(provider, event, expected):
    assert _usage_frame(provider, event) == expected


def test_anthropic_usage_start_and_delta_merge():
    starting = _usage_frame('anthropic', {'type': 'message_start', 'message': {
        'usage': {'input_tokens': 91, 'output_tokens': 1}}})
    latest = _usage_frame('anthropic', {'type': 'message_delta', 'usage': {'output_tokens': 22}}, starting)
    assert latest == ModelUsage('anthropic', 91, 22)
    assert _usage_frame('anthropic', {'type': 'unrecognized'}, latest) == latest


@pytest.fixture
def model_events(monkeypatch):
    initial = httpx.AsyncClient
    messages = []
    outbound = []

    def server(request):
        outbound.append(request)
        return httpx.Response(200, text='\n\n'.join('data: ' + json.dumps(item) for item in messages) +
                              '\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: initial(transport=httpx.MockTransport(server), **kw))
    return messages, outbound


@pytest.mark.asyncio
async def test_openai_stream_reports_usage_after_final_text_not_in_text(model_events):
    events, requests = model_events
    events[:] = [
        {'choices': [{'delta': {'content': 'Hello.'}}]},
        {'choices': [], 'usage': {'prompt_tokens': 104, 'completion_tokens': 5}},
    ]
    profile = ProviderConfig('openai', 'gpt', 'https://test.invalid/stream', 'secret', include_usage=True)
    result = [item async for item in stream_model(profile, [{'role': 'user', 'content': 'Hello'}])]
    assert result == ['Hello.', ModelUsage('openai', 104, 5)]
    assert json.loads(requests[0].content)['stream_options'] == {'include_usage': True}


@pytest.mark.asyncio
async def test_openai_tools_usage_after_calls(model_events):
    events, requests = model_events
    events[:] = [
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c1',
            'function': {'name': 'demo', 'arguments': '{}'}}]}}]},
        {'choices': [], 'usage': {'prompt_tokens': 155, 'completion_tokens': 11}},
    ]
    profile = ProviderConfig('openai', 'gpt', 'https://test.invalid/stream', 'secret', include_usage=True)
    result = [item async for item in stream_model_with_tools(profile, [], tools=[{'type': 'function',
        'function': {'name': 'demo', 'parameters': {'type': 'object', 'properties': {}}}}])]
    assert result == [ModelToolCall('c1', 'demo', {}), ModelUsage('openai', 155, 11)]
    assert 'stream_options' in json.loads(requests[0].content)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,events,expected', [
    ('anthropic', [
        {'type': 'message_start', 'message': {'usage': {'input_tokens': 33, 'output_tokens': 0}}},
        {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Okay.'}},
        {'type': 'message_delta', 'usage': {'output_tokens': 7}},
    ], ModelUsage('anthropic', 33, 7)),
    ('google', [
        {'candidates': [{'content': {'parts': [{'text': 'Okay.'}]}}]},
        {'usageMetadata': {'promptTokenCount': 88, 'candidatesTokenCount': 17}},
    ], ModelUsage('google', 88, 17)),
])
async def test_native_provider_stream_propagates_usage(model_events, provider, events, expected):
    received, requests = model_events
    received[:] = events
    profile = ProviderConfig(provider, 'test-model', 'https://test.invalid/stream', 'token')
    result = [item async for item in stream_native_tools(profile, [{'role': 'user', 'content': 'hi'}],
                                                           tools=[{'function': {'name': 'noop', 'parameters': {}}}],
                                                           max_tokens=128, temperature=None)]
    assert result == ['Okay.', expected]


@pytest.mark.asyncio
async def test_runner_consumes_usage_without_leaking_into_assistant_or_summary(tmp_path):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    settings = WorkspaceRepository(db)
    job, _ = store.begin('a', {'text': 'Remember context'})
    settings.save_setting('a', 'endpoints', {'agents': {'maxContextTokens': 2000}})
    profile = ProviderConfig('openai', 'mock', 'https://test.invalid/stream', '')
    seen_text = []

    async def fake_stream(*args, **kw):
        yield 'Answer'
        yield ModelUsage('openai', 400, 50)

    async def callback(value):
        seen_text.append(value)

    runner = AgentRunner('a', job, db, store, scopes=set(), grant_expires=None,
        stream_tools=fake_stream, stream_text=fake_stream, on_text=callback, profile=profile)
    original = [{'role': 'user', 'content': 'Remember context'}]
    state = AgentLoopState(AgentContext(profile, []), list(original))
    result = await run_agent_loop(state, stream_tools=fake_stream, stream_text=fake_stream,
        dispatch=lambda *a: None, on_text=callback, on_model_usage=runner._observe_model_usage)
    assert result[-1]['content'] == 'Answer'
    assert seen_text == ['Answer']
    measurement = store.token_calibration('a', job.run_id, 'openai', 'mock')
    assert .5 <= measurement.ratio <= 5
    assert measurement.cumulative_raw_sent > 0
    assert measurement.cumulative_provider_reported > 0
    restarted = GenerationStore(SQLiteDatabase(db.root))
    assert restarted.token_calibration('a', job.run_id, 'openai', 'mock') == measurement
    summary_seen = []

    async def summary(*a, **kw):
        summary_seen.append(True)
        yield 'Summary text'
        yield ModelUsage('openai', 100, 20)

    runner.stream_text = summary
    assert await runner._summarize_history(original) == 'Summary text'
    assert summary_seen == [True]


@pytest.mark.asyncio
async def test_context_snapshot_uses_persisted_provider_ratio_on_next_model_turn(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    settings = WorkspaceRepository(db)
    job, _ = store.begin('alice', {'text': 'One full turn'})
    settings.save_setting('alice', 'endpoints', {'agents': {'maxContextTokens': 600}})
    profile = ProviderConfig('openai', 'latest-model', 'http://127.0.0.1:11523/chat', '')

    async def text(*args, **kwargs):
        yield 'response'

    async def noop(_):
        pass

    runner = AgentRunner('alice', job, db, store, scopes=set(), grant_expires=None,
        stream_tools=text, stream_text=text, on_text=noop, profile=profile)
    state = AgentLoopState(AgentContext(profile, []), [{'role': 'user', 'content': 'One full turn'}])
    await runner._before_model(state)
    previous = [event['data'] for _, event in store.events('alice', job.run_id)
                if event.get('event') == 'on_context_usage'][-1]
    assert previous['calibrationRatio'] == 1
    await runner._observe_model_usage(ModelUsage('openai', 200, 18), state)
    latest_calibration = store.token_calibration('alice', job.run_id, 'openai', 'latest-model')
    assert latest_calibration.ratio > 1
    await runner._before_model(state)
    after = [event['data'] for _, event in store.events('alice', job.run_id)
             if event.get('event') == 'on_context_usage'][-1]
    assert after['calibrationRatio'] == latest_calibration.ratio
    assert after['breakdown']['messageTokens'] > previous['breakdown']['messageTokens']
    # Reopening both stores retains ratio for future turns without trusting
    # incoming client JSON metadata.
    assert GenerationStore(SQLiteDatabase(db.root)).token_calibration(
        'alice', job.run_id, 'openai', 'latest-model') == latest_calibration


@pytest.mark.asyncio
async def test_usage_without_provider_confirmation_does_not_change_ratio(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    job, _ = store.begin('a', {'text': 'No telemetry'})
    config = ProviderConfig('openai', 'model', 'http://127.0.0.1:12340', '')

    async def empty(*args, **kwargs):
        if False:
            yield None

    async def callback(_):
        pass

    runner = AgentRunner('a', job, db, store, scopes=set(), grant_expires=None,
        stream_tools=empty, stream_text=empty, on_text=callback, profile=config)
    state = AgentLoopState(AgentContext(config, []), [{'role': 'user', 'content': 'Normal prompt'}])
    await runner._observe_model_usage(ModelUsage('anthropic', 300, 20), state)
    assert store.token_calibration('a', job.run_id, 'openai', 'model') == TokenCalibration()
    await runner._observe_model_usage(ModelUsage('openai', 0, 0), state)
    assert store.token_calibration('a', job.run_id, 'openai', 'model') == TokenCalibration()


def test_anthropic_cached_input_telemetry_is_not_discarded():
    start = _usage_frame('anthropic', {'type': 'message_start', 'message': {
        'usage': {'input_tokens': 20, 'cache_read_input_tokens': 70,
                  'cache_creation_input_tokens': 10, 'output_tokens': 0}}})
    assert start == ModelUsage('anthropic', 100, 0)
    assert _usage_frame('anthropic', {'type': 'message_delta', 'usage': {
        'output_tokens': 30}}, start) == ModelUsage('anthropic', 100, 30)
    assert _usage_frame('anthropic', {'type': 'message_start', 'message': {
        'usage': {'input_tokens': 50, 'cache_read_input_tokens': 'invalid',
                  'output_tokens': 0}}}) is None


@pytest.mark.asyncio
async def test_calibration_storage_failure_does_not_abort_model_answer(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    job, _ = store.begin('a', {'text': 'Hello'})
    profile = ProviderConfig('openai', 'test', 'https://test.invalid', '')

    async def stream(*args, **kwargs):
        yield 'Successful answer.'
        yield ModelUsage('openai', 300, 12)

    async def emit(_):
        pass

    runner = AgentRunner('a', job, db, store, scopes=set(), grant_expires=None,
        stream_tools=stream, stream_text=stream, on_text=emit, profile=profile)
    monkeypatch.setattr(store, 'record_token_calibration',
                        lambda *a, **kw: (_ for _ in ()).throw(OSError('disk inaccessible')))
    result = await run_agent_loop(AgentLoopState(AgentContext(profile, []),
        [{'role': 'user', 'content': 'Hello'}]), stream_tools=stream, stream_text=stream,
        dispatch=lambda *a: None, on_text=emit, on_model_usage=runner._observe_model_usage)
    assert result[-1]['content'] == 'Successful answer.'
