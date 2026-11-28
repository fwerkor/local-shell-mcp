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


def _without(row: dict, *keys: str) -> dict:
    return {key: value for key, value in row.items() if key not in keys}


def _map_rows(rows: list, project) -> list:
    return [project(row) if isinstance(row, dict) else row for row in rows]


def _drop_equal(row: dict, key: str, value: Any) -> dict:
    if key in row and type(row[key]) is type(value) and row[key] == value:
        return _without(row, key)
    return row


def _compact_file_read(row: dict) -> dict:
    if 'path' not in row or 'content' not in row or row.get('binary') is not False:
        return row
    row = _without(row, 'sha256')
    row = _omit_defaults(row, {'binary': False, 'truncated': False, 'truncated_bytes': 0})
    if isinstance(row.get('bytes'), int) and row.get('truncated') is not True:
        row = _drop_equal(row, 'bytes_read', row['bytes'])
    return row


def _compact_plan(row: dict) -> dict:
    return _omit_defaults(
        _without(row, 'revision', 'continuation_claim_id', 'continuation_reserved',
                 'in_flight_calls', 'execution_lease_s', 'last_agent_activity'),
        {'note': None, 'last_continuation_at': None, 'continuation_retry_after': None},
    )


def _compact_mcp_server(row: dict) -> dict:
    if row.get('transport') == 'stdio':
        row = _omit_defaults(row, {'url': None, 'header_keys': []})
    elif row.get('transport') in {'streamable_http', 'sse'}:
        row = _omit_defaults(row, {'command': None, 'args': [], 'cwd': None, 'env_keys': []})
    return row


