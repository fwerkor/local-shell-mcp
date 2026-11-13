"""Automatic Memory Agent through actual loopback OpenAI SSE and SQLite replay."""
from __future__ import annotations

import asyncio
import json
import socket

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import memory_agent
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.memory import MemoryRepository
from local_shell_mcp.webui.providers import ProviderConfig, stream_model_with_tools
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.mark.asyncio
async def test_auto_memory_uses_real_sse_provider_and_replays_attachment(tmp_path, monkeypatch):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    received = []

    async def completion(request):
        body = await request.json()
        received.append(body)
        assert request.headers.get('authorization') == 'Bearer memory-test-key'
        assert body['model'] == 'memory-test'
        assert body['tool_choice'] == 'auto'
        assert {item['function']['name'] for item in body['tools']} == {
            'set_memory', 'delete_memory'}
        assert '# Current Chat:' in body['messages'][-1]['content']
        arguments = json.dumps({'key': 'style', 'value': 'The user prefers short replies.'})

        async def stream():
            for event in [
                {'choices': [{'delta': {'tool_calls': [{
                    'index': 0, 'id': 'call-real', 'function': {
                        'name': 'set_', 'arguments': arguments[:20]},
                }]}}]},
                {'choices': [{'delta': {'tool_calls': [{
                    'index': 0, 'function': {
                        'name': 'memory', 'arguments': arguments[20:]},
                }]}}]},
            ]:
                yield 'data: ' + json.dumps(event) + '\n\n'
                await asyncio.sleep(0)
            yield 'data: [DONE]\n\n'

        return StreamingResponse(stream(), media_type='text/event-stream')

    server = uvicorn.Server(uvicorn.Config(
        Starlette(routes=[Route('/v1/chat/completions', completion, methods=['POST'])]),
        host='127.0.0.1', port=port, access_log=False, log_level='error'))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        db = SQLiteDatabase(tmp_path / '.local-shell-mcp')
        settings = WorkspaceRepository(db)
        settings.save_setting('local', 'endpoints', {'memory': {
            'agent': {'enabled': True, 'provider': 'openAI', 'model': 'memory-test'},
            'tokenLimit': 50,
        }})
        store = GenerationStore(db)
        generation, _ = store.begin('local', {'text': 'Please remember I prefer short replies.'})
        monkeypatch.setattr(memory_agent, 'provider_config', lambda *a, **kw:
            ProviderConfig('openai', 'memory-test',
                           f'http://127.0.0.1:{port}/v1/chat/completions', 'memory-test-key'))
        assert await memory_agent.run_automatic_memory(
            'local', generation, db, store.history('local', generation.conversation_id),
            root_agent=None, stream_tools=stream_model_with_tools) == 1
        assert len(received) == 1
        assert MemoryRepository(SQLiteDatabase(db.root)).list('local', '')[0]['key'] == 'style'
        attachments = [event['data'] for _, event in store.events('local', generation.run_id)
                       if event.get('event') == 'attachment']
        assert len(attachments) == 1
        assert attachments[0]['toolCallId'] == 'call-real'
        assert attachments[0]['memory']['type'] == 'update'
        assert store.finish('local', generation.run_id, status='complete', text='Saved')
    finally:
        server.should_exit = True
        await task
