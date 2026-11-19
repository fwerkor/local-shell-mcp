"""Source detached Event Actor CAS reservation, cancellation, unknown launch paths."""
from __future__ import annotations

import json

import pytest
from test_webui_event_detached_lifecycle import admitted
from test_webui_event_detached_lifecycle import environment as environment

from local_shell_mcp.webui.detached_event_actions import (
    mark_running,
    reserve,
    settle,
)


def claim(db, lease, run, *, at, command='echo checked', task='tooltask_once', call='once',
          owner='owner'):
    return reserve(db, owner=owner, run_id=run.run_id, lease=lease, task_id=task,
                   tool_name='run_shell', tool_call_id=call, arguments={'command': command},
                   argument_hash='hash', at=at)


@pytest.mark.asyncio
async def test_source_reserved_action_requires_live_lease_and_expected_arguments(environment):
    db, child, source, binding = environment
    root, lease, runs, dispatch = await admitted(environment)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert claim(conn, lease, runs[0], at=1, command='wrong') is False
        with pytest.raises(PermissionError, match='source lease'):
            claim(conn, ('other-trigger', 'bad-lease'), runs[0], at=1)
        assert conn.execute('SELECT count(*) FROM agent_event_detached_actions').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_source_repeated_exact_reservation_uses_one_row_and_different_identity_fails(environment):
    db, child, source, binding = environment
    root, lease, runs, dispatch = await admitted(environment)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert claim(conn, lease, runs[0], at=1)
        assert claim(conn, lease, runs[0], at=1)
        assert conn.execute('SELECT count(*) FROM agent_event_detached_actions').fetchone()[0] == 1
        with pytest.raises(PermissionError, match='different detached action'):
            claim(conn, lease, runs[0], at=1, task='tooltask_other')


@pytest.mark.asyncio
async def test_source_terminal_unknown_or_cancelled_status_is_persisted_atomically(environment):
    db, child, source, binding = environment
    root, lease, runs, dispatch = await admitted(environment)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert claim(conn, lease, runs[0], at=1)
        assert mark_running(conn, 'tooltask_once', 'owner', 2)
        assert mark_running(conn, 'tooltask_once', 'owner', 3) is False
        settle(conn, 'tooltask_once', 'owner', 'uncertain', None, None, at=4)
        assert conn.execute('SELECT status FROM agent_event_detached_actions WHERE delivery_id=?',
                            (root,)).fetchone()['status'] == 'launch_indeterminate'
        settle(conn, 'tooltask_does_not_exist', 'owner', 'completed', 'unused', None, at=4)
        assert conn.execute('SELECT count(*) FROM agent_event_detached_actions').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_source_cancelled_terminal_proof_must_not_create_successful_wake(environment):
    db, child, source, binding = environment
    root, lease, runs, dispatch = await admitted(environment)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert claim(conn, lease, runs[0], at=1)
        settle(conn, 'tooltask_once', 'owner', 'cancelled', None, 'cancelled', at=2)
        row = conn.execute('SELECT status,evidence FROM agent_event_detached_actions WHERE delivery_id=?',
                           (root,)).fetchone()
        assert row['status'] == 'cancelled'
        evidence = json.loads(row['evidence'])
        assert evidence['status'] == 'cancelled' and evidence['error'] == 'cancelled'


@pytest.mark.asyncio
async def test_source_malformed_generation_epoch_cannot_persist_forged_tool_success(environment):
    db, child, source, binding = environment
    root, lease, runs, dispatch = await admitted(environment)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert claim(conn, lease, runs[0], at=1)
        state = json.loads(conn.execute('SELECT state FROM runs WHERE id=?',
                                        (runs[0].run_id,)).fetchone()['state'])
        original = dict(state)
        state['generationCreatedAt'] = -1
        conn.execute('UPDATE runs SET state=? WHERE id=?', (json.dumps(state), runs[0].run_id))
        with pytest.raises(ValueError, match='invalid shape'):
            settle(conn, 'tooltask_once', 'owner', 'completed', 'done', None, at=2)
        conn.execute('UPDATE runs SET state=? WHERE id=?', (json.dumps(original), runs[0].run_id))
        assert conn.execute('SELECT evidence FROM agent_event_detached_actions WHERE delivery_id=?',
                            (root,)).fetchone()['evidence'] is None
