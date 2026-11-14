"""Two-controller SQLite fencing and fresh-grant SSE restart of ordinary runs."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
from local_shell_mcp.webui.checkpoints import SQLiteCheckpointSaver
from local_shell_mcp.webui.generation_actor_lease import (
    ActorLease,
    active_run_ids,
    resumable_run_ids,
)
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture
def context(tmp_path, monkeypatch):
    root = tmp_path / '.state'
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(root))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    first, second = SQLiteDatabase(root), SQLiteDatabase(root)
    store = GenerationStore(first)
    job, _ = store.begin('local', {'text': 'ordinary user request'})
    monkeypatch.setattr(generation_routes, '_database', lambda: first)
    monkeypatch.setattr(generation_routes, 'provider_config', lambda *args: ProviderConfig(
        'openai', 'test', 'http://localhost:9000/v1/chat/completions', ''))
    yield first, second, store, job
    get_settings.cache_clear()


def test_one_actor_claim_across_controller_db_instances(context):
    first, second, store, job = context

    def race(index):
        return ActorLease.claim(first if index % 2 else second, 'local', job.run_id)

    with ThreadPoolExecutor(max_workers=20) as pool:
        actors = [a for a in pool.map(race, range(32)) if a is not None]
    assert len(actors) == 1
    winner = actors[0]
    assert winner.is_current()
    assert job.run_id in active_run_ids(second)
    assert winner.renew()
    assert not ActorLease.claim(second, 'other', job.run_id)
    with first.connect() as conn:
        conn.execute('UPDATE generation_actor_leases SET expires_at=0 WHERE run_id=?', (job.run_id,))
    replacement = ActorLease.claim(second, 'local', job.run_id)
    assert replacement and replacement.token != winner.token
    with pytest.raises(RuntimeSafetyError, match='lease'):
        winner.assert_current()
    with pytest.raises(RuntimeSafetyError, match='lease'):
        store.append('local', job.run_id, {'event': 'forged'}, actor_lease=winner)
    with pytest.raises(RuntimeSafetyError, match='lease'):
        store.finish('local', job.run_id, status='complete', actor_lease=winner)
    assert store.append('local', job.run_id, {'event': 'new-owner'}, actor_lease=replacement)
    assert store.finish('local', job.run_id, status='complete', actor_lease=replacement)
    assert not replacement.renew()
    winner.release()  # old actor must not delete the new actor's lease
    with first.connect() as conn:
        assert conn.execute('SELECT token FROM generation_actor_leases WHERE run_id=?',
                            (job.run_id,)).fetchone()[0] == replacement.token
    replacement.release()
    assert job.run_id not in active_run_ids(first)


def test_checkpointed_ordinary_run_is_preserved_while_uncheckpointed_orphan_terminates(context):
    first, second, store, job = context
    saver = SQLiteCheckpointSaver(first, 'local')
    config = saver.config(job.conversation_id, job.run_id, event_actor=True)
    saver.put(config, {'v': 1, 'id': '00001', 'channel_values': {
        'messages': [{'role': 'user', 'content': 'ordinary user request'}],
        'step': 0, 'model_turn': 0, 'pending_calls': [],
        'tool_step_started': False, 'completed': False, 'agent_id': None,
    }, 'channel_versions': {}, 'versions_seen': {}}, {'source': 'loop', 'step': 0})
    orphan, _ = store.begin('local', {'text': 'no checkpoint'})
    assert job.run_id in resumable_run_ids(second)
    assert orphan.run_id not in resumable_run_ids(second)
    exclusions = active_run_ids(first) | resumable_run_ids(first)
    assert store.recover_orphans(exclusions) == 1
    assert store.get('local', job.run_id).status == 'running'
    assert store.get('local', orphan.run_id).status == 'interrupted'


@pytest.mark.asyncio
async def test_sse_resume_reattaches_after_controller_crash_with_fresh_grants(context, monkeypatch):
    first, second, store, job = context
    saver = SQLiteCheckpointSaver(first, 'local')
    config = saver.config(job.conversation_id, job.run_id, event_actor=True)
    saver.put(config, {'v': 1, 'id': '00001', 'channel_values': {
        'messages': [{'role': 'user', 'content': 'ordinary user request'}],
        'step': 0, 'model_turn': 0, 'pending_calls': [],
        'tool_step_started': False, 'completed': False, 'agent_id': None,
    }, 'channel_versions': {}, 'versions_seen': {}}, {'source': 'loop', 'step': 0})
    # Simulate the first Controller crashing: the new process shares SQLite,
    # but no in-memory task or scope grant survives.
    seen = []

    async def model(profile, messages, **kwargs):
        seen.append(messages)
        yield 'Successfully resumed on a fresh Controller.'

    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', model)
    monkeypatch.setattr(generation_routes, 'stream_model', model)
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await asyncio.wait_for(client.get(
            f'/api/agents/chat/stream/{job.conversation_id}?resume=true'), 15)
        assert response.status_code == 200, response.text
        assert '"sync":true' in response.text
        assert 'Successfully resumed on a fresh Controller.' in response.text
    assert len(seen) == 1
    assert store.get('local', job.run_id).status == 'complete'
    assert job.run_id not in active_run_ids(first)


@pytest.mark.asyncio
async def test_sse_does_not_start_an_actor_while_another_controller_owns_it(context, monkeypatch):
    first, second, store, job = context
    active = ActorLease.claim(second, 'local', job.run_id)
    assert active
    async def broken(*args, **kwargs):
        raise AssertionError('A second Controller tried to start the model')
        yield ''

    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', broken)
    monkeypatch.setattr(generation_routes, 'stream_model', broken)
    # The lease is valid. The route reattaches as a passive SSE client, not
    # another model scheduler, even when there is no local event-loop task.
    assert job.run_id in active_run_ids(first)
    assert generation_routes._TASKS.get(job.run_id) is None
    assert ActorLease.claim(first, 'local', job.run_id) is None
    from starlette.requests import Request

    req = Request({'type': 'http', 'method': 'GET',
                   'path': '/api/agents/chat/stream/' + job.conversation_id,
                   'path_params': {'stream_id': job.conversation_id},
                   'query_string': b'resume=true', 'headers': []})
    response = await generation_routes.stream_generation(req)
    assert response.status_code == 200
    assert job.run_id not in generation_routes._TASKS
    active.release()


@pytest.mark.asyncio
async def test_old_controller_cannot_emit_or_finalize_after_root_lease_takeover(context, monkeypatch):
    first, second, store, job = context
    entered = asyncio.Event()
    release = asyncio.Event()

    async def model(profile, history, **kwargs):
        entered.set()
        await release.wait()
        yield 'must not arrive after lease takeover'

    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', model)
    monkeypatch.setattr(generation_routes, 'stream_model', model)
    profile = ProviderConfig('openai', 'test', 'http://localhost:9000/v1/chat/completions', '')
    await generation_routes._start_task('local', job, profile, None)
    await asyncio.wait_for(entered.wait(), 8)
    with first.connect() as conn:
        conn.execute('UPDATE generation_actor_leases SET expires_at=0 WHERE run_id=?', (job.run_id,))
    takeover = ActorLease.claim(second, 'local', job.run_id)
    assert takeover
    release.set()
    current = generation_routes._TASKS[job.run_id]
    await asyncio.wait_for(current, 8)
    assert store.get('local', job.run_id).status == 'running'
    assert not any('must not arrive' in str(e) for _, e in store.events('local', job.run_id))
    assert takeover.is_current()
    takeover.release()


@pytest.mark.asyncio
async def test_crash_after_steer_applied_before_first_checkpoint_replays_instruction(context, monkeypatch):
    from local_shell_mcp.webui.steering import SteeringStore

    first, second, store, job = context
    steering = SteeringStore(first)
    ack = steering.enqueue('local', {'conversationId': job.conversation_id,
        'generationCreatedAt': job.generation_created_at, 'text': 'Durable correction',
        'clientSteerId': 'stale-checkpoint'}, preempt_capable=True)
    # The source applied SSE + SQLite receipt commits here. Simulate a power
    # loss before any AgentRunner / StateGraph checkpoint transaction.
    assert len(steering.drain('local', job.run_id, boundary='terminal')) == 1
    assert ack['steerId'] in str(steering.applied_parts('local', job.run_id))
    assert job.run_id in resumable_run_ids(second)
    assert store.recover_orphans(resumable_run_ids(second)) == 0
    observed = []

    async def model(profile, messages, **kwargs):
        observed.append(messages)
        assert sum(m.get('steerId') == ack['steerId'] for m in messages) == 1
        assert messages[-1]['content'] == 'Durable correction'
        yield 'Processed recovered steer.'

    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', model)
    monkeypatch.setattr(generation_routes, 'stream_model', model)
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await asyncio.wait_for(client.get(
            f'/api/agents/chat/stream/{job.conversation_id}?resume=true'), 15)
        assert response.status_code == 200, response.text
    assert len(observed) == 1
    assert store.get('local', job.run_id).status == 'complete'
    assert sum(e.get('event') == 'on_steer_applied' for _, e in store.events('local', job.run_id)) == 1


@pytest.mark.asyncio
async def test_heartbeat_stops_if_run_lease_changes(context, monkeypatch):
    from local_shell_mcp.webui import generation_actor_lease

    first, second, store, job = context
    lease = ActorLease.claim(first, 'local', job.run_id)
    assert lease is not None
    monkeypatch.setattr(generation_actor_lease, '_RENEW_S', .01)
    with first.connect() as connection:
        connection.execute('UPDATE generation_actor_leases SET expires_at=0 WHERE run_id=?', (job.run_id,))
    await asyncio.wait_for(lease.keep_alive(), 1)
    with first.connect() as connection:
        assert connection.execute('SELECT expires_at FROM generation_actor_leases WHERE run_id=?',
                                  (job.run_id,)).fetchone()[0] == 0
    lease.release()


def test_recovery_exclusion_preserves_other_live_controller(context):
    first, second, store, job = context
    owner = ActorLease.claim(first, 'local', job.run_id)
    assert owner is not None
    assert resumable_run_ids(second, excludes=active_run_ids(second)) == set()
    owner.release()
