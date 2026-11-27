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
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    database = SQLiteDatabase(tmp_path)
    repo = WorkspaceRepository(database)
    monkeypatch.setattr(schedule_routes, '_repo', lambda: repo)
    monkeypatch.setattr(schedule_routes, '_owner',
                        lambda request: request.headers.get('x-owner', 'alice'))
    agent = AgentRepository(database).create('alice', {
        'name': 'Scheduled Agent', 'provider': 'openAI', 'model': 'mock-model',
    })
    yield Starlette(routes=schedule_routes.schedule_routes()), repo, agent
    get_settings.cache_clear()


def _config(agent, cadence=None):
    return {
        'name': 'Daily', 'prompt': 'Run', 'agent_id': agent['id'],
        'cadence': cadence or {'frequency': 'daily', 'hour': 9, 'minute': 0},
        'timezone': 'UTC', 'clientRequestId': 'test-request',
        'executionScopes': [],
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


@pytest.mark.asyncio
async def test_config_edit_preserves_next_run_advanced_concurrently(state, monkeypatch):
    app, repo, agent = state
    # Use an actual daily occurrence, not an arbitrary wall-clock minute.
    # A late claim should advance from the scheduled 09:00 occurrence.
    from datetime import UTC, datetime

    due = int(datetime(2026, 11, 25, 9, 0, tzinfo=UTC).timestamp() * 1000)
    now = due + 30_000
    monkeypatch.setattr(schedule_routes.time, "time", lambda: now / 1000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        created = await c.post('/api/schedules', json=_config(agent))
        assert created.status_code == 201
        sid = created.json()['id']
        with repo.database.connect() as db:
            db.execute('UPDATE webui_schedules SET next_run=? WHERE id=?', (due, sid))
        actual_validate = schedule_routes._validate
        claimed = []

        def concurrent_claim(owner, local_repo, config, *, partial=False, **kwargs):
            actual_validate(owner, local_repo, config, partial=partial, **kwargs)
            if partial and 'cadence' in config and 'clientRequestId' not in config:
                claimed.extend(schedule_routes._claim_due(repo.database))

        monkeypatch.setattr(schedule_routes, '_validate', concurrent_claim)
        changed = await c.patch('/api/schedules/' + sid, json={'name': 'Updated'})
        assert changed.status_code == 200, changed.text
        assert len(claimed) == 1
        with repo.database.connect() as db:
            actual_next = db.execute('SELECT next_run FROM webui_schedules WHERE id=?',
                                     (sid,)).fetchone()['next_run']
        assert actual_next == due + 24 * 60 * 60_000
        assert changed.json()['nextRunAt'] == schedule_routes._iso(actual_next)
        schedule_routes._settle(repo.database, claimed[0][0], 'success')
        assert schedule_routes._claim_due(repo.database) == []


@pytest.mark.asyncio
async def test_schedule_with_deleted_agent_can_be_paused(state):
    app, repo, agent = state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as c:
        created = await c.post('/api/schedules', json=_config(agent))
        assert created.status_code == 201
        sid = created.json()['id']
        assert AgentRepository(repo.database).delete('alice', agent['id'])
        paused = await c.patch('/api/schedules/' + sid, json={'enabled': False})
        assert paused.status_code == 200, paused.text
        assert paused.json()['enabled'] is False
        assert paused.json()['nextRunAt'] is None
        reenabled = await c.patch('/api/schedules/' + sid, json={'enabled': True})
        assert reenabled.status_code == 404


def test_sparse_leap_day_cron_keeps_future_occurrences(state, monkeypatch):
    from datetime import UTC, datetime

    _, repo, agent = state
    due = int(datetime(2028, 2, 29, 9, 0, tzinfo=UTC).timestamp() * 1000)
    monkeypatch.setattr(schedule_routes.time, 'time', lambda: (due + 20_000) / 1000)
    config = _config(agent, {'frequency': 'cron', 'expression': '0 9 29 2 *'})
    now = _now()
    with repo.database.connect() as db:
        db.execute('INSERT INTO webui_schedules '
                   '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)',
                   ('leap', 'alice', 'leap', _json(config), 1, due, now, now))
    claims = schedule_routes._claim_due(repo.database)
    assert len(claims) == 1
    future = int(datetime(2032, 2, 29, 9, 0, tzinfo=UTC).timestamp() * 1000)
    with repo.database.connect() as db:
        row = db.execute('SELECT next_run,enabled FROM webui_schedules WHERE id=?',
                         ('leap',)).fetchone()
    assert row['enabled'] == 1 and row['next_run'] == future


def test_exhausted_legacy_schedule_does_not_block_healthy_claims(state, monkeypatch):
    _, repo, agent = state
    due = int(time.time() * 1000) - 60_000
    now = _now()
    healthy = _config(agent)
    impossible = _config(agent, {'frequency': 'cron', 'expression': '0 9 31 2 *'})
    with repo.database.connect() as db:
        for sid, config in (('no-future', impossible), ('healthy', healthy)):
            db.execute('INSERT INTO webui_schedules '
                       '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (sid, 'alice', sid, _json(config), 1, due, now, now))
    claims = schedule_routes._claim_due(repo.database)
    assert {item[2] for item in claims} == {'healthy', 'no-future'}
    with repo.database.connect() as db:
        invalid = db.execute('SELECT enabled,next_run FROM webui_schedules WHERE id=?',
                             ('no-future',)).fetchone()
    assert invalid['enabled'] == 1 and invalid['next_run'] is None
    assert schedule_routes._claim_due(repo.database) == []


@pytest.mark.asyncio
async def test_committed_but_unstarted_generation_is_recovered_once(state, monkeypatch):
    from local_shell_mcp.webui import generation_routes, providers
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    _, repo, agent = state
    config = _config(agent)
    now = _now()
    with repo.database.connect() as db:
        db.execute('INSERT INTO webui_schedules '
                   '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)',
                   ('stranded', 'alice', 'stranded', _json(config), 1,
                    int(time.time() * 1000) - 60_000, now, now))
    occurrence = schedule_routes._claim_due(repo.database)[0]
    store = GenerationStore(repo.database)
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        generation, fresh = store.begin('alice', {
            'text': config['prompt'], 'agent_id': agent['id'],
            'clientRequestId': 'schedule:' + occurrence[0],
        }, agent, _connection=db)
    assert fresh
    preserved = schedule_routes.unstarted_schedule_generations(repo.database)
    assert generation.run_id in preserved
    assert store.recover_orphans(preserved) == 0
    assert store.get('alice', generation.run_id).status == 'running'

    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)
    monkeypatch.setattr(providers, 'provider_config',
                        lambda *args, **kwargs: ProviderConfig('openai', 'mock', 'http://example', ''))
    starts = []

    async def record_start(owner, resumed, profile, selected_agent, **kwargs):
        starts.append(resumed.run_id)
        return True

    monkeypatch.setattr(generation_routes, '_start_task', record_start)
    await schedule_routes._dispatch(occurrence, repo.database)
    assert starts == [generation.run_id]
    with repo.database.connect() as db:
        run = db.execute('SELECT status,run_id FROM webui_schedule_runs WHERE id=?',
                         (occurrence[0],)).fetchone()
        assert run['status'] == 'started' and run['run_id'] == generation.run_id
        assert db.execute('SELECT COUNT(*) FROM generation_requests WHERE owner=? AND '
                          'client_request_id=?',
                          ('alice', 'schedule:' + occurrence[0])).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_prior_execution_lease_prevents_schedule_replay(state, monkeypatch):
    from local_shell_mcp.webui import generation_routes, providers
    from local_shell_mcp.webui.generation_actor_lease import ActorLease
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    _, repo, agent = state
    config = _config(agent)
    now = _now()
    with repo.database.connect() as db:
        db.execute('INSERT INTO webui_schedules '
                   '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)',
                   ('executed', 'alice', 'executed', _json(config), 1,
                    int(time.time() * 1000) - 60_000, now, now))
    occurrence = schedule_routes._claim_due(repo.database)[0]
    store = GenerationStore(repo.database)
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        generation, _ = store.begin('alice', {
            'text': config['prompt'], 'agent_id': agent['id'],
            'clientRequestId': 'schedule:' + occurrence[0],
        }, agent, _connection=db)
    lease = ActorLease.claim(repo.database, 'alice', generation.run_id)
    assert lease is not None
    assert generation.run_id not in schedule_routes.unstarted_schedule_generations(repo.database)
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)
    monkeypatch.setattr(providers, 'provider_config',
                        lambda *args, **kwargs: ProviderConfig('openai', 'mock', 'http://example', ''))

    async def forbidden_start(*args, **kwargs):
        pytest.fail('A previously executed scheduled generation must not run again')

    monkeypatch.setattr(generation_routes, '_start_task', forbidden_start)
    await schedule_routes._dispatch(occurrence, repo.database)
    with repo.database.connect() as db:
        row = db.execute('SELECT status,run_id FROM webui_schedule_runs WHERE id=?',
                         (occurrence[0],)).fetchone()
    assert row['status'] == 'started' and row['run_id'] == generation.run_id
