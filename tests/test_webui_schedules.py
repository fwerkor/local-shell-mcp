"""Scheduled chat state, cadence, claim and ownership regression tests."""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import schedule_routes
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def state(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path)
    repo = WorkspaceRepository(db)
    monkeypatch.setattr(schedule_routes, '_repo', lambda: repo)
    monkeypatch.setattr(schedule_routes, '_owner',
                        lambda request: request.headers.get('x-owner', 'alice'))
    agent = AgentRepository(db).create('alice', {
        'name': 'Timer', 'provider': 'openAI', 'model': 'mock-model',
    })
    app = Starlette(routes=schedule_routes.schedule_routes())
    yield app, repo, agent
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_schedule_create_retry_update_delete_and_owner(state, monkeypatch):
    app, repo, agent = state
    payload = {
        'name': 'Daily digest', 'prompt': 'Summarize this morning.',
        'agent_id': agent['id'], 'cadence': {'frequency': 'daily', 'hour': 9, 'minute': 0},
        'timezone': 'Asia/Singapore', 'target': 'new',
        'clientRequestId': 'test-create-1',
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        result = await c.post('/api/schedules', json=payload)
        assert result.status_code == 201, result.text
        schedule = result.json()
        sid = schedule['id']
        assert schedule['nextRunAt'] and schedule['configRevision'] == 0
        retry = await c.post('/api/schedules', json=payload)
        assert retry.json()['id'] == sid
        assert len((await c.get('/api/schedules')).json()['schedules']) == 1
        assert (await c.get('/api/schedules', headers={'x-owner': 'bob'})).json()['schedules'] == []
        assert (await c.patch('/api/schedules/' + sid, headers={'x-owner': 'bob'},
                              json={'name': 'other'})).status_code == 404
        assert (await c.patch('/api/schedules/' + sid, json={
            'expectedConfigRevision': 3, 'name': 'Wrong revision'})).status_code == 409
        changed = await c.patch('/api/schedules/' + sid, json={
            'expectedConfigRevision': 0, 'name': 'New digest',
        })
        assert changed.status_code == 200 and changed.json()['configRevision'] == 1

        async def simulated_dispatch(occurrence, database):
            occurrence_id, owner, _sid, _config, _due = occurrence
            schedule_routes._settle(database, occurrence_id, 'started',
                                    conversation_id='test-conversation', run_id='test-run')
        monkeypatch.setattr(schedule_routes, '_dispatch', simulated_dispatch)
        started = await c.post('/api/schedules/' + sid + '/run')
        assert started.status_code == 200 and started.json()['conversationId'] == 'test-conversation'
        assert (await c.post('/api/schedules/' + sid + '/run')).status_code == 409
        assert len((await c.get('/api/schedules/' + sid)).json()['inFlight']) == 1
        assert (await c.delete('/api/schedules/' + sid)).status_code == 200
        assert (await c.get('/api/schedules/' + sid)).status_code == 404


def test_cadences_and_restart_persistence(state):
    _, repo, agent = state
    assert schedule_routes.next_run({'frequency': 'cron', 'expression': '*/15 * * * *'},
                                    'UTC', after_ms=1795426200000) > 1795426200000
    with pytest.raises(HTTPException):
        schedule_routes.next_run({'frequency': 'cron', 'expression': 'not cron'},
                                 'UTC', after_ms=1795426200000)
    assert schedule_routes.next_run({'frequency': 'weekdays', 'hour': 9, 'minute': 0},
                                    'Asia/Singapore', after_ms=1795426200000) > 1795426200000
    assert SQLiteDatabase(repo.database.root).path == repo.database.path


@pytest.mark.asyncio
async def test_schedule_dispatch_creates_real_generation_and_settles(state, monkeypatch):
    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    app, repo, agent = state
    store = GenerationStore(repo.database)
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)
    import local_shell_mcp.webui.providers as providers
    monkeypatch.setattr(providers, 'provider_config',
                        lambda *args, **kwargs: ProviderConfig('openai', 'mock-model', 'http://mock', ''))
    dispatched = []

    async def fake_start(owner, generation, profile, selected_agent, **kwargs):
        dispatched.append((owner, generation, profile, selected_agent, kwargs))
        return True

    monkeypatch.setattr(generation_routes, '_start_task', fake_start)
    payload = {
        'name': 'Scheduled task', 'prompt': 'Generate a digest.',
        'agent_id': agent['id'], 'cadence': {'frequency': 'hourly', 'hour': 0, 'minute': 5},
        'timezone': 'Asia/Singapore', 'clientRequestId': 'schedule-real-1',
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        created = (await c.post('/api/schedules', json=payload)).json()
        started = await c.post('/api/schedules/' + created['id'] + '/run')
        assert started.status_code == 200, started.text
        assert len(dispatched) == 1
        owner, generation, _, _, kwargs = dispatched[0]
        assert owner == 'alice' and not kwargs['granted_scopes']
        assert repo.conversation('alice', generation.conversation_id)['title'] == 'Generate a digest.'
        # Claim retry does not execute the model twice.
        assert (await c.post('/api/schedules/' + created['id'] + '/run')).status_code == 409
        store.finish('alice', generation.run_id, status='complete', text='Digest')
        schedule_routes._refresh(repo.database)
        final = (await c.get('/api/schedules/' + created['id'])).json()
        assert final['runCount'] == 1 and final['failureCount'] == 0
        assert final['lastRun']['status'] == 'success'
        assert final['inFlight'] == []


def test_crashed_claim_is_recoverable_once(state):
    app, repo, agent = state
    import time

    from local_shell_mcp.webui.storage import _json, _now
    schedule_id = 'recover-schedule'
    occurrence_id = 'recover-once'
    config = {
        'name': 'Recovery', 'prompt': 'Hello', 'agent_id': agent['id'],
        'cadence': {'frequency': 'daily', 'hour': 12, 'minute': 0},
        'timezone': 'UTC',
    }
    timestamp = _now() - 200_000_000
    with repo.database.connect() as db:
        db.execute('INSERT INTO webui_schedules '
                   '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)',
                   (schedule_id, 'alice', schedule_id, _json(config), 1,
                    int(time.time() * 1000), timestamp, timestamp))
        db.execute('INSERT INTO webui_schedule_runs '
                   '(id,owner,schedule_id,due_at,status,created_at,updated_at) '
                   "VALUES(?,?,?,?,?,?,?)",
                   (occurrence_id, 'alice', schedule_id, int(time.time() * 1000),
                    'claimed', timestamp, timestamp))
    recovered = schedule_routes._recover_claimed(repo.database)
    assert len(recovered) == 1 and recovered[0][0] == occurrence_id
    assert schedule_routes._recover_claimed(repo.database) == []


def test_schedule_cadence_validation_and_calendar_matches():
    from datetime import datetime

    from local_shell_mcp.webui.schedule_routes import _cron_field, _matches, _parse_cadence, _zone

    assert _cron_field('0,15-45/15', 0, 59) == {0, 15, 30, 45}
    assert _cron_field('0,7', 0, 7, weekday=True) == {0}
    assert _cron_field('*/20', 0, 59) == {0, 20, 40}
    for expression in ('*//2', '*/0', '99', '5-3', '1-6/99', ','):
        with pytest.raises((ValueError, TypeError)):
            _cron_field(expression, 0, 59)
    with pytest.raises(HTTPException):
        _zone('Mars/Alpha')
    with pytest.raises(HTTPException):
        _zone(99)
    for invalid in (
        [], {}, {'frequency': 'unknown'},
        {'frequency': 'daily', 'hour': 25, 'minute': 0},
        {'frequency': 'hourly', 'hour': 0, 'minute': None},
        {'frequency': 'weekly', 'hour': 9, 'minute': 0, 'daysOfWeek': []},
        {'frequency': 'weekly', 'hour': 9, 'minute': 0, 'daysOfWeek': ['Monday']},
        {'frequency': 'cron', 'expression': 42},
        {'frequency': 'cron', 'expression': '* * *'},
        {'frequency': 'cron', 'expression': '*/0 * * * *'},
        {'frequency': 'cron', 'expression': '* * * * 9'},
    ):
        with pytest.raises(HTTPException):
            _parse_cadence(invalid)
    monday = datetime(2026, 11, 23, 9, 0)
    sunday = datetime(2026, 11, 22, 9, 0)
    assert _matches(monday, _parse_cadence({
        'frequency': 'daily', 'hour': 9, 'minute': 0}))
    assert not _matches(sunday, _parse_cadence({
        'frequency': 'weekdays', 'hour': 9, 'minute': 0}))
    assert _matches(monday, _parse_cadence({
        'frequency': 'weekly', 'hour': 9, 'minute': 0, 'daysOfWeek': [1]}))
    assert not _matches(sunday, _parse_cadence({
        'frequency': 'weekly', 'hour': 9, 'minute': 0, 'daysOfWeek': [1]}))
    assert _matches(monday, _parse_cadence({
        'frequency': 'cron', 'expression': '0 9 * 11 1'}))
    assert _matches(monday, _parse_cadence({
        'frequency': 'cron', 'expression': '0 9 23 11 *'}))
    assert _matches(monday, _parse_cadence({
        'frequency': 'cron', 'expression': '0 9 24 11 1'}))
    assert not _matches(monday, _parse_cadence({
        'frequency': 'cron', 'expression': '0 8 * * *'}))


@pytest.mark.asyncio
async def test_schedule_rejects_invalid_create_update_and_origin(state, monkeypatch):
    app, repo, agent = state
    valid = {
        'name': 'Daily test', 'prompt': 'Prompt', 'agent_id': agent['id'],
        'cadence': {'frequency': 'daily', 'hour': 9, 'minute': 0},
        'timezone': 'UTC', 'clientRequestId': 'invalid-test-id',
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        invalid = [
            ({'name': ''}, 400), ({'prompt': None}, 400),
            ({'name': 'n' * 257}, 400),
            ({'agent_id': 'missing'}, 404),
            ({'clientRequestId': ''}, 400),
            ({'clientRequestId': 3}, 400),
            ({'enabled': 1}, 400),
            ({'target': 'existing'}, 400),
            ({'file_ids': ['x'] * 11}, 400),
            ({'file_ids': [3]}, 400),
            ({'chatProjectId': 'unknown'}, 404),
            ({'timezone': 'unknown/timezone'}, 400),
            ({'cadence': {'frequency': 'cron', 'expression': 'bad'}}, 400),
        ]
        for patch, status in invalid:
            request = await c.post('/api/schedules', json={**valid, **patch})
            assert request.status_code == status, (patch, request.text)
        assert (await c.post('/api/schedules', json={},
                             headers={'origin': 'https://malicious.example'})).status_code == 403
        assert (await c.post('/api/schedules', json={})).status_code == 400
        created = await c.post('/api/schedules', json={**valid, 'enabled': False})
        assert created.status_code == 201
        sid = created.json()['id']
        assert not created.json()['enabled'] and created.json()['nextRunAt'] is None
        assert (await c.patch('/api/schedules/' + sid,
                              json={'agent_id': 'missing'})).status_code == 404
        assert (await c.patch('/api/schedules/' + sid,
                              json={'enabled': 'yes'})).status_code == 400
        enabled = await c.patch('/api/schedules/' + sid,
                                json={'enabled': True, 'expectedConfigRevision': 0})
        assert enabled.status_code == 200
        assert enabled.json()['nextRunAt']
        assert (await c.get('/api/schedules/not-found')).status_code == 404
        assert (await c.post('/api/schedules/not-found/run')).status_code == 404
        monkeypatch.setitem(schedule_routes._LIMITS, 'maxPerUser', 1)
        rejected = await c.post('/api/schedules', json={**valid, 'clientRequestId': 'other-try'})
        assert rejected.status_code == 400


def test_due_claim_terminal_settlement_and_disabled_recovery(state):
    import time

    from local_shell_mcp.webui.storage import _json, _now

    _, repo, agent = state
    config = {'name': 'Due', 'prompt': 'Prompt', 'agent_id': agent['id'],
              'cadence': {'frequency': 'hourly', 'hour': 0, 'minute': 0},
              'timezone': 'UTC'}
    ts = _now()
    with repo.database.connect() as db:
        db.execute('INSERT INTO webui_schedules '
                   '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)',
                   ('due', 'alice', 'due', _json(config), 1,
                    int(time.time() * 1000) - 1000, ts, ts))
    claimed = schedule_routes._claim_due(repo.database)
    assert len(claimed) == 1
    assert schedule_routes._claim_due(repo.database) == []
    assert schedule_routes._claim_due(repo.database, manual=True) == []
    occurrence_id = claimed[0][0]
    schedule_routes._settle(repo.database, occurrence_id, 'error', error='bad_model')
    schedule_routes._settle(repo.database, occurrence_id, 'success')
    with repo.database.connect() as db:
        record = db.execute('SELECT * FROM webui_schedules WHERE id=?', ('due',)).fetchone()
        assert record['run_count'] == 1 and record['failure_count'] == 1
        db.execute('UPDATE webui_schedule_runs SET status=?,updated_at=? WHERE id=?',
                   ('claimed', ts - 200_000_000, occurrence_id))
        db.execute('UPDATE webui_schedules SET enabled=0 WHERE id=?', ('due',))
    assert schedule_routes._recover_claimed(repo.database) == []
    with repo.database.connect() as db:
        recovered = db.execute('SELECT status FROM webui_schedule_runs WHERE id=?',
                               (occurrence_id,)).fetchone()
        assert recovered['status'] == 'interrupted'


@pytest.mark.asyncio
async def test_schedule_worker_start_stop_and_dispatch_rejection(state, monkeypatch):
    import asyncio

    _, repo, agent = state
    await schedule_routes.start_schedule_worker(repo.database)
    await asyncio.sleep(0.03)
    await schedule_routes.start_schedule_worker(repo.database)  # idempotent lifecycle
    await schedule_routes.shutdown_schedule_worker()

    # These preflight failures must not start the provider or a native tool.
    await schedule_routes._dispatch(
        ('missing-agent', 'alice', 'missing', {
            'agent_id': 'does-not-exist', 'prompt': 'Prompt',
        }, 0), repo.database,
    )
    await schedule_routes._dispatch(
        ('missing-project', 'alice', 'missing', {
            'agent_id': agent['id'], 'prompt': 'Prompt', 'chatProjectId': 'deleted',
        }, 0), repo.database,
    )
    assert schedule_routes._WORKER is None
