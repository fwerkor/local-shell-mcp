"""Durable Scheduled Chats with Controller-owned, idempotent generation startup.

The worker claims each occurrence under SQLite BEGIN IMMEDIATE, so controller
restarts and concurrent server processes cannot double-fire one occurrence.
Unattended runs do not inherit a browser's transient OAuth tool grant.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .agents import AgentRepository
from .auth import _same_origin
from .routes import _body, _owner, _repo
from .storage import _json, _now, _stamp

log = logging.getLogger(__name__)
_WORKER: asyncio.Task | None = None
_ACTIVE: set[asyncio.Task] = set()
_LIMITS = {'maxPerUser': 25, 'minIntervalMinutes': 5, 'requireProject': False}
_DAY_MS = 86_400_000


def _iso(ms: int | None):
    return _stamp(ms / 1000) if ms is not None else None


def _zone(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise HTTPException(400, detail='Invalid timezone')
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(400, detail='Unknown timezone') from exc


def _cron_field(source, lower, upper, *, weekday=False):
    items = set()
    for section in source.split(','):
        parts = section.split('/')
        if len(parts) > 2 or not parts[0]:
            raise ValueError('Invalid cron segment')
        if len(parts) == 2 and not parts[1].isascii():
            raise ValueError('Invalid cron step')
        if len(parts) == 2 and not parts[1].isdigit():
            raise ValueError('Invalid cron step')
        step = int(parts[1]) if len(parts) == 2 else 1
        if step <= 0 or step > upper:
            raise ValueError('Invalid cron step')
        expression = parts[0]
        if expression == '*':
            start, end = lower, upper
        elif '-' in expression:
            start, end = (int(v) for v in expression.split('-', 1))
        else:
            start = int(expression)
            end = upper if len(parts) == 2 else start
        if start < lower or end > upper or end < start:
            raise ValueError('Invalid cron range')
        for value in range(start, end + 1, step):
            items.add(0 if weekday and value == 7 else value)
    return items


def _parse_cadence(value):
    if not isinstance(value, dict):
        raise HTTPException(400, detail='Invalid schedule cadence')
    frequency = value.get('frequency')
    if frequency == 'cron':
        expression = value.get('expression')
        if not isinstance(expression, str) or len(expression) > 256:
            raise HTTPException(400, detail='Invalid cron expression')
        fields = expression.split()
        if len(fields) != 5:
            raise HTTPException(400, detail='Cron must have five fields')
        try:
            minute = _cron_field(fields[0], 0, 59)
            hour = _cron_field(fields[1], 0, 23)
            dom = _cron_field(fields[2], 1, 31)
            month = _cron_field(fields[3], 1, 12)
            dow = _cron_field(fields[4], 0, 7, weekday=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, detail='Invalid cron expression') from exc
        return frequency, (minute, hour, dom, month, dow,
                           fields[2] == '*', fields[4] == '*')
    if frequency not in {'hourly', 'daily', 'weekdays', 'weekly'}:
        raise HTTPException(400, detail='Unsupported schedule frequency')
    hour, minute = value.get('hour'), value.get('minute')
    if (type(hour) is not int or not 0 <= hour <= 23 or
            type(minute) is not int or not 0 <= minute <= 59):
        raise HTTPException(400, detail='Invalid schedule time')
    days = value.get('daysOfWeek')
    if days is not None and (not isinstance(days, list) or not days or
                             any(type(day) is not int or day not in range(7) for day in days)):
        raise HTTPException(400, detail='Invalid weekdays')
    return frequency, (hour, minute, set(days or []))


def _matches(local, parsed):
    frequency, settings = parsed
    dow = (local.weekday() + 1) % 7
    if frequency == 'hourly':
        return local.minute == settings[1]
    if frequency == 'daily':
        return (local.hour, local.minute) == settings[:2]
    if frequency == 'weekdays':
        return dow in {1, 2, 3, 4, 5} and (local.hour, local.minute) == settings[:2]
    if frequency == 'weekly':
        return dow in (settings[2] or {1}) and (local.hour, local.minute) == settings[:2]
    minutes, hours, dom, months, weekdays, dom_any, dow_any = settings
    day_match = local.day in dom
    weekday_match = dow in weekdays
    if dom_any:
        day_ok = weekday_match
    elif dow_any:
        day_ok = day_match
    else:
        day_ok = day_match or weekday_match
    return local.minute in minutes and local.hour in hours and local.month in months and day_ok


def next_run(cadence, timezone, *, after_ms, min_interval_minutes=5):
    """UTC minute scan avoids nonexistent DST times and disambiguates repeated times."""
    parsed = _parse_cadence(cadence)
    zone = _zone(timezone)
    initial = (after_ms // 60_000 + 1) * 60_000
    earliest = after_ms + min_interval_minutes * 60_000
    for timestamp in range(initial, initial + 370 * _DAY_MS, 60_000):
        if timestamp < earliest:
            continue
        local = datetime.fromtimestamp(timestamp / 1000, tz=UTC).astimezone(zone)
        if _matches(local, parsed):
            return timestamp
    raise HTTPException(400, detail='Schedule has no occurrence within one year')


def _validate_cadence_interval(cadence):
    """Reject cron expressions with occurrences closer than the 5-minute limit.

    This validates the cadence itself; next_run can then advance from a due
    time without padding each occurrence by the scheduler's polling latency.
    """
    parsed = _parse_cadence(cadence)
    if parsed[0] != 'cron':
        return
    minutes, hours, *_ = parsed[1]
    times = sorted(hour * 60 + minute for hour in hours for minute in minutes)
    minimum = _LIMITS['minIntervalMinutes']
    if any(right - left < minimum for left, right in zip(times, times[1:], strict=False)):
        raise HTTPException(400, detail='Schedule interval must be at least five minutes')
    if 1440 + times[0] - times[-1] >= minimum:
        return
    # Inter-day gaps matter only when the cron day predicate matches both
    # adjacent dates. A Monday-only 23:59/00:00 cadence is not too frequent.
    day = datetime.now(UTC).replace(hour=min(hours),
                                   minute=min(minutes), second=0, microsecond=0)
    for offset in range(370):
        current = day + timedelta(days=offset)
        if _matches(current, parsed) and _matches(current + timedelta(days=1), parsed):
            raise HTTPException(400, detail='Schedule interval must be at least five minutes')


def _validate(owner, repo, data, *, partial=False):
    required = {'name', 'prompt', 'agent_id', 'cadence', 'timezone', 'clientRequestId'}
    if not partial and not required.issubset(data):
        raise HTTPException(400, detail='Missing schedule fields')
    for field, limit in [('name', 256), ('prompt', 32000)]:
        if field in data and (not isinstance(data[field], str) or
                              not 1 <= len(data[field].strip()) <= limit):
            raise HTTPException(400, detail=f'Invalid {field}')
    if 'agent_id' in data:
        agent = data['agent_id']
        if not isinstance(agent, str) or not agent or AgentRepository(repo.database).get(owner, agent) is None:
            raise HTTPException(404, detail='Schedule Agent not found')
    if 'clientRequestId' in data and (not isinstance(data['clientRequestId'], str) or
                                      not 1 <= len(data['clientRequestId']) <= 128):
        raise HTTPException(400, detail='Invalid schedule request id')
    if 'enabled' in data and type(data['enabled']) is not bool:
        raise HTTPException(400, detail='enabled must be a boolean')
    if 'target' in data and data['target'] != 'new':
        raise HTTPException(400, detail='Only new-chat schedules are supported')
    if 'file_ids' in data:
        files = data['file_ids']
        if not isinstance(files, list) or len(files) > 10 or any(not isinstance(f, str) for f in files):
            raise HTTPException(400, detail='Invalid files')
    if ('chatProjectId' in data and data['chatProjectId'] is not None
            and (not isinstance(data['chatProjectId'], str) or not repo.project(owner, data['chatProjectId']))):
        raise HTTPException(404, detail='Schedule project not found')
    if 'cadence' in data:
        _validate_cadence_interval(data['cadence'])
    if 'timezone' in data:
        _zone(data['timezone'])


def _present(row, database):
    config = json.loads(row['config'])
    with database.connect() as db:
        active = db.execute('SELECT conversation_id FROM webui_schedule_runs WHERE schedule_id=? '
                            "AND status='started' AND conversation_id IS NOT NULL",
                            (row['id'],)).fetchall()
    return {
        **config, 'id': row['id'], 'user': row['owner'],
        'enabled': bool(row['enabled']),
        'configRevision': row['revision'],
        'runCount': row['run_count'], 'failureCount': row['failure_count'],
        'lastRun': json.loads(row['last_run']) if row['last_run'] else None,
        'nextRunAt': _iso(row['next_run']) if row['enabled'] and row['next_run'] else None,
        'inFlight': [{'conversationId': record['conversation_id']} for record in active],
        'createdAt': _stamp(row['created_at'] / 1_000_000),
        'updatedAt': _stamp(row['updated_at'] / 1_000_000),
    }


def _find(owner, sid, database):
    with database.connect() as db:
        row = db.execute('SELECT * FROM webui_schedules WHERE owner=? AND id=?', (owner, sid)).fetchone()
    if row is None:
        raise HTTPException(404, detail='Schedule not found')
    return row


async def schedules(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    repo = _repo()
    if request.method == 'GET':
        with repo.database.connect() as db:
            rows = db.execute('SELECT * FROM webui_schedules WHERE owner=? ORDER BY created_at DESC',
                              (owner,)).fetchall()
        return JSONResponse({'schedules': [_present(row, repo.database) for row in rows],
                             'limits': _LIMITS})
    data = await _body(request)
    _validate(owner, repo, data)
    with repo.database.connect() as db:
        row = db.execute('SELECT * FROM webui_schedules WHERE owner=? AND request_id=?',
                         (owner, data['clientRequestId'])).fetchone()
        if row is not None:
            return JSONResponse(_present(row, repo.database))
        count = db.execute('SELECT COUNT(*) FROM webui_schedules WHERE owner=?', (owner,)).fetchone()[0]
    if count >= _LIMITS['maxPerUser']:
        raise HTTPException(400, detail='Schedule limit reached')
    config = {key: data[key] for key in
              ('name', 'prompt', 'agent_id', 'cadence', 'timezone', 'target', 'file_ids',
               'chatProjectId') if key in data}
    config.setdefault('target', 'new')
    now = int(time.time() * 1000)
    enabled = data.get('enabled', True)
    next_at = next_run(config['cadence'], config['timezone'], after_ms=now) if enabled else None
    sid = str(uuid.uuid4())
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        count = db.execute('SELECT COUNT(*) FROM webui_schedules WHERE owner=?', (owner,)).fetchone()[0]
        if count >= _LIMITS['maxPerUser']:
            raise HTTPException(400, detail='Schedule limit reached')
        db.execute('INSERT OR IGNORE INTO webui_schedules '
                   '(id,owner,request_id,config,enabled,next_run,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)',
                   (sid, owner, data['clientRequestId'], _json(config), int(enabled), next_at, _now(), _now()))
        row = db.execute('SELECT * FROM webui_schedules WHERE owner=? AND request_id=?',
                         (owner, data['clientRequestId'])).fetchone()
    return JSONResponse(_present(row, repo.database), status_code=201)


async def schedule(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    sid = request.path_params['id']
    repo = _repo()
    row = _find(owner, sid, repo.database)
    if request.method == 'GET':
        return JSONResponse(_present(row, repo.database))
    if request.method == 'DELETE':
        with repo.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM webui_schedules WHERE owner=? AND id=?', (owner, sid))
        return JSONResponse({'id': sid})
    payload = await _body(request)
    if 'expectedConfigRevision' in payload and (type(payload['expectedConfigRevision']) is not int or
                                                 payload['expectedConfigRevision'] != row['revision']):
        raise HTTPException(409, detail='Schedule configuration changed')
    _validate(owner, repo, payload, partial=True)
    config = json.loads(row['config'])
    for key in ('name', 'prompt', 'agent_id', 'cadence', 'timezone', 'target',
                'file_ids', 'chatProjectId'):
        if key in payload:
            config[key] = payload[key]
    _validate(owner, repo, config, partial=True)
    enabled = payload.get('enabled', bool(row['enabled']))
    timing_changed = (config['cadence'] != json.loads(row['config'])['cadence']
                      or config['timezone'] != json.loads(row['config'])['timezone'])
    if enabled and (timing_changed or not row['enabled']):
        next_at = next_run(config['cadence'], config['timezone'],
                           after_ms=int(time.time() * 1000))
    else:
        next_at = row['next_run'] if enabled else None
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        latest = db.execute('SELECT revision FROM webui_schedules WHERE id=? AND owner=?',
                            (sid, owner)).fetchone()
        if latest is None:
            raise HTTPException(404, detail='Schedule not found')
        if latest['revision'] != row['revision']:
            raise HTTPException(409, detail='Schedule configuration changed')
        db.execute('UPDATE webui_schedules SET config=?,enabled=?,next_run=?,'
                   'revision=revision+1,updated_at=? WHERE id=? AND owner=?',
                   (_json(config), int(enabled), next_at, _now(), sid, owner))
    return JSONResponse(_present(_find(owner, sid, repo.database), repo.database))


def _claim_due(database, *, owner=None, sid=None, manual=False):
    now = int(time.time() * 1000)
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        where = [] if manual else ['enabled=1']
        values = []
        if owner is not None:
            where.append('owner=?')
            values.append(owner)
        if sid is not None:
            where.append('id=?')
            values.append(sid)
        if not manual:
            where.append('next_run<=?')
            values.append(now)
        where.append("NOT EXISTS (SELECT 1 FROM webui_schedule_runs r "
                     "WHERE r.schedule_id=webui_schedules.id AND "
                     "r.status IN ('claimed','started'))")
        rows = db.execute('SELECT * FROM webui_schedules WHERE ' + ' AND '.join(where) +
                          ' ORDER BY next_run LIMIT ?', (*values, 25)).fetchall()
        claimed = []
        for row in rows:
            already = db.execute("SELECT 1 FROM webui_schedule_runs WHERE schedule_id=? AND "
                                 "status IN ('claimed','started')", (row['id'],)).fetchone()
            if already:
                continue
            config = json.loads(row['config'])
            due = now if manual else row['next_run']
            if manual:
                # Same-second retries cannot start a second expensive generation.
                previous = db.execute('SELECT 1 FROM webui_schedule_runs WHERE schedule_id=? '
                                      'AND created_at>?', (row['id'], _now() - 60_000_000)).fetchone()
                if previous:
                    continue
            # Anchor recurrence to the scheduled due minute, never to polling
            # latency. The creation/edit path already enforces the initial delay.
            next_at = next_run(config['cadence'], config['timezone'],
                               after_ms=due, min_interval_minutes=0) if not manual else row['next_run']
            run_id = str(uuid.uuid4())
            db.execute('INSERT INTO webui_schedule_runs(id,owner,schedule_id,due_at,status,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?,?)',
                       (run_id, row['owner'], row['id'], due, 'claimed', _now(), _now()))
            db.execute('UPDATE webui_schedules SET next_run=?,updated_at=? WHERE id=?',
                       (next_at, _now(), row['id']))
            claimed.append((run_id, row['owner'], row['id'], config, due))
        return claimed


def _recover_claimed(database, *, grace_seconds=90):
    """Reclaim a persisted occurrence left unfinished by a crashed dispatcher.

    The claim's id is stable across attempts and is the model generation's
    trusted idempotency key. A single SQLite write lease prevents two
    controllers recovering the same occurrence concurrently.
    """
    cutoff = _now() - grace_seconds * 1_000_000
    claimed = []
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute(
            "SELECT r.*,s.config,s.enabled FROM webui_schedule_runs r "
            "JOIN webui_schedules s ON s.id=r.schedule_id "
            "WHERE r.status='claimed' AND r.updated_at<? ORDER BY r.created_at LIMIT 25",
            (cutoff,),
        ).fetchall()
        for row in rows:
            if row['enabled'] == 0:
                db.execute("UPDATE webui_schedule_runs SET status='interrupted',updated_at=? WHERE id=?",
                           (_now(), row['id']))
                continue
            db.execute("UPDATE webui_schedule_runs SET updated_at=? WHERE id=? AND status='claimed'",
                       (_now(), row['id']))
            claimed.append((row['id'], row['owner'], row['schedule_id'],
                            json.loads(row['config']), row['due_at']))
    return claimed


def _settle(database, occurrence_id, status, *, conversation_id=None, run_id=None, error=None):
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM webui_schedule_runs WHERE id=?', (occurrence_id,)).fetchone()
        if row is None:
            return
        if row['status'] in {'success', 'error', 'interrupted'}:
            return
        db.execute('UPDATE webui_schedule_runs SET status=?,conversation_id=coalesce(?,conversation_id),'
                   'run_id=coalesce(?,run_id),updated_at=? WHERE id=?',
                   (status, conversation_id, run_id, _now(), occurrence_id))
        if status in {'success', 'error', 'interrupted'}:
            data = {'status': status, 'conversationId': conversation_id or row['conversation_id'],
                    'firedAt': _iso(row['due_at'])}
            if error:
                data['error'] = error
            db.execute('UPDATE webui_schedules SET run_count=run_count+1,'
                       'failure_count=failure_count+?,last_run=?,updated_at=? WHERE id=?',
                       (int(status != 'success'), _json(data), _now(), row['schedule_id']))


async def _dispatch(occurrence, database):
    occurrence_id, owner, sid, config, due = occurrence
    from .content_filters import (
        ContentFilterBlocked,
        validate_agent_instructions,
        validate_message_submission,
    )
    from .generation_routes import _generation_store, _start_task
    from .memory_protection import configured_filters
    from .providers import provider_config, selected_provider
    from .storage import WorkspaceRepository

    try:
        agent = AgentRepository(database).get(owner, config['agent_id'])
        if agent is None:
            raise ValueError('agent_deleted')
        repo = WorkspaceRepository(database)
        project_id = config.get('chatProjectId')
        if project_id and repo.project(owner, project_id) is None:
            raise ValueError('project_deleted')
        filters = configured_filters(repo, owner)
        validate_message_submission(config['prompt'], filters)
        validate_agent_instructions(agent.get('instructions') or '', filters)
        model = agent.get('model')
        provider = selected_provider({'endpoint': 'agents'}, agent)
        profile = provider_config(provider, model)
        # No user OAuth grant is persisted or implicitly upgraded into unattended
        # machine capabilities. Tool execution requires its own explicit grant.
        payload = {'text': config['prompt'], 'agent_id': config['agent_id'],
                   'endpoint': 'agents', 'provider': provider, 'model': model,
                   'clientRequestId': 'schedule:' + occurrence_id}
        if project_id:
            payload['projectId'] = project_id
        if config.get('file_ids'):
            payload['files'] = [{'file_id': file_id} for file_id in config['file_ids']]
        generation, fresh = _generation_store().begin(owner, payload, agent)
        _settle(database, occurrence_id, 'started', conversation_id=generation.conversation_id,
                run_id=generation.run_id)
        if fresh:
            started = await _start_task(owner, generation, profile, agent,
                                        native_file_tools=False, write_tools=False, mcp_enabled=False,
                                        granted_scopes=frozenset())
            if not started:
                _settle(database, occurrence_id, 'interrupted',
                        conversation_id=generation.conversation_id, error='generation_not_started')
    except Exception as exc:
        # Only stable user-facing validation errors may be echoed into the run
        # record. Unexpected provider exceptions can contain credential data.
        reason = str(exc)[:256] if isinstance(
            exc, (ValueError, KeyError, PermissionError, RuntimeError)) else type(exc).__name__
        if isinstance(exc, ContentFilterBlocked):
            reason = 'content_filter'
        _settle(database, occurrence_id, 'error', error=reason)
        log.warning('Scheduled chat could not start: %s', type(exc).__name__)


def _refresh(database):
    from .generations import GenerationStore
    store = GenerationStore(database)
    with database.connect() as db:
        rows = db.execute("SELECT * FROM webui_schedule_runs WHERE status='started'").fetchall()
    for row in rows:
        if not row['run_id']:
            continue
        result = store.get(row['owner'], row['run_id'])
        if result is None:
            _settle(database, row['id'], 'interrupted', error='Generation missing')
        elif result.status in {'complete', 'error', 'aborted', 'interrupted'}:
            status = 'success' if result.status == 'complete' else ('interrupted' if result.status in ('aborted', 'interrupted') else 'error')
            _settle(database, row['id'], status,
                    conversation_id=result.conversation_id, run_id=result.run_id)


async def _worker(database):
    while True:
        try:
            _refresh(database)
            for item in [*_recover_claimed(database), *_claim_due(database)]:
                task = asyncio.create_task(_dispatch(item, database), name='scheduled-chat-' + item[0])
                _ACTIVE.add(task)
                task.add_done_callback(_ACTIVE.discard)
        except Exception:
            log.exception('Scheduled chat worker iteration failed')
        await asyncio.sleep(20)


async def start_schedule_worker(database):
    global _WORKER
    if _WORKER is not None and not _WORKER.done():
        return
    _WORKER = asyncio.create_task(_worker(database), name='webui-scheduled-chats')


async def shutdown_schedule_worker():
    global _WORKER
    if _WORKER is not None:
        _WORKER.cancel()
        await asyncio.gather(_WORKER, return_exceptions=True)
        _WORKER = None
    if _ACTIVE:
        await asyncio.gather(*tuple(_ACTIVE), return_exceptions=True)


async def run_schedule(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    sid = request.path_params['id']
    database = _repo().database
    _find(owner, sid, database)
    claims = _claim_due(database, owner=owner, sid=sid, manual=True)
    if not claims:
        raise HTTPException(409, detail='Schedule already running or recently started')
    occurrence = claims[0]
    await _dispatch(occurrence, database)
    with database.connect() as db:
        result = db.execute('SELECT * FROM webui_schedule_runs WHERE id=?',
                            (occurrence[0],)).fetchone()
    if result is None or result['status'] != 'started':
        raise HTTPException(409, detail='Schedule could not start')
    return JSONResponse({'scheduleId': sid, 'conversationId': result['conversation_id'],
                         'status': 'started'})


def schedule_routes() -> list[Route]:
    return [
        Route('/api/schedules', schedules, methods=['GET', 'POST']),
        Route('/api/schedules/{id}/run', run_schedule, methods=['POST']),
        Route('/api/schedules/{id}', schedule, methods=['GET', 'PATCH', 'DELETE']),
    ]
