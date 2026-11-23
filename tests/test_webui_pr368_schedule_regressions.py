"""Focused scheduling regressions for PR #368 review."""
from __future__ import annotations

import time

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import schedule_routes
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.storage import WorkspaceRepository, _json, _now


@pytest.fixture
def state(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    repo = WorkspaceRepository(database)
    monkeypatch.setattr(schedule_routes, '_repo', lambda: repo)
    monkeypatch.setattr(schedule_routes, '_owner',
                        lambda request: request.headers.get('x-owner', 'alice'))
    agent = AgentRepository(database).create('alice', {
        'name': 'Scheduled Agent', 'provider': 'openAI', 'model': 'mock-model',
    })
    return Starlette(routes=schedule_routes.schedule_routes()), repo, agent


def _config(agent, cadence=None):
    return {
        'name': 'Daily', 'prompt': 'Run', 'agent_id': agent['id'],
        'cadence': cadence or {'frequency': 'daily', 'hour': 9, 'minute': 0},
        'timezone': 'UTC', 'clientRequestId': 'test-request',
    }


@pytest.mark.asyncio
async def test_non_timing_edits_preserve_upcoming_occurrence(state, monkeypatch):
    app, repo, agent = state
    # UTC morning 08:58; creation picks tomorrow due to initial five-minute delay.
    current = 1795424280.0
    monkeypatch.setattr(schedule_routes.time, 'time', lambda: current)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        created = await c.post('/api/schedules', json=_config(agent))
        assert created.status_code == 201, created.text
        sid = created.json()['id']
        with repo.database.connect() as db:
            due = int(current * 1000) + 2 * 60_000
            db.execute('UPDATE webui_schedules SET next_run=? WHERE id=?', (due, sid))
        changed = await c.patch('/api/schedules/' + sid, json={'name': 'Renamed'})
        assert changed.status_code == 200, changed.text
        assert changed.json()['nextRunAt'] == schedule_routes._iso(due)
        changed_again = await c.patch('/api/schedules/' + sid, json={'prompt': 'New prompt'})
        assert changed_again.status_code == 200
        assert changed_again.json()['nextRunAt'] == schedule_routes._iso(due)


@pytest.mark.asyncio
async def test_paused_schedules_accept_explicit_run_now(state, monkeypatch):
    app, repo, agent = state
    async def dispatched(occurrence, database):
        schedule_routes._settle(database, occurrence[0], 'started',
                                conversation_id='manual-conversation', run_id='run')
    monkeypatch.setattr(schedule_routes, '_dispatch', dispatched)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        created = await c.post('/api/schedules', json={**_config(agent), 'enabled': False})
        assert created.status_code == 201
        sid = created.json()['id']
        run = await c.post('/api/schedules/' + sid + '/run')
        assert run.status_code == 200, run.text
        assert run.json()['conversationId'] == 'manual-conversation'
        assert (await c.get('/api/schedules/' + sid)).json()['enabled'] is False


def test_late_poll_does_not_skip_five_minute_cron_occurrence(state, monkeypatch):
    _, repo, agent = state
    # 2026-11-23 09:00 UTC schedule, worker arrives 20 seconds late.
    from datetime import UTC, datetime

    due = int(datetime(2026, 11, 23, 9, 0, tzinfo=UTC).timestamp() * 1000)
    monkeypatch.setattr(schedule_routes.time, 'time', lambda: (due + 20_000) / 1000)
    now = _now()
    config = _config(agent, {'frequency': 'cron', 'expression': '*/5 * * * *'})
    with repo.database.connect() as db:
        db.execute('INSERT INTO webui_schedules '
                   '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)',
                   ('cron', 'alice', 'cron', _json(config), 1, due, now, now))
    claims = schedule_routes._claim_due(repo.database)
    assert len(claims) == 1
    with repo.database.connect() as db:
        new_due = db.execute('SELECT next_run FROM webui_schedules WHERE id=?',
                             ('cron',)).fetchone()[0]
    assert new_due == due + 5 * 60_000


def test_claim_batch_excludes_running_before_limit_and_preserves_owner(state, monkeypatch):
    _, repo, agent = state
    due = int(time.time() * 1000) - 60_000
    now = _now()
    config = _config(agent)
    with repo.database.connect() as db:
        for index in range(26):
            owner = 'alice' if index < 25 else 'bob'
            sid = f's{index:02d}'
            db.execute('INSERT INTO webui_schedules '
                       '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (sid, owner, sid, _json(config), 1, due + index, now, now))
            if index < 25:
                db.execute('INSERT INTO webui_schedule_runs '
                           '(id,owner,schedule_id,due_at,status,created_at,updated_at) '
                           'VALUES(?,?,?,?,?,?,?)',
                           (f'r{index}', owner, sid, due, 'started', now, now))
    claims = schedule_routes._claim_due(repo.database)
    assert len(claims) == 1
    assert claims[0][1:3] == ('bob', 's25')
    assert schedule_routes._claim_due(repo.database) == []


@pytest.mark.asyncio
async def test_sub_five_minute_cron_rejected_independently_of_polling(state):
    app, _, agent = state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        for expression in ('*/2 * * * *', '0,3 9 * * *', '59 23 * * * ,'):
            result = await c.post('/api/schedules', json={
                **_config(agent, {'frequency': 'cron', 'expression': expression}),
                'clientRequestId': expression,
            })
            assert result.status_code == 400, (expression, result.text)
        normal = await c.post('/api/schedules', json={
            **_config(agent, {'frequency': 'cron', 'expression': '*/5 * * * *'}),
            'clientRequestId': 'safe-five-minute',
        })
        assert normal.status_code == 201, normal.text


def test_invalid_cron_step_rejected_not_interpreted_as_default(state):
    _, repo, agent = state
    from starlette.exceptions import HTTPException

    from local_shell_mcp.webui.schedule_routes import _parse_cadence

    for expression in ('*/-15 * * * *', '*/oops * * * *', '*/ * * * *',
                       '*/+5 * * * *', '*/0 * * * *', '*/x * * * *'):
        with pytest.raises(HTTPException):
            _parse_cadence({'frequency': 'cron', 'expression': expression})
