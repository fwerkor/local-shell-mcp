"""Opt-in automatic MemoryRun: source gate, BPE window, tool-end and SSE artifact."""
from __future__ import annotations

import time

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes, memory_agent
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import MemoryRepository
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def memory_run(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
    store = GenerationStore(db)
    settings = WorkspaceRepository(db)
    job, _ = store.begin('alice', {'text': 'Remember that I prefer short answers.'})
    default = ProviderConfig('openai', 'mock-memory', 'http://localhost/mock', '')
    monkeypatch.setattr(memory_agent, 'provider_config', lambda *args, **kwargs: default)
    return db, store, settings, job, default


def enable(settings, *, agent=None):
    settings.save_setting('alice', 'endpoints', {
        'memory': {'tokenLimit': 120, 'agent': agent or {
            'enabled': True, 'provider': 'openAI', 'model': 'mock-memory',
        }},
        'agents': {'capabilities': ['memory']},
    })


@pytest.mark.asyncio
async def test_disabled_or_missing_memory_agent_never_starts_model(memory_run):
    db, store, settings, job, profile = memory_run

    async def blocked(*args, **kwargs):
        raise AssertionError('Automatic memory model must be opt-in')
        yield 'unreachable' 

    history = store.history('alice', job.conversation_id)
    assert await memory_agent.run_automatic_memory('alice', job, db, history,
        root_agent=None, stream_tools=blocked) == 0
    enable(settings, agent={'enabled': False, 'provider': 'openAI', 'model': 'mock-memory'})
    assert await memory_agent.run_automatic_memory('alice', job, db, history,
        root_agent=None, stream_tools=blocked) == 0
    enable(settings)
    settings.save_setting('alice', 'user.memories', False)
    assert await memory_agent.run_automatic_memory('alice', job, db, history,
        root_agent=None, stream_tools=blocked) == 0


@pytest.mark.asyncio
async def test_automatic_memory_tools_commit_with_persistent_attachment(memory_run):
    db, store, settings, job, profile = memory_run
    enable(settings)
    received = []

    async def stream(config, messages, **kw):
        received.append((config, messages, kw))
        assert 'ONLY for memory requests' in messages[0]['content']
        assert '# Current Chat:' in messages[-1]['content']
        assert len(kw['tools']) == 2
        yield ModelToolCall('memory-1', 'set_memory', {'key': 'style', 'value': 'The user prefers concise replies.'})
        yield 'Complete'

    history = store.history('alice', job.conversation_id)
    assert await memory_agent.run_automatic_memory('alice', job, db, history,
        root_agent=None, stream_tools=stream) == 1
    assert len(received) == 1
    assert MemoryRepository(SQLiteDatabase(db.root)).list('alice', '')[0]['key'] == 'style'
    event = store.events('alice', job.run_id)[-1][1]
    assert event['event'] == 'attachment'
    assert event['data']['type'] == 'memory'
    assert event['data']['toolCallId'] == 'memory-1'
    assert event['data']['memory']['type'] == 'update'
    assert event['data']['messageId'] == job.response_message_id
    assert event['data']['conversationId'] == job.conversation_id
    assert store.finish('alice', job.run_id, status='complete', text='The answer')
    assert store.events('alice', job.run_id)[-1][1]['final'] is True


@pytest.mark.asyncio
async def test_auto_memory_deleted_or_filtered_and_concurrent_policy_changes(memory_run):
    db, store, settings, job, profile = memory_run
    enable(settings)
    memory = MemoryRepository(db)
    memory.write('alice', 'style', 'Use original style.')
    history = store.history('alice', job.conversation_id)

    async def stream(*args, **kw):
        settings.save_setting('alice', 'webui.filters.config', {'memories': {'pii': {
            'fields': ['value'], 'starterPatterns': [],
            'customPatterns': [{'id': 'secret', 'label': 'protected', 'regex': 'PRIVATE-[A-Z]+'}],
        }}})
        yield ModelToolCall('filter-1', 'set_memory', {'key': 'style', 'value': 'PRIVATE-SECRET'})
        yield ModelToolCall('delete-1', 'delete_memory', {'key': 'style'})

    assert await memory_agent.run_automatic_memory('alice', job, db, history,
        root_agent=None, stream_tools=stream) == 1
    assert not memory.list('alice')
    saved = [event['data']['memory'] for _, event in store.events('alice', job.run_id)
             if event.get('event') == 'attachment']
    assert [item['type'] for item in saved] == ['delete']
    assert 'PRIVATE-SECRET' not in str(saved)


@pytest.mark.asyncio
async def test_agent_partition_and_quota_enforced(memory_run):
    db, store, settings, job, profile = memory_run
    enable(settings)
    root = {'id': 'agent_a____child', 'tools': ['memory'], 'memory_scope': 'agent'}

    async def stream(*args, **kwargs):
        yield ModelToolCall('memory-2', 'set_memory', {'key': 'style', 'value': 'Use summaries.'})

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=root, stream_tools=stream) == 1
    assert MemoryRepository(db).list('alice', '') == []
    assert MemoryRepository(db).list('alice', 'agent_a')[0]['value'] == 'Use summaries.'
    assert MemoryRepository(db).list('bob', 'agent_a') == []
    settings.save_setting('alice', 'user.memories', False)
    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=root, stream_tools=stream) == 0


