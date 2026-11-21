"""Source Event Actor detached launches are never guessed or duplicated on restart."""
from __future__ import annotations

import asyncio
import json

import pytest
from test_webui_event_detached_lifecycle import admitted, launch
from test_webui_event_detached_lifecycle import environment as environment

from local_shell_mcp.webui import event_triggers
from local_shell_mcp.webui.background_tools import _TOOL_TASKS, shutdown_background_tools
from local_shell_mcp.webui.detached_event_actions import reserve
from local_shell_mcp.webui.event_triggers import get_event, process_event_deliveries
from local_shell_mcp.webui.generations import GenerationStore


@pytest.mark.asyncio
async def test_crashed_reserved_native_launch_must_not_be_retried_or_claim_success(environment):
    db, child, source, binding = environment
    root_id, lease, runs, dispatch = await admitted(environment)
    run = runs[0]
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert reserve(conn, owner='owner', run_id=run.run_id, lease=lease,
                       task_id='tooltask_opaque', tool_name='run_shell',
                       tool_call_id='call-reserved', arguments={'command':'echo checked'},
                       argument_hash='native-hash', at=1)
        conn.execute('UPDATE agent_event_detached_actions SET recovery_after=0 WHERE delivery_id=?',
                     (root_id,))
    GenerationStore(db).finish('owner', run.run_id, status='complete', text='claimed detached launch')
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    status = get_event(db, 'owner', source['id'], root_id)
    assert status['status'] == 'dead' and status['error']['code'] == 'DETACHED_ACTION_LAUNCH_INDETERMINATE'
    with db.connect() as conn:
        assert conn.execute('SELECT status FROM agent_event_detached_actions '
                            'WHERE delivery_id=?', (root_id,)).fetchone()['status'] == 'launch_indeterminate'
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0] == 1
    assert len(runs) == 1  # No second model turn or unverified internal wake.


@pytest.mark.asyncio
async def test_controller_crash_after_durable_terminal_replays_single_internal_wake(environment):
    db, child, source, binding = environment
    root_id, lease, runs, dispatch = await admitted(environment)
    native_id, gate, calls = await launch(environment, run=runs[0], lease=lease,
                                          background_output='{"ok":true}')
    GenerationStore(db).finish('owner', runs[0].run_id, status='complete', text='queued detached')
    gate.set()
    await asyncio.wait_for(_TOOL_TASKS[native_id], 4)
    # In-memory event-owner references are not authoritative after restart.
    event_triggers._OWNED.clear()
    assert await process_event_deliveries(db, dispatch=dispatch) == 1
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    receipt = get_event(db, 'owner', source['id'], root_id)
    assert receipt['status'] == 'succeeded'
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries '
                            'WHERE envelope LIKE ?', ('%librechat.event_actor.detached_completion%',)).fetchone()[0] == 1
    assert len(runs) == 2 and len(calls) == 1
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_tampered_terminal_evidence_fails_closed_without_fake_completion(environment):
    db, child, source, binding = environment
    root_id, lease, runs, dispatch = await admitted(environment)
    native_id, gate, calls = await launch(environment, run=runs[0], lease=lease,
                                          background_output='{"ok":true}')
    GenerationStore(db).finish('owner', runs[0].run_id, status='complete', text='pending')
    gate.set()
    await asyncio.wait_for(_TOOL_TASKS[native_id], 4)
    with db.connect() as conn:
        evidence = json.loads(conn.execute('SELECT evidence FROM agent_event_detached_actions '
                                           'WHERE delivery_id=?', (root_id,)).fetchone()['evidence'])
        evidence['idempotencyKey'] = 'forged'
        conn.execute('UPDATE agent_event_detached_actions SET evidence=? WHERE delivery_id=?',
                     (json.dumps(evidence), root_id))
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    receipt = get_event(db, 'owner', source['id'], root_id)
    assert receipt['status'] == 'dead'
    assert receipt['error']['code'] == 'EXPECTED_ACTION_INVALID_TERMINAL_PROOF'
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0] == 1
    await shutdown_background_tools()


@pytest.mark.asyncio
async def test_second_expected_action_with_distinct_tool_id_cannot_launch(environment):
    db, child, source, binding = environment
    root_id, lease, runs, dispatch = await admitted(environment)
    native_id, gate, calls = await launch(environment, run=runs[0], lease=lease,
                                          background_output='{"ok":true}')
    from local_shell_mcp.webui.background_tools import start_tool_task
    from local_shell_mcp.webui.providers import ModelToolCall

    async def forbidden(*args):
        raise AssertionError('Conflicting action must never launch')

    with pytest.raises(PermissionError, match='different detached action'):
        await start_tool_task(db, 'owner', runs[0].conversation_id,
                              runs[0].conversation_id, runs[0].run_id,
                              ModelToolCall('different-id','run_shell',{'command':'echo checked'}),
                              scopes=frozenset(), grant_expires=None,
                              event_delivery_lease=lease, dispatch=forbidden)
    assert len(calls) == 1
    gate.set()
    await asyncio.wait_for(_TOOL_TASKS[native_id], 4)
    await shutdown_background_tools()
