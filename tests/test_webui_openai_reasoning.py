"""Reasoning must survive OpenAI-compatible streams, SSE replay and history."""

from __future__ import annotations

import json

import httpx
import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.conversation_titles import PROMPT as TITLE_PROMPT
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import (
    ModelThought,
    ModelToolCall,
    ProviderConfig,
    stream_model,
    stream_model_with_tools,
)


def _sse(monkeypatch, events):
    original = httpx.AsyncClient

    def handler(request):
        frames = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events)
        return httpx.Response(200, text=frames + 'data: [DONE]\n\n',
                              headers={'content-type': 'text/event-stream'})

    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize('with_tools', [False, True])
async def test_openai_compatible_reasoning_is_streamed_separately(monkeypatch, with_tools):
    _sse(monkeypatch, [
        {'choices': [{'delta': {'reasoning_content': 'Let me '}}]},
        {'choices': [{'delta': {'reasoning_content': 'check.', 'content': 'The '}}]},
        {'choices': [{'delta': {'reasoning': 'Second thought.'}}]},
        {'choices': [{'delta': {'reasoning_details': [
            {'type': 'reasoning.text', 'text': ' More detail.'},
            {'type': 'reasoning.encrypted', 'data': 'do-not-display'},
        ]}}]},
        {'choices': [{'delta': {'content': 'answer.'}}]},
    ])
    config = ProviderConfig('openai', 'compatible', 'https://provider.test/chat/completions', 'secret')
    messages = [{'role': 'user', 'content': 'question'}]
    if with_tools:
        output = [item async for item in stream_model_with_tools(
            config, messages, tools=[{'type': 'function', 'function': {'name': 'read'}}])]
    else:
        output = [item async for item in stream_model(config, messages)]
    assert output == [
        ModelThought('thinking', text='Let me '),
        ModelThought('thinking', text='check.'),
        'The ',
        ModelThought('thinking', text='Second thought.'),
        ModelThought('thinking', text=' More detail.'),
        'answer.',
    ]


@pytest.mark.asyncio
async def test_openai_tool_call_and_reasoning_can_share_a_delta(monkeypatch):
    _sse(monkeypatch, [
        {'choices': [{'delta': {'reasoning_content': 'Need to read a file.', 'tool_calls': [
            {'index': 0, 'id': 'call-1', 'function': {'name': 'file_read', 'arguments': '{"path":'}},
        ]}}]},
        {'choices': [{'delta': {'tool_calls': [
            {'index': 0, 'function': {'arguments': '"a.txt"}'}},
        ]}}]},
    ])
    config = ProviderConfig('openai', 'compatible', 'https://provider.test/chat/completions', 'secret')
    output = [item async for item in stream_model_with_tools(
        config, [{'role': 'user', 'content': 'read'}], tools=[{'type': 'function'}])]
    assert output == [ModelThought('thinking', text='Need to read a file.'),
                      ModelToolCall('call-1', 'file_read', {'path': 'a.txt'})]


