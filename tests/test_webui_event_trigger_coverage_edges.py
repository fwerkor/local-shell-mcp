"""Owner-fenced edge cases in source event admission and terminal evidence."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
from local_shell_mcp.webui.event_triggers import (
    _detached_proven,
    _parse_expected_action,
    _queue_detached_completion,
    assert_event_lease,
    assert_source_steer_claim,
    prepare_source_event,
)


@pytest.mark.parametrize(('value','mode','target','error'), [
    ('tool call', 'continue', {'bindingId': 'a', 'sourceKeyId': 's'}, 'object'),
    ({'toolName': 'write'}, 'fire', {}, 'bound-child'),
    ({'toolName': 'write'}, 'continue', {'bindingId': '', 'sourceKeyId': 's'}, 'bound-child'),
    ({'toolName': 'write', 'argumentSubset': []}, 'continue',
     {'bindingId': 'a', 'sourceKeyId': 's'}, 'argumentSubset'),
])
def test_expected_action_requires_valid_bound_child_proof(value, mode, target, error):
    with pytest.raises(ValueError, match=error):
        _parse_expected_action(value, mode, target)


def test_oversized_event_payload_is_never_admitted_even_when_input_is_short():
    event = {'mode': 'fire', 'target': {'agentId': 'owned-agent'},
             'event': {'id': 'payload-test', 'type': 'activity', 'occurredAt': 100,
                       'payload': {'content': 'X' * 1_100_000}}, 'input': 'safe'}
    with pytest.raises(ValueError, match='1048576 bytes'):
        prepare_source_event('alice', 'key-1', 'envelope-limit', event)


def test_invalid_remote_delivery_lease_cannot_authorize_actor_or_steer(tmp_path):
    database = SQLiteDatabase(tmp_path / 'state')
    with database.connect() as db, pytest.raises(RuntimeSafetyError, match='Steer delivery lease'):
        assert_source_steer_claim(db, 'alice', ('foreign-delivery', 'foreign-token'))
    with pytest.raises(RuntimeSafetyError, match='actor lease'):
        assert_event_lease(database, 'alice', 'run-missing', ('foreign-delivery', 'foreign-token'))


def test_forged_detached_completion_is_not_trusted_without_owner_evidence(tmp_path):
    database = SQLiteDatabase(tmp_path / 'state')
    envelope = {'principal': {'userId': 'alice'}, 'target': {},
                'event': {'type': 'librechat.event_actor.detached_completion',
                          'source': {'id': 'librechat-event-actor', 'type': 'internal'},
                          'payload': {'version': 1, 'invocationId': 'fake',
                                      'taskId': 'fake', 'generationCreatedAt': 0,
                                      'wakeGenerationCreatedAt': 0, 'idempotencyKey': 'a' * 64}}}
    with database.connect() as db:
        assert _detached_proven(db, envelope) is False
        assert _detached_proven(db, {**envelope, 'event': {'type': 'other'}}) is False
        with pytest.raises((KeyError, ValueError, PermissionError)):
            _queue_detached_completion(db, {'id': 'fake'}, envelope,
                                       {'evidence': json.dumps({'version': 0})}, 0)


def test_coalesced_source_event_rejects_oversized_batch_before_sqlite_admission(tmp_path):
    from local_shell_mcp.webui.event_triggers import enqueue_event

    db = SQLiteDatabase(tmp_path / 'data')
    event = {
        'mode': 'continue', 'target': {'agentId': 'agent-1',
            'conversationId': 'child-1', 'parentMessageId': 'parent-1', 'bindingId': 'binding-1'},
        'event': {'id': 'event-big', 'type': 'activity', 'occurredAt': 100,
                  'payload': {'text': 'x' * 530000}},
        'input': 'Process event', 'coalesce': {'key': 'source-batch'},
    }
    with pytest.raises(ValueError, match='Coalesced envelope exceeds'):
        enqueue_event(db, 'alice', 'source-1', 'big-coalesced', event)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0] == 0


def test_observed_action_requires_a_successful_completed_tool_not_only_a_receipt(tmp_path):
    from local_shell_mcp.webui.event_triggers import _observed_action
    from local_shell_mcp.webui.generations import GenerationStore

    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    run, _ = store.begin('alice', {'text': 'Execute a trusted tool'})
    calls = [
        {'event': 'on_message_delta', 'data': {'content': 'The file was written'}},
        {'event': 'on_run_step_completed', 'data': {'result': {'id': 'missing-tool'}}},
        {'event': 'on_run_step_completed', 'data': {'result': {'tool_call': {
            'name': 'file_write', 'args': {'path': 'a'}, 'output': 'Blocked: unauthorized'}}}},
        {'event': 'on_run_step_completed', 'data': {'result': {'tool_call': {
            'name': 'file_write', 'args': {'path': 'a'},
            'output': json.dumps({'background_task_id': 'bg-1'})}}}},
        {'event': 'on_run_step_completed', 'data': {'result': {'tool_call': {
            'name': 'file_write', 'args': {'path': 'a'}, 'output': json.dumps({'ok': False})}}}},
    ]
    for payload in calls:
        store.append('alice', run.run_id, payload)
    with db.connect() as conn:
        assert not _observed_action(conn, run.run_id, {'toolName': 'file_write'})
    store.append('alice', run.run_id, {'event': 'on_run_step_completed', 'data': {
        'result': {'tool_call': {'name': 'file_write', 'args': {'path': 'a'}, 'output': 'Saved'}}}})
    with db.connect() as conn:
        assert _observed_action(conn, run.run_id, {'toolName': 'file_write',
                                                   'argumentSubset': {'path': 'a'}})


def test_source_internal_wake_with_valid_projection_requires_reserved_host_evidence(tmp_path):
    from local_shell_mcp.webui.detached_event_actions import _EVENT_SOURCE, _EVENT_TYPE

    db = SQLiteDatabase(tmp_path / 'data')
    valid = {
        'principal': {'userId': 'alice'},
        'target': {'agentId': 'child'},
        'event': {'type': _EVENT_TYPE, 'source': {'id': _EVENT_SOURCE, 'type': 'internal'},
                  'payload': {'version': 1, 'invocationId': 'trigger_' + 'a' * 64,
                              'taskId': 'tooltask_' + 'b' * 64,
                              'idempotencyKey': 'c' * 64, 'generationCreatedAt': 100,
                              'wakeGenerationCreatedAt': 100}},
    }
    with db.connect() as conn:
        assert not _detached_proven(conn, valid)  # Valid shape is not authority.
        assert not _detached_proven(conn, {**valid, 'event': {
            **valid['event'], 'payload': {**valid['event']['payload'],
                                          'wakeGenerationCreatedAt': -1}}})


def test_expected_action_matches_mcp_suffix_and_rejects_malformed_argument_json():
    from local_shell_mcp.webui.event_triggers import matches_expected_action

    expected = {'toolName': 'file_write'}
    assert matches_expected_action({'toolName': 'file_write_mcp_github'}, expected)
    assert not matches_expected_action({'toolName': None}, expected)
    assert not matches_expected_action({'toolName': 'file_write_suffix'}, expected)
    assert not matches_expected_action({'toolName': 'file_write', 'arguments': '{bad-json'},
                                       {**expected, 'argumentSubset': {'path': 'main.py'}})
    assert matches_expected_action({'toolName': 'file_write',
                                    'arguments': '{"path":"main.py"}'},
                                   {**expected, 'argumentSubset': {'path': 'main.py'}})


def test_expected_action_uses_full_owned_execution_arguments_not_truncated_sse(tmp_path):
    from local_shell_mcp.webui.event_triggers import _observed_action
    from local_shell_mcp.webui.generations import GenerationStore

    database = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(database)
    run, _ = store.begin('local', {'text': 'Call Action with a large body'})
    full = {'project': 'support', 'payload': 'x' * 32_000}
    completion = {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'step-large', 'type': 'tool_call', 'tool_call': {
            'id': 'call-large', 'name': 'send_action',
            'args': {'_truncated': True, 'preview': 'too large to expose'},
            'output': '{"ok":true}',
        }}}}
    store.append('local', run.run_id, completion, full_arguments=full)
    with database.connect() as db:
        assert _observed_action(db, run.run_id, {
            'toolName': 'send_action', 'argumentSubset': {'project': 'support'}})
        assert not _observed_action(db, run.run_id, {
            'toolName': 'send_action', 'argumentSubset': {'project': 'unrelated'}})
        persisted = json.loads(db.execute('SELECT state FROM runs WHERE id=?',
                                          (run.run_id,)).fetchone()['state'])
    assert persisted['completedToolArguments']['call-large']['arguments'] == full
    assert '_truncated' in store.events('local', run.run_id)[-1][1]['data']['result']['tool_call']['args']


def test_expected_action_does_not_accept_http_or_network_failure_evidence(tmp_path):
    from local_shell_mcp.webui.event_triggers import _observed_action
    from local_shell_mcp.webui.generations import GenerationStore

    database = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(database)
    run, _ = store.begin('local', {'text': 'Call external service'})
    for index, output in enumerate(('API call failed (HTTP 500)', 'API call failed (timeout)',
                                     'API call failed (network error)')):
        store.append('local', run.run_id, {'event': 'on_run_step_completed', 'data': {'result': {
            'id': f'step-{index}', 'tool_call': {'id': f'call-{index}',
                'name': f'action_{index}', 'args': {'tenant': 'support'}, 'output': output}}}},
            full_arguments={'tenant': 'support'})
    with database.connect() as db:
        for index in range(3):
            assert not _observed_action(db, run.run_id, {
                'toolName': f'action_{index}', 'argumentSubset': {'tenant': 'support'}})


def test_completed_file_tool_keeps_arguments_transactional_with_sse(tmp_path):
    from local_shell_mcp.webui.generations import GenerationStore

    database = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(database)
    run, _ = store.begin('local', {'text': 'Persist full tool arguments'})
    event = {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'file-step', 'type': 'tool_call', 'tool_call': {
            'id': 'call-file', 'name': 'file_write', 'args': {'_truncated': True},
            'output': 'saved'}}}}
    store.append_tool_completion('local', run.run_id, event, 'call-file', [],
                                 full_arguments={'path': 'report.md', 'content': 'A' * 33000})
    with database.connect() as db:
        state = json.loads(db.execute('SELECT state FROM runs WHERE id=?',
                                      (run.run_id,)).fetchone()['state'])
        assert state['completedToolArguments']['call-file']['arguments']['path'] == 'report.md'
    assert sum(e.get('event') == 'on_run_step_completed' for _, e in store.events('local', run.run_id)) == 1


@pytest.mark.asyncio
async def test_reviewed_tool_edits_record_actual_arguments_and_respond_is_not_execution(tmp_path, monkeypatch):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.checkpoints import SQLiteCheckpointSaver
    from local_shell_mcp.webui.event_triggers import _observed_action
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig

    database = SQLiteDatabase(tmp_path / 'db')
    store = GenerationStore(database)
    run, _ = store.begin('local', {'text': 'Review tool calls'})

    async def unused(*args, **kwargs):
        return None

    monkeypatch.setattr(SQLiteCheckpointSaver, 'put_writes', lambda *args, **kwargs: None)
    runner = AgentRunner('local', run, database, store, scopes=set(), grant_expires=None,
                         stream_tools=unused, stream_text=unused, on_text=unused,
                         profile=ProviderConfig('openai', 'mock', 'https://example.invalid', ''))
    reviewed = ModelToolCall('call-edited', 'send_action', {'to': 'new', 'payload': 'x' * 20000})
    await runner._completed(reviewed, {'output': '{"ok":true}'}, executed=True)
    offered = ModelToolCall('call-responded', 'send_action', {'to': 'unreviewed'})
    await runner._completed(offered, {'output': 'Provided by user'}, executed=False)
    with database.connect() as db:
        assert _observed_action(db, run.run_id, {'toolName': 'send_action',
                                                 'argumentSubset': {'to': 'new'}})
        assert not _observed_action(db, run.run_id, {'toolName': 'send_action',
                                                     'argumentSubset': {'to': 'unreviewed'}})
        assert not _observed_action(db, run.run_id, {'toolName': 'send_action',
                                                     'argumentSubset': {'to': 'old'}})
        state = json.loads(db.execute('SELECT state FROM runs WHERE id=?', (run.run_id,)).fetchone()['state'])
        assert state['completedToolArguments']['call-edited']['arguments']['to'] == 'new'
        assert 'call-responded' not in state['completedToolArguments']
    recorded = [e['data']['result']['tool_call'] for _, e in store.events('local', run.run_id)
                if e.get('event') == 'on_run_step_completed']
    assert any(e.get('executed') is False for e in recorded)