def _compact_extra(name: str, arguments: dict, data: Any) -> Any:
    # The public verbose flag restores diagnostic metadata. Never recursively
    # strip arbitrary payloads, even if their keys match our native fields.
    if arguments.get('verbose', False):
        return data
    if name == 'file_list' and isinstance(data, list):
        return _map_rows(data, lambda row: _omit_defaults(_without(row, 'modified'), {'size': None})
                         if 'path' in row and 'type' in row else row)
    if not isinstance(data, dict):
        return data
    if name == 'file_read':
        if isinstance(data.get('files'), list):
            return {**data, 'files': _map_rows(data['files'], _compact_file_read)}
        return _compact_file_read(data)
    if name == 'file_grep' and isinstance(data.get('matches'), list) and data.get('ok') is True:
        data = _drop_equal(data, 'count', len(data['matches']))
        return _omit_defaults(data, {'stderr': '', 'truncated': False, 'ok': True})
    if name == 'file_tree' and data.get('exists') is True and data.get('is_directory') is True:
        data = _omit_defaults(data, {'exists': True, 'is_directory': True, 'truncated': False})
        if isinstance(data.get('entries'), list):
            data = _drop_equal(data, 'count', len(data['entries']))
        return data
    if name == 'job_list' and isinstance(data.get('jobs'), list):
        return {**data, 'jobs': _map_rows(data['jobs'], lambda row: _omit_defaults(
            _without(row, 'backend', 'session_id'), {'attempts': 1, 'exit_code': None}))}
    if name == 'job_tail' and isinstance(data.get('job'), dict):
        job = _without(data['job'], 'output_bytes')
        job = _drop_equal(job, 'job_id', arguments.get('job_id'))
        return {**data, 'job': _omit_defaults(job, {'exit_code': None})}
    if name == 'shell_list' and isinstance(data.get('sessions'), list):
        return {**data, 'sessions': _map_rows(data['sessions'], lambda row:
                    _omit_defaults(_without(row, 'backend'), {'attached': '0'}))}
    if name == 'shell_read' and 'output' in data:
        return _drop_equal(data, 'session_id', arguments.get('session_id'))
    if name == 'shell_stop' and data.get('killed') is True:
        return _omit_defaults(data, {'stderr': ''})
    if name in {'session_manage', 'plan_manage'}:
        if isinstance(data.get('plan'), dict):
            data = {**data, 'plan': _compact_plan(data['plan'])}
        if name == 'session_manage':
            progress = data.get('progress')
            if isinstance(progress, dict):
                progress = _omit_defaults(progress, {'summary': None, 'findings': [],
                    'next': None, 'blockers': [], 'updated_at': None})
                data = {**data, 'progress': progress} if progress else _without(data, 'progress')
        return data
    if name in {'skill_list', 'skill_load'}:
        data = _omit_defaults(_without(data, 'skills_dir', 'skills_dirs'), {'warnings': []})
        if name == 'skill_list' and isinstance(data.get('skills'), list):
            return {**data, 'skills': _map_rows(data['skills'], lambda row:
                _without(row, 'entry_path', 'source_path', 'related_files'))}
        return data
    if name == 'mcp_tool_search' and isinstance(data.get('tools'), list):
        def project(row: dict) -> dict:
            server, tool = row.get('server'), row.get('tool')
            if isinstance(server, str) and isinstance(tool, str) and row.get('name') == f'{server}:{tool}':
                row = _without(row, 'server', 'tool')
            return _omit_defaults(row, {'title': None, 'description': None})
        data = {**data, 'tools': _map_rows(data['tools'], project)}
        data = _drop_equal(data, 'count', len(data['tools']))
        return _omit_defaults(data, {'unrefreshed_servers': []})
    if name == 'mcp_manage':
        if isinstance(data.get('servers'), list):
            data = {**data, 'servers': _map_rows(data['servers'], _compact_mcp_server)}
        if isinstance(data.get('server'), dict):
            data = {**data, 'server': _compact_mcp_server(data['server'])}
        return data
    if name in {'browser_snapshot', 'browser_act'}:
        if isinstance(data.get('pages'), list) and isinstance(data.get('page_id'), str):
            def project_page(row: dict) -> dict:
                if row.get('page_id') == data['page_id']:
                    for key in ('title', 'url'):
                        if key in data:
                            row = _drop_equal(row, key, data[key])
                return row
            data = {**data, 'pages': _map_rows(data['pages'], project_page)}
        if name == 'browser_snapshot':
            data = _omit_defaults(data, {'errors': [], 'network': [], 'text_truncated': False,
                                        'screenshot_path': None, 'text': None})
        return data
    if name == 'remote_list' and isinstance(data.get('machines'), list):
        def project_machine(row: dict) -> dict:
            info = row.get('info')
            if not isinstance(info, dict):
                return row
            info = _without(info, 'poll_protocol_version')
            if 'workdir' in row:
                info = _drop_equal(info, 'workdir', row['workdir'])
            shell = info.get('persistent_shell')
            if isinstance(shell, dict):
                info = {**info, 'persistent_shell': _without(shell, 'socket_name', 'tmux_helper_version')}
            return {**row, 'info': info}
        return {**data, 'machines': _map_rows(data['machines'], project_machine)}
    if name == 'environment_get':
        settings = data.get('settings')
        if isinstance(settings, dict):
            # Full settings include deployment, OAuth, UI and other controller
            # internals. Keep limits and execution policy visible by default.
            keys = {'workspace_root', 'allow_full_container', 'disable_local',
                    'auth_mode', 'remote_enabled', 'command_denylist', 'path_denylist',
                    'python_bin', 'git_bin', 'rg_bin'}
            data = {**data, 'settings': {key: value for key, value in settings.items()
                       if key in keys or key.startswith('max_') or key == 'default_timeout_s'}}
        probe = data.get('probe')
        if isinstance(probe, dict) and probe.get('ok') is True and probe.get('exit_code') == 0:
            data = {**data, 'probe': _omit_defaults(_without(probe, 'command', 'ok'),
                       {'stderr': '', 'truncated': False, 'timed_out': False})}
        return data
    return data


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
    elif name == 'job_list' and not verbose and isinstance(data, dict) and isinstance(data.get('jobs'), list):
        defaults = {'command_truncated': False, 'log_truncated': False, 'name': None,
                    'completed_at': None, 'error': None}
        data = {**data, 'jobs': [_omit_defaults(row, defaults) if isinstance(row, dict)
                                 else row for row in data['jobs']]}
    elif (name == 'remote_list'
          and isinstance(data, dict) and isinstance(data.get('machines'), list)):
        rows = []
        for row in data['machines']:
            if isinstance(row, dict):
                row = {key: value for key, value in row.items() if key != 'capabilities'}
                info = row.get('info')
                if isinstance(info, dict):
                    row['info'] = {key: value for key, value in info.items()
                                   if key not in {'sample_generation', 'sample_sequence'}}
                if not verbose:
                    row = {key: value for key, value in row.items()
                           if key not in {'last_seen', 'offline_after_s', 'reset_generation'}}
                    if row.get('queue_depth') == 0:
                        row = _omit_defaults(row, {'interactive_queue_depth': 0, 'transfer_queue_depth': 0})
            rows.append(row)
        data = {**data, 'machines': rows}
    if 'data' in compact:
        compact['data'] = _compact_extra(name, arguments, data)
    return compact