@pytest.mark.asyncio
async def test_model_failures_and_untrusted_config_do_not_break_chat(memory_run, monkeypatch):
    db, store, settings, job, profile = memory_run
    enable(settings, agent={'enabled': True, 'id': 'foreign-agent'})

    async def fail(*args, **kwargs):
        raise ValueError('provider unavailable')
        yield

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=fail) == 0
    enable(settings)
    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=fail) == 0
    assert store.get('alice', job.run_id).status == 'running'


def test_memory_window_preserves_last_user_turn_and_truncates_by_bpe():
    history = [
        {'role': 'user', 'content': f'Turn {n}.'} if n % 2 == 0 else
        {'role': 'assistant', 'content': f'Answer {n}.'}
        for n in range(14)
    ]
    history.append({'role': 'user', 'content': 'Z' * 16000 + ' final request'})
    window = memory_agent._memory_window(history, window_size=3, max_tokens=80)
    assert '# Current Chat' in window or '[Earlier chat content omitted' in window
    assert 'Turn 0.' not in window
    assert 'final request' in window
    assert memory_agent.count_tokens(window, exact=False) <= 80


@pytest.mark.asyncio
async def test_root_generation_runs_optin_memory_alongside_chat(memory_run, monkeypatch):
    db, store, settings, job, profile = memory_run
    enable(settings)
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)
    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', stream_memory)

    async def main_text(*args, **kwargs):
        yield 'Normal response.'

    monkeypatch.setattr(generation_routes, 'stream_model', main_text)
    from local_shell_mcp.webui import agent_runner

    class StubChatRunner:
        def __init__(self, *args, on_text, **kwargs):
            self.partial_text = 'Normal response.'
            self.on_text = on_text

        async def run(self, history):
            await self.on_text('Normal response.')
            return history

    monkeypatch.setattr(agent_runner, 'AgentRunner', StubChatRunner)
    await generation_routes._run_model('alice', job, profile)
    assert store.latest('alice', job.conversation_id).status == 'complete'
    assert store.history('alice', job.conversation_id)[-1]['content'] == 'Normal response.'
    assert MemoryRepository(db).list('alice', '')[0]['key'] == 'style'
    assert any(event.get('event') == 'attachment' for _, event in store.events('alice', job.run_id))


async def stream_memory(*args, **kwargs):
    yield ModelToolCall('attached-memory', 'set_memory', {'key': 'style', 'value': 'The user likes brief answers.'})


@pytest.mark.asyncio
async def test_automatic_memory_rejects_opaque_configuration_and_model_failure(memory_run, monkeypatch):
    db, store, settings, job, _ = memory_run
    enable(settings, agent={'enabled': True, 'provider': 'openAI'})
    called = False

    async def fake(*args, **kwargs):
        nonlocal called
        called = True
        yield 'bad'

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=fake) == 0
    assert not called
    enable(settings)
    def unavailable(*args, **kwargs):
        raise ValueError('Model cannot be initialized')
    monkeypatch.setattr(memory_agent, 'provider_config', unavailable)
    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=fake) == 0
    assert not called


@pytest.mark.asyncio
async def test_automatic_memory_needs_trustworthy_memory_snapshot(memory_run, monkeypatch):
    db, store, settings, job, _ = memory_run
    enable(settings)
    monkeypatch.setattr(memory_agent.MemoryRepository, 'formatted',
                        lambda *args, **kw: {'readFailed': True})

    async def never(*args, **kwargs):
        raise AssertionError('Summary read failed')
        yield None

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=never) == 0


