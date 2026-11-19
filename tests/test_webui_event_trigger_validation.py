"""Source edge validation and stable opaque idempotency without fake oracle expectations."""
from __future__ import annotations

import time

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    _NO_PARENT,
    bound_child,
    enqueue_event,
    get_event,
    mint_source_key,
    prepare_source_event,
    register_bound_child,
    validate_source_key,
)


@pytest.fixture
def env(tmp_path):
    db = SQLiteDatabase(tmp_path / 'data')
    repo = AgentRepository(db)
    agent = repo.create('owner', {'name':'A', 'provider':'openai','model':'a','tools':[]})
    key = mint_source_key(db, 'owner', permissions=('fire',))
    return db, agent, key


def event(agent):
    return {'mode':'fire','event':{'id':'source-01','type':'resource.ready','occurredAt':123},
            'target':{'agentId':agent['id']},'input':'Hello'}


@pytest.mark.parametrize('field,value', [
    ('label',''), ('label','a'*129), ('permissions',()),
    ('permissions',('fictitious',)), ('expires_at',int(time.time()*1000)-5000),
])
def test_source_credential_creation_rejects_invalid_metadata(env, field, value):
    db, agent, key = env
    with pytest.raises(ValueError):
        mint_source_key(db, 'owner', **{field:value})


def test_expired_source_token_is_not_authentic_and_cannot_be_reused(env):
    db, agent, key = env
    with db.connect() as conn:
        conn.execute('UPDATE agent_event_source_keys SET expires_at=? WHERE id=?',
                     (0,key['id']))
    assert validate_source_key(db, key['token']) is None
    with pytest.raises(PermissionError, match='revoked'):
        enqueue_event(db, 'owner', key['id'], 'try-after-expiry', event(agent))


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(mode='not-a-mode'),
    lambda d: d.update(event=None),
    lambda d: d.update(target=[]),
    lambda d: d['event'].update(occurredAt=-1),
    lambda d: d['event'].update(occurredAt=True),
    lambda d: d['event'].update(occurredAt=2**53),
    lambda d: d['event'].update(id=''),
    lambda d: d['event'].update(type=17),
    lambda d: d['target'].update(agentId=None),
    lambda d: d.update(input=''),
    lambda d: d.update(orderingKey=' '),
    lambda d: d.update(orderingKey='x'*257),
    lambda d: d.update(coalesce={'key':'not-supported'}),
    lambda d: d.update(expectedAction={'toolName':'write'}),
    lambda d: d['event'].update(payload={'bad':float('nan')}),
])
def test_invalid_source_event_fails_before_queue_write(env, mutation):
    db, agent, key = env
    body = event(agent)
    mutation(body)
    with pytest.raises((ValueError,TypeError)):
        enqueue_event(db, 'owner', key['id'], 'request-invalid', body)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0] == 0


@pytest.mark.parametrize('target,body_extra,expected', [
    ({'conversationId':'convo','generationCreatedAt':-1}, {}, 'generationCreatedAt'),
    ({'conversationId':'convo','generationCreatedAt':123,'preempt':'false'}, {}, 'preempt'),
    ({'conversationId':'convo','generationCreatedAt':123,'preempt':True}, {}, None),
])
def test_source_steer_envelope_target_validation_without_unimplemented_admission(env,
                                                                                    target,body_extra,expected):
    db, agent, key = env
    body = event(agent)
    body.update(mode='steer',target={'agentId':agent['id'],**target},**body_extra)
    if expected:
        with pytest.raises(ValueError, match=expected):
            prepare_source_event('owner',key['id'],'stable',body)
    else:
        envelope,_ = prepare_source_event('owner',key['id'],'stable',body)
        assert envelope['target']['preempt'] is True
        # The source key here permits only fire. A syntactically valid Steer
        # still must not bypass its authenticated mode policy.
        with pytest.raises(PermissionError, match='not allowed'):
            enqueue_event(db,'owner',key['id'],'stable',body)


def test_exact_event_continue_binding_key_restrictions_and_parent_replay(env):
    db, agent, key = env
    body = event(agent)
    body.update(mode='continue',target={'agentId':agent['id'],'conversationId':'child',
                'parentMessageId':_NO_PARENT,'bindingId':'evtbind_'+'0'*48})
    with pytest.raises(PermissionError, match='binding'):
        enqueue_event(db,'owner',key['id'],'unbound',body)
    with pytest.raises(ValueError, match='Event binding'):
        bound_child(db,'owner',key['id'],'not-valid')
    assert bound_child(db,'owner',key['id'],'evtbind_'+'0'*48) is None
    with pytest.raises(ValueError, match='invalid'):
        get_event(db,'owner',key['id'],'not-valid')
    with pytest.raises(KeyError):
        register_bound_child(db,'owner',key['id'],'register',actor_id='actor',
            parent_conversation_id='not-found',parent_message_id='missing',
            target_agent_id=agent['id'])


def test_different_source_principal_cannot_address_other_owner_agent(env):
    db, agent, key = env
    foreign = mint_source_key(db,'other',permissions=('fire',))
    with pytest.raises(PermissionError, match='owned'):
        enqueue_event(db,'other',foreign['id'],'foreign-1',event(agent))
    # No source prompt or bearer token is stored in a public receipt.
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_deliveries').fetchone()[0] == 0
