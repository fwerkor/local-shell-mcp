"""Authenticated completed-parent child registration cannot bypass Artifact guard."""
from __future__ import annotations

import uuid

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.child_thread_activity import ActiveChildThreads
from local_shell_mcp.webui.generations import GenerationStore


@pytest.fixture
def parent(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    agent = AgentRepository(db).create('owner', {'name': 'parent', 'provider': 'openai',
                                                 'model': 'test', 'tools': []})
    generation, _ = GenerationStore(db).begin('owner', {'text': 'Parent'}, agent)
    return db, generation


def child_id():
    return str(uuid.uuid4())


@pytest.mark.parametrize('item', ['owner', 'child', 'run', 'reply'])
def test_completed_parent_guard_requires_all_trusted_nonempty_fields(parent, item):
    db, generation = parent
    values = {'owner': 'owner', 'child': child_id(), 'run': generation.run_id,
              'reply': generation.response_message_id}
    values[item] = ''
    with pytest.raises(ValueError, match='trusted owner'):
        ActiveChildThreads(db).reserve_for_completed_parent(*values.values())


def test_guard_rejects_nonterminal_or_foreign_parent_generation(parent):
    db, generation = parent
    with pytest.raises(PermissionError, match='completed'):
        ActiveChildThreads(db).reserve_for_completed_parent('owner', child_id(),
                                                              generation.run_id,
                                                              generation.response_message_id)
    with pytest.raises(PermissionError, match='completed'):
        ActiveChildThreads(db).reserve_for_completed_parent('foreign', child_id(),
                                                              generation.run_id,
                                                              generation.response_message_id)


def test_guard_denies_parent_reply_spoofing_self_thread_and_missing_assistant(parent):
    db, generation = parent
    GenerationStore(db).finish('owner', generation.run_id, status='complete', text='settled')
    guard = ActiveChildThreads(db)
    with pytest.raises(PermissionError, match='parent reply'):
        guard.reserve_for_completed_parent('owner', child_id(), generation.run_id, 'fake-reply')
    with pytest.raises(PermissionError, match='parent reply'):
        guard.reserve_for_completed_parent('owner', generation.conversation_id,
                                           generation.run_id, generation.response_message_id)
    with db.connect() as conn:
        conn.execute('DELETE FROM messages WHERE id=?', (generation.response_message_id,))
    with pytest.raises(PermissionError, match='parent reply'):
        guard.reserve_for_completed_parent('owner', child_id(), generation.run_id,
                                           generation.response_message_id)


def test_guard_reservation_is_owner_immutable_and_replay_idempotent(parent):
    db, generation = parent
    GenerationStore(db).finish('owner', generation.run_id, status='complete', text='settled')
    guard = ActiveChildThreads(db)
    reserved = child_id()
    guard.reserve_for_completed_parent('owner', reserved, generation.run_id,
                                       generation.response_message_id)
    guard.reserve_for_completed_parent('owner', reserved, generation.run_id,
                                       generation.response_message_id)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM active_subagent_threads WHERE thread_id=?',
                            (reserved,)).fetchone()[0] == 1
        conn.execute('UPDATE active_subagent_threads SET parent_run_id=? WHERE thread_id=?',
                     ('other_parent', reserved))
    with pytest.raises(PermissionError, match='another parent'):
        guard.reserve_for_completed_parent('owner', reserved, generation.run_id,
                                           generation.response_message_id)


def test_guard_denies_existing_child_conversation_even_if_same_owner(parent):
    db, generation = parent
    GenerationStore(db).finish('owner', generation.run_id, status='complete', text='settled')
    occupied = generation.conversation_id
    with pytest.raises(PermissionError, match='invalid parent reply or thread'):
        ActiveChildThreads(db).reserve_for_completed_parent('owner', occupied,
            generation.run_id, generation.response_message_id)
    second, _ = GenerationStore(db).begin('owner', {'text': 'Other conversation'})
    with pytest.raises(PermissionError, match='already exists'):
        ActiveChildThreads(db).reserve_for_completed_parent('owner', second.conversation_id,
            generation.run_id, generation.response_message_id)