@pytest.mark.asyncio
async def test_automatic_memory_refuses_filtered_user_input(memory_run):
    db, store, settings, job, _ = memory_run
    enable(settings)
    settings.save_setting('alice', 'webui.filters.config', {'memories': {'pii': {
        'starterPatterns': [], 'fields': ['value'],
        'customPatterns': [{'id': 'private', 'label': 'private value', 'regex': 'PRIVATE-[A-Z]+'}],
    }}})

    async def never(*args, **kwargs):
        raise AssertionError('Blocked input cannot reach the memory model')
        yield None

    assert await memory_agent.run_automatic_memory('alice', job, db,
        [{'role': 'user', 'content': 'PRIVATE-INPUT'}], root_agent=None, stream_tools=never) == 0
    assert await memory_agent.run_automatic_memory('alice', job, db,
        [{'role': 'system', 'content': 'No user text'}], root_agent=None, stream_tools=never) == 0


@pytest.mark.asyncio
async def test_automatic_memory_agent_settings_and_model_output_guards(memory_run):
    db, store, settings, job, _ = memory_run
    settings.save_setting('alice', 'endpoints', {'memory': {
        'agent': {'enabled': True, 'provider': 'openAI', 'model': 'mock-memory',
                  'instructions': 'Custom memory instructions.'},
        'validKeys': 'bad', 'maxInputTokens': False, 'messageWindowSize': False,
    }})

    async def stream(profile, messages, **kwargs):
        assert 'Custom memory instructions.' in messages[0]['content']
        assert 'Memory Status' not in messages[0]['content']
        yield 'No memory requests'
        yield ModelToolCall('outside-tool', 'unsupported_tool', {})
        yield ModelToolCall('memory-call', 'set_memory', {'key': 'style', 'value': 'Only requested facts.'})

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=stream) == 1


@pytest.mark.asyncio
async def test_automatic_memory_grant_revoked_or_run_terminal_before_mutation(memory_run):
    db, store, settings, job, _ = memory_run
    enable(settings)

    async def before_write(*args, **kwargs):
        store.finish('alice', job.run_id, status='aborted')
        yield ModelToolCall('late-memory', 'set_memory', {'key': 'late', 'value': 'Never persist.'})

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=before_write) == 0
    assert not MemoryRepository(db).list('alice')


def test_memory_window_structured_contents_and_no_user_boundary():
    data = [
        {'role': 'assistant', 'content': 'early'},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'part A'},
                                        {'type': 'image_url', 'url': 'untrusted'},
                                        {'type': 'text', 'text': 'part B'}]},
        {'role': 'assistant', 'content': 42},
        {'role': 'assistant', 'content': 'last'},
        {'role': 'assistant', 'content': 'end'},
    ]
    result = memory_agent._memory_window(data, window_size=2, max_tokens=128)
    assert 'early' not in result and 'end' in result
    assert 'image_url' not in result
    # Without a usable user window, the source falls back to the latest N items.
    shorter = memory_agent._memory_window(data[:3], window_size=5, max_tokens=128)
    assert 'part A' in shorter and 'part B' in shorter
    assert '42' not in shorter


@pytest.mark.asyncio
async def test_memory_write_denied_after_auth_grant_expires(memory_run):
    db, store, settings, job, _ = memory_run
    enable(settings)

    async def provider(*args, **kwargs):
        yield ModelToolCall('expired', 'set_memory', {'key': 'style', 'value': 'No.'})

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=provider,
        grant_expires=int(time.time()) - 1) == 0
    assert not MemoryRepository(db).list('alice')

    class ExpiringIterator:
        async def __aiter__(self):
            from unittest.mock import patch
            with patch.object(memory_agent.time, 'time', return_value=time.time() + 100):
                yield ModelToolCall('expired-midrun', 'set_memory', {'key': 'style', 'value': 'No.'})

    async def late(*args, **kwargs):
        async for entry in ExpiringIterator():
            yield entry

    assert await memory_agent.run_automatic_memory('alice', job, db,
        store.history('alice', job.conversation_id), root_agent=None, stream_tools=late,
        grant_expires=int(time.time()) + 10) == 0
    assert not MemoryRepository(db).list('alice')
