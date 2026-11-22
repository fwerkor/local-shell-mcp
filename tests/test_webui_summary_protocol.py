"""Real HTTP/SSE summarizer, durable resume and original React continuation."""
from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.storage import WorkspaceRepository


def _port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


@pytest.mark.asyncio
async def test_compaction_with_actual_openai_sse_and_browser_continue(tmp_path, monkeypatch):
    """No summary is fabricated: model response crosses a real loopback HTTP port."""
    playwright = pytest.importorskip('playwright.async_api')
    model_port = _port()
    server_port = _port()
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    monkeypatch.setenv('LOCAL_SHELL_MCP_UI_ENABLED', 'true')
    monkeypatch.setenv('LOCAL_SHELL_MCP_REMOTE_ENABLED', 'false')
    monkeypatch.setenv('LOCAL_SHELL_MCP_MODEL_BASE_URL', f'http://127.0.0.1:{model_port}/v1')
    monkeypatch.setenv('LOCAL_SHELL_MCP_MODEL_API_KEY', 'test-private-key')
    monkeypatch.setenv('LOCAL_SHELL_MCP_MODEL', 'mock-test-model')
    get_settings.cache_clear()

    received = []

    async def model_response(request):
        body = await request.json()
        received.append(body)
        assert request.headers.get('authorization') == 'Bearer test-private-key'
        assert body['model'] == 'mock-test-model'
        is_summary = 'checkpoint' in body['messages'][-1]['content'].lower()
        answer = ('## Checkpoint\n## Goal\nKeep context from earlier exchanges.'
                  if is_summary else 'The model continued after the summary.')
        # Emit independently framed SSE chunks to exercise the actual provider adapter.
        async def stream():
            import json
            for piece in (answer[:20], answer[20:]):
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': piece}}]}) + '\n\n'
                await asyncio.sleep(0)
            yield 'data: [DONE]\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream')

    model = uvicorn.Server(uvicorn.Config(
        Starlette(routes=[Route('/v1/chat/completions', model_response, methods=['POST'])]),
        host='127.0.0.1', port=model_port, log_level='error', access_log=False))
    web = uvicorn.Server(uvicorn.Config(_with_oauth_routes(Starlette()), host='127.0.0.1',
                                        port=server_port, log_level='error', access_log=False))
    tasks = [asyncio.create_task(model.serve()), asyncio.create_task(web.serve())]
    browser = None
    try:
        for _ in range(200):
            if model.started and web.started:
                break
            await asyncio.sleep(.05)
        assert model.started and web.started
        database = shared_database(get_settings().state_dir.resolve())
        repo = WorkspaceRepository(database)
        repo.save_setting('local', 'endpoints', {'summarization': {'enabled': True}})
        store = GenerationStore(database)
        parent = None
        cid = None
        for index in range(4):
            body = {'text': f'Historical user prompt {index}.'}
            if cid is not None:
                body.update({'conversationId': cid, 'parentMessageId': parent})
            job, fresh = store.begin('local', body)
            assert fresh
            assert store.finish('local', job.run_id, status='complete', text=f'Historical answer {index}.')
            cid, parent = job.conversation_id, job.response_message_id
        with database.connect() as connection:
            count_before = connection.execute('SELECT count(*) FROM messages WHERE conversation_id=?',
                                              (cid,)).fetchone()[0]
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{server_port}') as http:
            response = await http.post('/api/agents/chat', json={
                'compact': True, 'conversationId': cid, 'parentMessageId': parent,
                'provider': 'openAI', 'model': 'mock-test-model',
            })
            assert response.status_code == 202, response.text
            for _ in range(200):
                run = store.latest('local', cid)
                if run and run.status not in {'running', 'requires_action'}:
                    break
                await asyncio.sleep(.05)
            assert run and run.status == 'complete'
            history = store.history('local', cid)
            assert len(history) == 1, history
            assert history[0]['role'] == 'system'
            assert 'Keep context from earlier exchanges' in history[0]['content']
            assert len(received) == 1
            assert 'Historical user prompt 0.' in str(received[0]['messages'])
            assert 'checkpoint' in received[0]['messages'][-1]['content'].lower()
            with database.connect() as connection:
                count_after = connection.execute('SELECT count(*) FROM messages WHERE conversation_id=?',
                                                 (cid,)).fetchone()[0]
            assert count_after == count_before + 1  # compaction created no dummy user message

            async with playwright.async_playwright() as manager:
                try:
                    browser = await manager.chromium.launch(headless=True)
                except playwright.Error as exc:
                    if "Executable doesn't exist" in str(exc):
                        pytest.skip('Chromium is not installed')
                    raise
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                await page.goto(f'http://127.0.0.1:{server_port}/c/{cid}',
                                wait_until='domcontentloaded')
                await page.get_by_test_id('text-input').fill('Please continue now.')
                await page.locator('button[type="submit"]').first.click()
                await page.get_by_text('The model continued after the summary.', exact=True).first.wait_for(timeout=15000)
                assert not errors, errors
                assert len(received) >= 2
                continued = received[-1]['messages']
                assert any('<summary>' in item.get('content', '') for item in continued
                           if isinstance(item.get('content'), str))
                assert not any('Historical user prompt 0.' in str(item) for item in continued)
                await page.reload()
                try:
                    await page.get_by_text('The model continued after the summary.', exact=True).first.wait_for(timeout=15000)
                except Exception:
                    print('BROWSER TEXT:', (await page.locator('body').inner_text())[:3000])
                    print('MODEL REQUESTS:', [(x.get('model'), str(x.get('messages', []))[:700]) for x in received])
                    with database.connect() as conn:
                        print('RUNS:', [tuple(row) for row in conn.execute('SELECT status,state FROM runs ORDER BY updated_at DESC LIMIT 2')])
                    raise
    finally:
        if browser is not None:
            await browser.close()
        model.should_exit = web.should_exit = True
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
        get_settings.cache_clear()
