"""Pinned SDK context snapshot, native React SSE replay and SQLite reload."""
from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState
from local_shell_mcp.webui.compaction import build_summary_carrier_text
from local_shell_mcp.webui.context_budget import calculate_budget, context_usage_snapshot
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def setup(tmp_path):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    job, fresh = store.begin('alice', {'text': 'What was our plan?', 'model': 'test'})
    assert fresh
    return db, store, job


def _snapshot(job, *, messages=None):
    return context_usage_snapshot(
        messages or [{'role': 'system', 'content': 'Policy'},
                     {'role': 'user', 'content': 'What was our plan?'}],
        [], 1024, run_id=job.run_id, agent_id='example-agent',
    )


def test_context_breakdown_projects_source_schema_without_double_counting_summary():
    messages = [
        {'role': 'system', 'content': 'System policy'},
        {'role': 'system', 'content': build_summary_carrier_text('Old facts')},
        {'role': 'user', 'content': 'Search'},
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c', 'function': {'name': 'f', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'c', 'content': 'Found records'},
    ]
    tools = [{'type': 'function', 'function': {'name': 'f', 'parameters': {'type': 'object'}}}]
    budget = calculate_budget(messages, tools, 2000)
    event = context_usage_snapshot(messages, tools, 2000, run_id='run-1', agent_id='agent-1')
    breakdown = event['breakdown']
    assert event['runId'] == 'run-1' and event['agentId'] == 'agent-1'
    assert event['contextBudget'] == 2000 - budget.reserve_tokens
    assert breakdown['summaryTokens'] > 0 and breakdown['toolSchemaTokens'] > 0
    assert breakdown['messageCount'] == 3 and breakdown['toolCount'] == 1
    assert breakdown['toolMessageTokens'] > 0
    assert breakdown['instructionTokens'] + breakdown['summaryTokens'] == (
        budget.instruction_tokens + budget.tool_schema_tokens)
    assert breakdown['messageTokens'] == budget.message_tokens
    assert breakdown['availableForMessages'] == budget.available_for_messages
    assert event['remainingContextTokens'] == budget.remaining_context_tokens
    assert event['effectiveInstructionTokens'] == breakdown['instructionTokens']
    assert context_usage_snapshot(messages, tools, 30)['remainingContextTokens'] == 0


def test_context_snapshot_atomic_replay_and_message_reload(setup):
    db, store, job = setup
    snapshot = _snapshot(job)
    with pytest.raises(KeyError, match='unauthorized'):
        store.record_context_usage('intruder', job.run_id, snapshot)
    seq = store.record_context_usage('alice', job.run_id, snapshot)
    assert seq > 0
    assert store.events('alice', job.run_id)[-1][1] == {
        'event': 'on_context_usage', 'data': snapshot}
    assert store.events('intruder', job.run_id) == []
    snapshot_2 = {**snapshot, 'remainingContextTokens': 4}
    store.record_context_usage('alice', job.run_id, snapshot_2)
    with db.connect() as conn:
        assert json.loads(conn.execute('SELECT state FROM runs WHERE id=?',
                                       (job.run_id,)).fetchone()[0])['contextUsage'] == snapshot_2
    assert store.finish('alice', job.run_id, status='complete', text='The plan is ready')
    final = store.events('alice', job.run_id)[-1][1]
    assert final['responseMessage']['metadata']['contextUsage'] == snapshot_2
    reopened = WorkspaceRepository(SQLiteDatabase(db.root))
    messages = reopened.messages('alice', job.conversation_id)['messages']
    assert messages[-1]['metadata']['contextUsage'] == snapshot_2
    with pytest.raises(KeyError):
        store.record_context_usage('alice', job.run_id, snapshot)


def test_snapshot_failed_write_keeps_run_state_and_event_log_unchanged(setup):
    _, store, job = setup
    count = len(store.events('alice', job.run_id))
    with pytest.raises(ValueError, match='256 KiB'):
        store.record_context_usage('alice', job.run_id, {'leak': 'z' * 300000})
    assert len(store.events('alice', job.run_id)) == count
    assert store.get('alice', job.run_id).status == 'running'
    assert store.finish('alice', job.run_id, status='interrupted')
    assert 'metadata' not in store.events('alice', job.run_id)[-1][1]['responseMessage']


@pytest.mark.asyncio
async def test_context_usage_event_visible_on_native_http_sse_after_restart(setup, monkeypatch):
    db, store, job = setup
    snapshot = _snapshot(job)
    store.record_context_usage('alice', job.run_id, snapshot)
    restarted = GenerationStore(SQLiteDatabase(db.root))
    assert restarted.recover_orphans() == 1
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: restarted)
    monkeypatch.setattr(generation_routes, '_owner', lambda request: 'alice')
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://lsm') as client:
        response = await client.get('/api/agents/chat/stream/' + job.conversation_id)
        assert response.status_code == 200
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith('data: ')]
        assert any(item.get('event') == 'on_context_usage' and item['data'] == snapshot
                   for item in events)
        assert events[-1]['responseMessage']['metadata']['contextUsage'] == snapshot
        next_page = await client.get('/api/agents/chat/stream/' + job.conversation_id,
                                     params={'after': 1})
        assert next_page.status_code == 200
        assert 'on_context_usage' in next_page.text


@pytest.mark.asyncio
async def test_runner_publishes_budget_without_triggering_summary(setup):
    db, store, job = setup
    WorkspaceRepository(db).save_setting('alice', 'endpoints', {
        'summarization': {'enabled': False},
    })

    async def empty(*args, **kwargs):
        if False:
            yield None

    async def emit(_):
        pass

    profile = ProviderConfig('openai', 'test', 'https://invalid.example/v1', '')
    runner = AgentRunner('alice', job, db, store, scopes=set(), grant_expires=None,
                         stream_tools=empty, stream_text=empty, on_text=emit, profile=profile)
    state = AgentLoopState(AgentContext(profile, [], {'max_context_tokens': 900}),
                           [{'role': 'user', 'content': 'test'}])
    await runner._before_model(state)
    events = [item for _, item in store.events('alice', job.run_id)
              if item.get('event') == 'on_context_usage']
    assert len(events) == 1
    assert events[0]['data']['breakdown']['messageCount'] == 1
    assert store.finish('alice', job.run_id, status='complete', text='done')
    assert store.events('alice', job.run_id)[-1][1]['responseMessage']['metadata']['contextUsage'] == events[0]['data']
