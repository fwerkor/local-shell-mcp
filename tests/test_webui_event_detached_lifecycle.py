"""Authenticated source Event Actor -> native background task -> host-proven wake."""
from __future__ import annotations

import asyncio
import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner, providers
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.background_tools import (
    _TOOL_TASKS,
    check_tool_task,
    shutdown_background_tools,
    start_tool_task,
)
from local_shell_mcp.webui.detached_event_actions import _EVENT_TYPE
from local_shell_mcp.webui.event_triggers import (
    _NO_PARENT,
    enqueue_event,
    get_event,
    mint_source_key,
    process_event_deliveries,
    register_bound_child,
    revoke_source_key,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.fixture
def environment(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / 'state')
    repo = AgentRepository(db)
    child = repo.create('owner', {'name': 'child', 'provider': 'openai', 'model': 'test',
                                  'tools': ['run_shell'],
                                  'tool_options': {'run_shell': {'run_in_background': True}}})
    parent = repo.create('owner', {'name': 'parent', 'provider': 'openai', 'model': 'test',
                                   'tools': [], 'subagents': {'enabled': True,
                                                             'agent_ids': [child['id']]}})
    generation, _ = GenerationStore(db).begin('owner', {'text': 'delegate'}, parent)
    GenerationStore(db).finish('owner', generation.run_id, status='complete', text='delegated')
    source = mint_source_key(db, 'owner', permissions=('continue',))
    binding = register_bound_child(db, 'owner', source['id'], 'detached-source-key',
                                   actor_id='observed',
                                   parent_conversation_id=generation.conversation_id,
                                   parent_message_id=generation.response_message_id,
                                   target_agent_id=child['id'])
    monkeypatch.setattr(providers, 'provider_config', lambda *args: ProviderConfig(
        'openai', 'test', 'https://example.invalid', ''))
    monkeypatch.setattr(agent_runner, 'provider_config', providers.provider_config)
    return db, child, source, binding


def post(env, suffix='1'):
    db, child, source, binding = env
    return enqueue_event(db, 'owner', source['id'], 'delivery-' + suffix, {
        'mode': 'continue', 'event': {'id': suffix, 'type': 'host.modified',
                                     'occurredAt': 1760000000000},
        'target': {'agentId': child['id'], 'conversationId': binding['threadId'],
                   'parentMessageId': _NO_PARENT, 'bindingId': binding['id']},
        'input': 'Synchronize the observed change',
        'expectedAction': {'toolName': 'run_shell',
                           'argumentSubset': {'command': 'echo checked'}},
    })['id']


async def admitted(env):
    db, child, source, binding = env
    root_id = post(env)
    captured = []

    async def model_dispatch(owner, generation, *args, **kwargs):
        captured.append(generation)

    assert await process_event_deliveries(db, dispatch=model_dispatch) == 1
    with db.connect() as conn:
        claimed = conn.execute('SELECT lease_owner,status FROM agent_event_deliveries WHERE id=?',
                               (root_id,)).fetchone()
        assert claimed['status'] == 'leased'
    return root_id, (root_id, claimed['lease_owner']), captured, model_dispatch


async def launch(env, *, run, lease, background_output, call_id='verified', command='echo checked'):
    db, child, source, binding = env
    started = asyncio.Event()
    gate = asyncio.Event()
    attempts = []

    async def native_dispatch(call, scopes, expires, scope_conversation):
        attempts.append((call.name, dict(call.arguments)))
        started.set()
        await gate.wait()
        return background_output

    call = ModelToolCall(call_id, 'run_shell', {'command': command})
    receipt = json.loads(await start_tool_task(db, 'owner', run.conversation_id,
                          run.conversation_id, run.run_id, call, scopes=frozenset(),
                          grant_expires=None, dispatch=native_dispatch,
                          event_delivery_lease=lease))
    assert receipt['status'] == 'running'
    await asyncio.wait_for(started.wait(), 3)
    return receipt['background_task_id'], gate, attempts


@pytest.mark.asyncio
async def test_detached_completion_is_one_host_native_call_then_one_internal_continue(environment):
    db, child, source, binding = environment
    root_id, lease, runs, dispatch = await admitted(environment)
    native_id, gate, attempts = await launch(environment, run=runs[0], lease=lease,
                                            background_output='{"ok":true,"stdout":"done"}')
    with db.connect() as conn:
        action = conn.execute('SELECT status,task_id,idempotency_key FROM agent_event_detached_actions '
                              'WHERE delivery_id=?', (root_id,)).fetchone()
        assert action['status'] == 'running' and action['task_id'] == native_id
        assert len(action['idempotency_key']) == 64
    # Model has seen only the launch receipt, not a completed native action.
    GenerationStore(db).append('owner', runs[0].run_id, {'event': 'on_run_step_completed',
        'data': {'result': {'id': 'launch', 'type': 'tool_call', 'tool_call': {
            'name': 'run_shell', 'args': {'command': 'echo checked'},
            'output': json.dumps({'background_task_id': native_id, 'status': 'running'})}}}})
    GenerationStore(db).finish('owner', runs[0].run_id, status='complete', text='Detached task dispatched')
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    assert get_event(db, 'owner', source['id'], root_id)['status'] == 'leased'
    gate.set()
    await asyncio.wait_for(_TOOL_TASKS[native_id], 3)
    assert check_tool_task(db, 'owner', runs[0].conversation_id, native_id)['status'] == 'completed'
    assert await process_event_deliveries(db, dispatch=dispatch) == 1
    event_status = get_event(db, 'owner', source['id'], root_id)
    assert event_status['status'] == 'succeeded'
    internal_id = event_status['result']['completionEvent']
    with db.connect() as conn:
        row = conn.execute('SELECT envelope FROM agent_event_deliveries WHERE id=?',
                           (internal_id,)).fetchone()
        event = json.loads(row['envelope'])
        assert event['event']['type'] == _EVENT_TYPE
        assert event['event']['payload']['invocationId'] == root_id
        assert event['event']['payload']['taskId'] == native_id
        assert event['input'].startswith('Resume the suspended event actor')
        completion = json.loads(event['input'].split('Verified detached tool completion: ', 1)[1])
        assert completion == {'taskId': native_id, 'toolName': 'run_shell',
                              'toolCallId': 'verified',
                              'result': '{"ok":true,"stdout":"done"}'}
    with db.connect() as conn:
        continuation_input = conn.execute('SELECT text FROM messages WHERE id=?',
                                          (runs[1].user_message_id,)).fetchone()['text']
    assert native_id in continuation_input and 'stdout' in continuation_input
    assert len(runs) == 2  # root event turn and exactly one internal continuation
    GenerationStore(db).finish('owner', runs[1].run_id, status='complete', text='Finalized')
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    assert get_event(db, 'owner', source['id'], internal_id)['status'] == 'succeeded'
    assert len(attempts) == 1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_detached_actions').fetchone()[0] == 1
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_failed_native_terminal_cannot_be_misreported_as_expected_action(environment):
    db, child, source, binding = environment
    root_id, lease, runs, dispatch = await admitted(environment)
    native_id, gate, attempts = await launch(environment, run=runs[0], lease=lease,
                                            background_output='{"ok":false,"error":"denied"}')
    GenerationStore(db).finish('owner', runs[0].run_id, status='complete', text='claimed success')
    gate.set()
    await asyncio.wait_for(_TOOL_TASKS[native_id], 3)
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    assert get_event(db, 'owner', source['id'], root_id)['status'] == 'dead'
    with db.connect() as conn:
        action = conn.execute('SELECT evidence,status FROM agent_event_detached_actions '
                              'WHERE delivery_id=?', (root_id,)).fetchone()
        assert action['status'] == 'failed'
        assert json.loads(action['evidence'])['status'] == 'failed'
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0] == 1
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_source_revocation_cannot_enqueue_a_new_trusted_internal_completion(environment):
    db, child, source, binding = environment
    root_id, lease, runs, dispatch = await admitted(environment)
    native_id, gate, attempts = await launch(environment, run=runs[0], lease=lease,
                                            background_output='{"ok":true}')
    GenerationStore(db).finish('owner', runs[0].run_id, status='complete', text='dispatched')
    assert revoke_source_key(db, 'owner', source['id'])
    gate.set()
    await asyncio.wait_for(asyncio.gather(_TOOL_TASKS[native_id], return_exceptions=True), 3)
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    assert get_event(db, 'owner', source['id'], root_id)['status'] == 'dead'
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0] == 1
    await shutdown_background_tools()