@pytest.mark.asyncio
@pytest.mark.parametrize('segments', [
    [('think', 'Reason '), ('think', 'first.'), ('text', 'Final answer.')],
    [('text', 'First text.'), ('think', 'Later reasoning.'), ('text', 'Final answer.')],
    [('think', 'Only reasoning.')],
])
async def test_generation_reasoning_visible_during_stream_and_after_reconnect(
    tmp_path, monkeypatch, segments,
):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    try:
        store = GenerationStore(shared_database(get_settings().state_dir))
        generation, _ = store.begin('local', {'text': 'Explain briefly'})

        async def provider(*args, **kwargs):
            for kind, chunk in segments:
                yield ModelThought('thinking', text=chunk) if kind == 'think' else chunk

        monkeypatch.setattr(generation_routes, 'stream_model', provider)
        monkeypatch.setattr(generation_routes, 'stream_model_with_tools', provider)
        profile = ProviderConfig('openai', 'reasoning-test', 'https://provider.test/v1', 'secret')
        await generation_routes._run_model('local', generation, profile)

        expected = []
        for kind, value in segments:
            part_type = 'think' if kind == 'think' else 'text'
            part_key = 'think' if kind == 'think' else 'text'
            if expected and expected[-1]['type'] == part_type:
                expected[-1][part_key] += value
            else:
                expected.append({'type': part_type, part_key: value,
                                 **({'phase': 'final_answer'} if kind == 'text' else {})})

        assert store.latest('local', generation.conversation_id).status == 'complete'
        events = [event for _, event in store.events('local', generation.run_id)]
        assert sum(event.get('event') == 'on_reasoning_delta' for event in events) == sum(
            kind == 'think' for kind, _ in segments)
        assert all(event.get('data', {}).get('delta', {}).get('content', {}).get('type') == 'think'
                   for event in events if event.get('event') == 'on_reasoning_delta')
        snapshot, _ = store.resume_snapshot('local', generation.run_id)
        # The resumable stream retains individual text/thought slots, even if
        # no answer text has been emitted yet.
        assert [part for part in snapshot['aggregatedContent'] if
                part.get('type') != 'text' or part.get('text')] == expected
        final = next(event['responseMessage'] for event in reversed(events)
                     if 'responseMessage' in event)
        assert final['content'] == expected
        assert final['text'] == ''.join(chunk for kind, chunk in segments if kind == 'text')
        with store.database.connect() as db:
            persisted = db.execute('SELECT content FROM messages WHERE id=?',
                                   (generation.response_message_id,)).fetchone()
        assert json.loads(persisted['content']) == expected
        history = store.history('local', generation.conversation_id)
        assistant = [message for message in history if message['role'] == 'assistant'][-1]
        assert ''.join(part['thinking'] for part in assistant.get('reasoning', [])
                       if part['type'] == 'thinking') == ''.join(
                           chunk for kind, chunk in segments if kind == 'think')
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_visible_prose_remains_between_reasoning_and_tool_rounds(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    monkeypatch.setattr('local_shell_mcp.webui.machine_permissions._registered_defaults',
                        lambda: {'local': 'write'})
    get_settings.cache_clear()
    try:
        store = GenerationStore(shared_database(get_settings().state_dir))
        generation, _ = store.begin('local', {'text': 'Check twice'})
        round_count = 0
        snapshots = []

        async def provider(*args, **kwargs):
            nonlocal round_count
            if args[1] and args[1][0].get("content") == TITLE_PROMPT:
                yield "Recovered task"
                return
            round_count += 1
            if round_count > 1:
                snapshots.append(store.resume_snapshot('local', generation.run_id)[0]['aggregatedContent'])
            yield ModelThought('thinking', text=f'Thought {round_count}')
            yield f'Visible {round_count}.'
            if round_count < 3:
                yield ModelToolCall(f'call-{round_count}', 'file_list', {'path': '.'})

        monkeypatch.setattr(generation_routes, 'stream_model', provider)
        monkeypatch.setattr(generation_routes, 'stream_model_with_tools', provider)
        profile = ProviderConfig('openai', 'reasoning-test', 'https://provider.test/v1', 'secret')
        await generation_routes._run_model('local', generation, profile, mcp_enabled=True,
                                           granted_scopes=frozenset({'shell:read', 'shell:write'}))
        assert store.latest('local', generation.conversation_id).status == 'complete', store.events('local', generation.run_id)[-1]
        assert round_count == 3

        def sequence(parts):
            return [(p['type'], p.get('text') or p.get('think') or p.get('tool_call', {}).get('id'))
                    for p in parts if p.get('text') or p.get('think') or p.get('tool_call')]

        expected = [('think', 'Thought 1'), ('text', 'Visible 1.'), ('tool_call', 'call-1'),
                    ('think', 'Thought 2'), ('text', 'Visible 2.'), ('tool_call', 'call-2'),
                    ('think', 'Thought 3'), ('text', 'Visible 3.')]
        assert sequence(snapshots[0]) == expected[:3]
        assert sequence(snapshots[1]) == expected[:6]
        snapshot, _ = store.resume_snapshot('local', generation.run_id)
        assert sequence(snapshot['aggregatedContent']) == expected
        events = [event for _, event in store.events('local', generation.run_id)]
        final = next(event['responseMessage'] for event in reversed(events) if 'responseMessage' in event)
        assert sequence(final['content']) == expected
        assert final['text'] == 'Visible 1.Visible 2.Visible 3.'
        with store.database.connect() as db:
            saved = db.execute('SELECT content FROM messages WHERE id=?',
                               (generation.response_message_id,)).fetchone()
        assert sequence(json.loads(saved['content'])) == expected
    finally:
        get_settings.cache_clear()
