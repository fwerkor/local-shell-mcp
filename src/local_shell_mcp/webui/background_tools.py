"""Original LibreChat background.ts ordinary-tool capability and one-shot host.

Runs exactly the original LSM native call_tool entrypoint under the original
validated grant. No new model executor or RPC implementation. Like upstream
process-local ordinary tools, an interrupted native call has an *uncertain*
result after restart: never blindly re-execute possible irreversible effects.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
import time
from typing import Any

from .providers import ModelToolCall

log = logging.getLogger(__name__)
_TOOL_TASKS: dict[str, asyncio.Task] = {}
_LOCAL_TASK_IDENTITIES: set[str] = set()
_LEASE_OWNER = secrets.token_hex(16)
_LEASE_MS = 30_000
_HEARTBEAT_SECONDS = 5
_MAX_RESULT = 100_000
_EXCLUDED = frozenset({
    'subagent', 'check_background_task', 'ask_user_question',
    'session_manage', 'plan_manage', 'mcp_manage', 'remote_manage',
    'web_search', 'file_search', 'image_gen_oai', 'image_edit_oai',
    'file_write', 'file_upload', 'file_download',
    'mcp_tool_search', 'mcp_tool_inspect', 'mcp_tool_call',
})
_DEFAULT_CODE_NAMES = frozenset({'bash_tool', 'execute_code'})


def _now() -> int:
    return int(time.time() * 1000)


def eligible(name: str) -> bool:
    return name not in _EXCLUDED and not name.startswith(('lc_transfer_to_', 'image_gen', 'image_edit'))


def inject_tools(definitions: list[dict], config: dict | None,
                 *, native_names: frozenset[str] = frozenset()) -> tuple[list[dict], frozenset[str]]:
    """Source applyBackgroundToolCalls: opt-in by effective tool_options.

    Does not modify the shared original tool definitions and will not hijack an
    existing function-owned `run_in_background` property or non-object schema.
    """
    policy = (config or {}).get('tool_options') or {}
    capability = (config or {}).get('run_in_background') is True
    updated: list[dict] = []
    selected: set[str] = set()
    for definition in definitions:
        function = definition.get('function') or {}
        name = function.get('name')
        options = policy.get(name) if isinstance(policy, dict) else None
        explicit = options.get('run_in_background') if isinstance(options, dict) else None
        enabled = explicit if type(explicit) is bool else (capability or name in _DEFAULT_CODE_NAMES)
        params = function.get('parameters') or {}
        properties = params.get('properties') or {}
        if (enabled and isinstance(name, str) and name in native_names and eligible(name)
                and isinstance(params, dict) and params.get('type', 'object') == 'object'
                and isinstance(properties, dict) and 'run_in_background' not in properties):
            updated.append({**definition, 'function': {**function, 'parameters': {
                **params, 'type': 'object', 'properties': {**properties, 'run_in_background': {
                    'type': 'boolean', 'description':
                    'Run this tool in the background and return a background_task_id; '
                    'check_background_task can retrieve its result later.',
                }},
            }}})
            selected.add(name)
        else:
            updated.append(definition)
    return updated, frozenset(selected)


def _payload(row: Any, *, result: str | None = None) -> dict:
    return {'background_task_id': row['id'], 'tool': row['tool_name'],
            'status': row['status'], 'started_at': row['created_at'],
            'elapsed_ms': max(0, row['updated_at'] - row['created_at']),
            **({'result_available': True} if row['status'] == 'completed' and not row['claimed'] else {}),
            **({'result_claimed': True} if row['claimed'] else {}),
            **({'result': result} if result is not None else {}),
            **({'error': row['error_type']} if row['error_type'] else {})}


async def start_tool_task(database: Any, owner: str, conversation_id: str,
                          authorization_conversation_id: str, run_id: str,
                          call: ModelToolCall, *, scopes: frozenset[str],
                          grant_expires: int | None, dispatch,
                          event_delivery_lease: tuple[str, str] | None = None) -> str:
    if not eligible(call.name) or not call.call_id or not isinstance(call.arguments, dict):
        raise ValueError('Ordinary background tool is not eligible')
    fingerprint = hashlib.sha256(json.dumps([call.name, call.arguments], ensure_ascii=False,
                                           sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = 'tooltask_' + hashlib.sha256(json.dumps(
        [owner, conversation_id, run_id, call.call_id], separators=(',', ':')).encode()).hexdigest()
    now = _now()
    first = False
    # The initial restart sweep may predate expiry of old process-local
    # leases. Reconcile them again before computing running quotas.
    recover_background_tools(database)
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        parent = db.execute('SELECT r.id FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                            'WHERE r.id=? AND r.conversation_id=? AND c.owner=? AND r.status="running"',
                            (run_id, conversation_id, owner)).fetchone()
        row = db.execute('SELECT * FROM agent_background_tools WHERE id=?', (identity,)).fetchone()
        if row is None and parent is None:
            raise PermissionError('Background tool requires an active owned parent run')
        if row is not None:
            if (row['argument_hash'] != fingerprint or row['tool_name'] != call.name or
                    row['authorization_conversation_id'] != authorization_conversation_id):
                raise ValueError('Background tool-call ID was used for different arguments')
        else:
            running_user = db.execute('SELECT count(*) FROM agent_background_tools '
                                      'WHERE owner=? AND status="running"', (owner,)).fetchone()[0]
            running_thread = db.execute('SELECT count(*) FROM agent_background_tools '
                                        'WHERE owner=? AND authorization_conversation_id=? '
                                        'AND status="running"',
                                        (owner, authorization_conversation_id)).fetchone()[0]
            if running_user >= 40:
                raise PermissionError('User background task limit of 40 exceeded')
            if running_thread >= 10:
                raise PermissionError('Conversation background task limit of 10 exceeded')
            allowed = db.execute('SELECT 1 FROM conversations WHERE id=? AND owner=?',
                                 (authorization_conversation_id, owner)).fetchone()
            if not allowed:
                raise PermissionError('Background tool authorization scope is invalid')
            if event_delivery_lease is not None:
                from .detached_event_actions import reserve

                reserve(db, owner=owner, run_id=run_id, lease=event_delivery_lease,
                        task_id=identity, tool_name=call.name,
                        tool_call_id=call.call_id, arguments=call.arguments,
                        argument_hash=fingerprint, at=now)
            db.execute('INSERT INTO agent_background_tools('
                       'id,owner,conversation_id,authorization_conversation_id,parent_run_id,'
                       'parent_tool_call_id,tool_name,argument_hash,status,lease_owner,lease_until,'
                       'created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (identity, owner, conversation_id, authorization_conversation_id, run_id,
                        call.call_id, call.name, fingerprint, 'running', _LEASE_OWNER,
                        now + _LEASE_MS, now, now))
            first = True
        row = db.execute('SELECT * FROM agent_background_tools WHERE id=?', (identity,)).fetchone()
    if first:
        # Retain identity after the coroutine exits on revoked lease. Polling
        # must distinguish a lost *local* lease from an orphan of old process.
        if len(_LOCAL_TASK_IDENTITIES) > 10000:
            _LOCAL_TASK_IDENTITIES.clear()
        _LOCAL_TASK_IDENTITIES.add(identity)
        async def execute():
            parent = asyncio.current_task()

            async def heartbeat():
                while True:
                    await asyncio.sleep(_HEARTBEAT_SECONDS)
                    with database.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        updated = db.execute('UPDATE agent_background_tools SET lease_until=?,updated_at=? '
                                             'WHERE id=? AND status="running" AND lease_owner=? '
                                             'AND cancel_requested=0 AND lease_until>?',
                                             (_now() + _LEASE_MS, _now(), identity, _LEASE_OWNER, _now()))
                        if updated.rowcount != 1:
                            parent.cancel()
                            return
                        if event_delivery_lease is not None:
                            from .detached_event_actions import renew_source_lease

                            if not renew_source_lease(db, owner, run_id, event_delivery_lease, _now()):
                                parent.cancel()
                                return
                            db.execute('UPDATE agent_event_detached_actions SET recovery_after=? '
                                       'WHERE task_id=? AND owner=? AND status="running"',
                                       (_now() + 30 * 60_000, identity, owner))
            lease_task = asyncio.create_task(heartbeat(), name='background-tool-lease')
            try:
                if event_delivery_lease is not None:
                    from .detached_event_actions import mark_running, renew_source_lease

                    with database.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        if not renew_source_lease(db, owner, run_id, event_delivery_lease, _now()):
                            raise PermissionError('Detached event source was revoked')
                        mark_running(db, identity, owner, _now())
                # Run the registered LSM audited tool path, not a new worker/RPC.
                if grant_expires is not None and grant_expires <= time.time():
                    raise PermissionError('Original authorization grant expired')
                result = await dispatch(call, scopes, grant_expires,
                                        authorization_conversation_id)
                value = str(result)[:_MAX_RESULT]
                with contextlib.suppress(ValueError, TypeError):
                    native = json.loads(value)
                    if isinstance(native, dict) and native.get('ok') is False:
                        raise RuntimeError('Native tool returned an unsuccessful result')
                status = 'completed'
                error = None
            except asyncio.CancelledError:
                # An operator's durable cancel request is explicit; process
                # shutdown or an expired/competing actor has UNKNOWN effects.
                status, error, value = 'uncertain', 'INTERRUPTED_UNKNOWN_RESULT', None
                raise
            except Exception as exc:
                status, error, value = 'error', type(exc).__name__, None
            finally:
                lease_task.cancel()
                await asyncio.gather(lease_task, return_exceptions=True)
                # If shutdown interrupts an ongoing native action, its effects
                # may be ambiguous. Never retry it without explicit operator action.
                with database.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    finish_status = locals().get('status', 'uncertain')
                    finish_error = locals().get('error')
                    previous = db.execute('SELECT cancel_requested,lease_until FROM agent_background_tools '
                                          'WHERE id=? AND status="running" AND lease_owner=?',
                                          (identity, _LEASE_OWNER)).fetchone()
                    if previous:
                        if previous['cancel_requested']:
                            finish_status, finish_error = 'cancelled', None
                        elif previous['lease_until'] is None or previous['lease_until'] <= _now():
                            finish_status, finish_error = 'uncertain', 'LEASE_EXPIRED_UNKNOWN_RESULT'
                        if finish_status == 'completed' and previous['cancel_requested']:
                            finish_status, finish_error = 'cancelled', None
                        db.execute('UPDATE agent_background_tools SET status=?,result=?,error_type=?,updated_at=?,lease_until=NULL '
                                   'WHERE id=? AND status="running" AND lease_owner=?',
                                   (finish_status, locals().get('value') if finish_status == 'completed' else None,
                                    finish_error, _now(), identity, _LEASE_OWNER))
                        if event_delivery_lease is not None:
                            from .detached_event_actions import settle

                            settle(db, identity, owner, finish_status, locals().get('value'),
                                   finish_error, _now())
                _TOOL_TASKS.pop(identity, None)
        _TOOL_TASKS[identity] = asyncio.create_task(execute(), name='background-tool-'+identity[9:21])
    return json.dumps(_payload(row), ensure_ascii=False)


def check_tool_task(database: Any, owner: str, authorization_conversation_id: str,
                    identity: str | None, action: str = 'poll') -> dict | list[dict]:
    if identity is not None and (not isinstance(identity, str) or not identity.startswith('tooltask_')):
        return {'status': 'not_found'}
    recover_background_tools(database)
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if identity is None:
            rows = db.execute('SELECT * FROM agent_background_tools WHERE owner=? '
                              'AND authorization_conversation_id=? ORDER BY created_at DESC LIMIT 100',
                              (owner, authorization_conversation_id)).fetchall()
            return [_payload(row) for row in rows]
        row = db.execute('SELECT * FROM agent_background_tools WHERE id=? AND owner=? '
                         'AND authorization_conversation_id=?',
                         (identity, owner, authorization_conversation_id)).fetchone()
        if row is None:
            return {'status': 'not_found', 'background_task_id': identity}
        if row['status'] == 'running' and row['lease_until'] is not None and row['lease_until'] <= _now():
            db.execute('UPDATE agent_background_tools SET status="uncertain",'
                       'error_type="LEASE_EXPIRED_UNKNOWN_RESULT",updated_at=? '
                       'WHERE id=? AND status="running" AND lease_until<=?',
                       (_now(), identity, _now()))
            row = db.execute('SELECT * FROM agent_background_tools WHERE id=?', (identity,)).fetchone()
        if action == 'cancel':
            if row['status'] == 'running':
                db.execute('UPDATE agent_background_tools SET cancel_requested=1,updated_at=? WHERE id=?',
                           (_now(), identity))
                active = _TOOL_TASKS.get(identity)
                if active:
                    active.cancel()
                return {**_payload(row), 'status': 'cancellation_requested'}
            return {**_payload(row), 'status': 'not_running'}
        if action != 'poll':
            return {**_payload(row), 'status': 'invalid_control'}
        if row['status'] == 'completed' and not row['claimed']:
            db.execute('UPDATE agent_background_tools SET claimed=1,updated_at=? WHERE id=? AND claimed=0',
                       (_now(), identity))
            return {**_payload(row, result=row['result'] or ''),
                    'result_claimed': True, 'result_available': False}
        return _payload(row)


def recover_background_tools(database: Any) -> int:
    """On startup, mark unknown process-local side effects uncertain, never replay."""
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        expired = db.execute('SELECT id,lease_owner FROM agent_background_tools '
                             'WHERE status="running" AND (lease_until IS NULL OR lease_until<=?)',
                             (_now(),)).fetchall()
        changed = 0
        for row in expired:
            # An active local task lost its lease to another controller;
            # abandoned tasks from a previous process have no local executor.
            error = ('LEASE_EXPIRED_UNKNOWN_RESULT'
                     if row['id'] in _LOCAL_TASK_IDENTITIES or row['lease_owner'] == _LEASE_OWNER
                     else 'PROCESS_RESTART_UNKNOWN_RESULT')
            changed += db.execute('UPDATE agent_background_tools SET status="uncertain",'
                                  'error_type=?,updated_at=? WHERE id=? AND status="running"',
                                  (error, _now(), row['id'])).rowcount
        return changed


async def shutdown_background_tools() -> None:
    tasks = list(_TOOL_TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _TOOL_TASKS.clear()
