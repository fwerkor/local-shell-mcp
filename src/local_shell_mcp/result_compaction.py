"""Compact only known native result shapes at the public tool boundary.

Worker RPC, audit records, internal state and arbitrary third-party payloads
retain their original contracts. Missing optional flags have documented defaults.
"""
from __future__ import annotations

from typing import Any


def _omit_defaults(row: dict, defaults: dict) -> dict:
    return {key: value for key, value in row.items()
            if key not in defaults or type(value) is not type(defaults[key])
            or value != defaults[key]}


def compact_native_result(name: str, arguments: dict, result: Any) -> Any:
    # Error envelopes, rich media, nested MCP responses and unknown shapes are
    # intentionally not rewritten. Never recurse into arbitrary user data.
    if not isinstance(result, dict) or result.get('ok') is not True:
        return result
    if name == 'mcp_tool_call' or not set(result) <= {'ok', 'message', 'data'}:
        return result
    compact = _omit_defaults(result, {'message': ''})
    data = compact.get('data')
    verbose = arguments.get('verbose', False)
    if name in {'run_shell', 'run_python'} and isinstance(data, dict) and 'exit_code' in data:
        data = _omit_defaults(data, {'timed_out': False, 'truncated': False,
                                     'stderr': '', 'persisted': False})
        if data.get('ok') is True and data.get('exit_code') == 0:
            data.pop('ok')
        if name == 'run_shell' and data.get('command') == arguments.get('command'):
            data.pop('command', None)
        if data.get('cwd') == arguments.get('cwd', '.'):
            data.pop('cwd', None)
    elif name in {'job_start', 'shell_start'} and isinstance(data, dict):
        data = dict(data)
        if 'command' in arguments and data.get('command') == arguments['command']:
            data.pop('command', None)
        if data.get('cwd') == arguments.get('cwd', '.'):
            data.pop('cwd', None)
        if name == 'job_start':
            data = _omit_defaults(data, {'error': None, 'progress': None, 'result': None,
                                         'completed_at': None, 'log_truncated': False})
    elif name == 'session_manage' and isinstance(data, dict) and not verbose:
        data = dict(data)
        history = data.get('recent_activity')
        if isinstance(history, list):
            # Human/system events can contain new information. Tool activity is
            # already in the conversation/audit; full history is opt-in.
            retained = [event for event in history if not isinstance(event, dict)
                        or event.get('actor') != 'agent'
                        or event.get('type') not in {'tool.started', 'tool.completed', 'session.reported'}]
            if retained:
                data['recent_activity'] = retained
            else:
                data.pop('recent_activity')
            if len(history) > len(retained):
                data['omitted_activity_count'] = len(history) - len(retained)
        data = _omit_defaults(data, {'plan': None})
    elif name == 'job_tail' and isinstance(data, dict) and not verbose:
        job = data.get('job')
        if isinstance(job, dict) and 'job_id' in job and 'status' in job:
            # Metadata available from job_get; retain unknown future fields,
            # progress, results, failures, exit codes and truncation indicators.
            detail = {'command', 'cwd', 'backend', 'session_id', 'created_at',
                      'updated_at', 'last_started_at', 'completed_at'}
            job = {key: value for key, value in job.items() if key not in detail}
            job = _omit_defaults(job, {'name': None, 'error': None, 'progress': None,
                                       'result': None, 'log_truncated': False, 'attempts': 1})
            data = {**data, 'job': job}
            status, exit_code = job.get('status'), job.get('exit_code')
            if data.get('message') in {f'job completed with exit code {exit_code}', f'job is {status}'}:
                data.pop('message', None)
    elif name == 'job_list' and isinstance(data, dict) and isinstance(data.get('jobs'), list):
        defaults = {'command_truncated': False, 'log_truncated': False, 'name': None,
                    'completed_at': None, 'error': None}
        data = {**data, 'jobs': [_omit_defaults(row, defaults) if isinstance(row, dict)
                                 else row for row in data['jobs']]}
    elif (name == 'remote_manage' and str(arguments.get('action', '')).strip().lower() == 'list'
          and not verbose and isinstance(data, dict) and isinstance(data.get('machines'), list)):
        rows = []
        for row in data['machines']:
            if isinstance(row, dict):
                row = {key: value for key, value in row.items()
                       if key not in {'last_seen', 'offline_after_s', 'reset_generation'}}
                if row.get('queue_depth') == 0:
                    row = _omit_defaults(row, {'interactive_queue_depth': 0, 'transfer_queue_depth': 0})
            rows.append(row)
        data = {**data, 'machines': rows}
    if 'data' in compact:
        compact['data'] = data
    return compact
