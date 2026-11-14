"""Real original bound Event Actor creation, owner-scoped source and child guard."""
from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.event_triggers import (
    _NO_PARENT,
    binding_key,
    bound_child,
    enqueue_event,
    mint_source_key,
    register_bound_child,
)
from local_shell_mcp.webui.generations import GenerationStore


@pytest.fixture
def actors(tmp_path):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    repo = AgentRepository(db)
    child = repo.create('alice', {'name':'child','provider':'openai','model':'small','tools':[]})
    parent = repo.create('alice', {'name':'parent','provider':'openai','model':'small',
                                   'tools':[], 'subagents':{'enabled':True,'agent_ids':[child['id']]}})
    generation, _ = GenerationStore(db).begin('alice', {'text':'Prepare a child event actor'}, parent)
    GenerationStore(db).finish('alice', generation.run_id, status='complete', text='Child authorized')
    source = mint_source_key(db, 'alice', permissions=('continue',))
    return db, parent, child, generation, source


@pytest.fixture
def stub_guard():
    # Real PR352 child write-fence is integrated in this branch.
    from local_shell_mcp.webui.child_thread_activity import ActiveChildThreads

    return ActiveChildThreads


def _register(actors, **override):
    db, parent, child, generation, source = actors
    return register_bound_child(db, 'alice', source['id'], override.pop('key','actor-key-1'),
                                actor_id=override.pop('actor_id','delegate'),
                                parent_conversation_id=override.pop('parent_conversation_id', generation.conversation_id),
                                parent_message_id=override.pop('parent_message_id', generation.response_message_id),
                                target_agent_id=override.pop('target_agent_id',child['id']))


def test_missing_actual_artifact_child_guard_fails_closed_no_writable_conversation(actors, monkeypatch):
    from local_shell_mcp.webui.child_thread_activity import ActiveChildThreads

    monkeypatch.setattr(ActiveChildThreads, 'reserve_for_completed_parent', None)
    db, parent, child, generation, source = actors
    with pytest.raises(RuntimeError, match='Child conversation write guard'):
        _register(actors)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_bindings').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM conversations').fetchone()[0] == 1


def test_source_bound_direct_child_idempotency_and_parent_lineage(actors, stub_guard):
    db, parent, child, generation, source = actors
    first = _register(actors)
    second = _register(actors)
    assert first == second
    assert first['id'] == binding_key('alice', source['id'], 'actor-key-1')
    assert first['id'].startswith('evtbind_') and len(first['id']) == 56
    with db.connect() as conn:
        reserved = conn.execute('SELECT archived,agent_id,metadata FROM conversations WHERE id=?',
                                (first['threadId'],)).fetchone()
        assert reserved['archived'] == 1 and reserved['agent_id'] == child['id']
        lineage = json.loads(reserved['metadata'])
        assert lineage['subagentThread']['parentMessageId'] == generation.response_message_id
        assert lineage['agentEventBinding']['sourceKeyId'] == source['id']
        marker = conn.execute('SELECT parent_run_id FROM active_subagent_threads WHERE thread_id=?',
                              (first['threadId'],)).fetchone()
        assert marker['parent_run_id'] == generation.run_id
    assert bound_child(db, 'alice', source['id'], first['id'])['conversation_id'] == first['threadId']
    assert bound_child(db, 'alice', 'other-key', first['id']) is None
    assert bound_child(db, 'bob', source['id'], first['id']) is None
    with pytest.raises(ValueError, match='Idempotency-Key'):
        _register(actors, actor_id='different')


def test_invalid_child_or_parent_lineage_rejected_by_original_contract(actors, stub_guard):
    db, parent, child, generation, source = actors
    unrelated = AgentRepository(db).create('alice', {'name': 'unrelated', 'provider': 'openai',
                                                     'model': 'small', 'tools': []})
    with pytest.raises(PermissionError, match='direct child'):
        _register(actors, target_agent_id=unrelated['id'])
    with pytest.raises(KeyError, match='reply'):
        _register(actors, parent_message_id='foreign-reply')
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM agent_event_bindings').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_bound_continue_uses_reserved_child_thread_and_source_order_lane(actors, stub_guard, monkeypatch):
    from local_shell_mcp.webui import agent_runner, providers
    from local_shell_mcp.webui.event_triggers import (
        process_event_deliveries,
        shutdown_event_workers,
    )
    from local_shell_mcp.webui.providers import ProviderConfig

    db, parent, child, generation, source = actors
    binding = _register(actors)
    payload = {'mode':'continue', 'event':{'id':'turn-1','type':'chess.turn.ready',
               'occurredAt':1786968000000}, 'target':{'agentId':child['id'],
               'conversationId':binding['threadId'], 'parentMessageId':_NO_PARENT,
               'bindingId':binding['id']}, 'input':'Analyze this move',
               'orderingKey':binding['id']}
    receipt = enqueue_event(db, 'alice', source['id'], 'ply-1', payload)
    assert receipt['status'] == 'pending'
    monkeypatch.setattr(providers, 'provider_config', lambda *args: ProviderConfig(
        'openai','small','https://example.invalid',''))
    monkeypatch.setattr(agent_runner,'provider_config', providers.provider_config)
    received = []
    async def dispatch(owner, generation, profile, agent, **kwargs):
        received.append((generation, kwargs))
    assert await process_event_deliveries(db, dispatch=dispatch) == 1
    child_generation, options = received[0]
    assert child_generation.conversation_id == binding['threadId']
    assert child_generation.agent_id == child['id']
    assert options['native_file_tools'] is False and options['granted_scopes'] == frozenset()
    with db.connect() as conn:
        content = conn.execute('SELECT parent_id FROM messages WHERE id=?',
                               (child_generation.user_message_id,)).fetchone()
        assert content['parent_id'] == _NO_PARENT
    GenerationStore(db).finish('alice', child_generation.run_id, status='complete', text='My turn')
    assert await process_event_deliveries(db, dispatch=dispatch) == 0
    await shutdown_event_workers()
