"""Original authenticated Agent Trigger source envelope, idempotency and per-key ACL."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    delivery_key,
    enqueue_event,
    get_event,
    mint_source_key,
    prepare_source_event,
    revoke_source_key,
    source_keys,
    validate_source_key,
)


@pytest.fixture
def env(tmp_path):
    database = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    agent = AgentRepository(database).create('alice', {'name': 'research', 'provider': 'openai',
                                                        'model': 'test', 'tools': []})
    secret = mint_source_key(database, 'alice', permissions=('fire',))
    return database, agent, secret


def request(agent, *, key='event-1', message='Hello'):
    return {'mode': 'fire', 'event': {'id': key, 'type': 'resource.ready',
            'occurredAt': 1786967999000, 'source': {'id': 'forged', 'type': 'unsafe'}},
            'target': {'agentId': agent['id']}, 'input': message}


def test_source_key_has_only_one_visible_secret_and_revocation_is_immediate(env):
    db, agent, key = env
    assert key['token'].startswith('lsm_evt_')
    assert validate_source_key(db, key['token']) == {'id': key['id'], 'owner': 'alice', 'permissions': ['fire']}
    assert key['token'] not in json.dumps(source_keys(db, 'alice'))
    assert source_keys(db, 'bob') == []
    assert validate_source_key(db, key['token'] + '!') is None
    assert revoke_source_key(db, 'bob', key['id']) is False
    assert revoke_source_key(db, 'alice', key['id']) is True
    assert revoke_source_key(db, 'alice', key['id']) is False
    assert validate_source_key(db, key['token']) is None


def test_source_envelope_overwrites_untrusted_user_and_source_identity(env):
    db, agent, key = env
    body = request(agent)
    body['principal'] = {'id': 'elevated'}
    envelope, lane = prepare_source_event('alice', key['id'], 'resource-42', body, received_at=123)
    assert envelope['principal'] == {'userId': 'alice'}
    assert envelope['event']['source'] == {'id': key['id'], 'type': 'remote_api_key'}
    assert envelope['deliveryId'] == 'resource-42'
    assert len(delivery_key(envelope)) == 72
    assert lane.startswith('trigger_lane_')
    assert envelope['receivedAt'] == 123


def test_durable_idempotent_delivery_retries_and_conflicts_by_same_source(env):
    db, agent, key = env
    first = enqueue_event(db, 'alice', key['id'], 'resource-42', request(agent))
    again = enqueue_event(db, 'alice', key['id'], 'resource-42', request(agent))
    assert first['id'] == again['id'] and again['replayed'] is True
    status = get_event(db, 'alice', key['id'], first['id'])
    assert status['status'] == 'pending' and status['attempts'] == 0
    assert get_event(db, 'not-alice', key['id'], first['id']) is None
    assert get_event(db, 'alice', 'not-that-source', first['id']) is None
    with pytest.raises(ValueError, match='Idempotency'):
        enqueue_event(db, 'alice', key['id'], 'resource-42', request(agent, message='different'))
    with pytest.raises(ValueError, match='target.conversationId'):
        enqueue_event(db, 'alice', key['id'], 'resource-43',
                      request(agent, key='second') | {'mode': 'continue'})
    assert len(db.path.read_bytes()) > 100


@pytest.mark.parametrize('bad_key', ['', 'with space', 'x'*257, 'a\nb'])
def test_bad_idempotency_keys_rejected(env, bad_key):
    db, agent, key = env
    with pytest.raises(ValueError):
        enqueue_event(db, 'alice', key['id'], bad_key, request(agent))
