"""Real React Chromium: graph child Ask User survives refresh and SSE resume."""
from __future__ import annotations

import asyncio
import json
import re
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner, generation_routes
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.mark.asyncio
async def test_original_react_direct_graph_child_human_resume_after_reload(tmp_path, monkeypatch):
    pytest.importorskip('langgraph')
    playwright = pytest.importorskip('playwright.async_api')
    import uvicorn

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    monkeypatch.setenv('LOCAL_SHELL_MCP_UI_ENABLED', 'true')
    monkeypatch.setenv('LOCAL_SHELL_MCP_REMOTE_ENABLED', 'false')
    monkeypatch.setenv('LOCAL_SHELL_MCP_MODEL_BASE_URL', 'http://127.0.0.1:11434/v1')
    monkeypatch.setenv('LOCAL_SHELL_MCP_MODEL', 'graph-root')
    get_settings.cache_clear()
    db = shared_database(get_settings().state_dir)
    repo = AgentRepository(db)
    root = repo.create('local', {'name': 'Graph root', 'provider': 'openAI',
                                 'model': 'graph-root', 'tools': ['ask_user_question']})
    child = repo.create('local', {'name': 'Graph child', 'provider': 'openAI',
                                  'model': 'graph-child', 'tools': ['ask_user_question']})
    root = repo.update('local', root['id'], {'edges': [
        {'from': root['id'], 'to': child['id'], 'edgeType': 'direct'}]})
    profile = lambda _provider, model=None: ProviderConfig(  # noqa: E731
        'openai', model or 'graph-root', 'http://127.0.0.1:11434/v1/chat/completions', '')
    monkeypatch.setattr(agent_runner, 'provider_config', profile)
    monkeypatch.setattr(generation_routes, 'provider_config', profile)
    seen = []

    async def model(provider, messages, **kwargs):
        seen.append((provider.model, messages))
        if provider.model == 'graph-root':
            yield 'Root prepared the graph handoff.'
        elif not any(m.get('role') == 'tool' for m in messages):
            yield ModelToolCall('graph-ask', 'ask_user_question', {'questions': [
                {'id': 'format', 'header': 'Format', 'question': 'Which output format?',
                 'options': [{'label': 'Markdown', 'value': 'markdown'},
                             {'label': 'JSON', 'value': 'json'}]},
            ]})
        else:
            assert json.loads(messages[-1]['content']) == {'answers': {'format': 'markdown'}}
            yield 'Graph child received Markdown answer.'

    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', model)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_with_oauth_routes(Starlette()),
        host='127.0.0.1', port=port, lifespan='on', log_level='error', access_log=False))
    task = asyncio.create_task(server.serve())
    browser = None
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                raise RuntimeError('Graph browser server stopped unexpectedly')
            await asyncio.sleep(0.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            try:
                browser = await manager.chromium.launch(headless=True)
            except playwright.Error as exc:
                if 'Executable doesn\'t exist' in str(exc):
                    pytest.skip('Chromium required by source React browser acceptance')
                raise
            page = await browser.new_page()
            errors, submissions = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: submissions.append(request.post_data_json)
                    if '/api/agents/chat/resume' in request.url and request.method == 'POST' else None)
            convo = await page.request.post(f'http://127.0.0.1:{port}/api/convos', data={
                'title': 'Graph ask user', 'endpoint': 'agents',
                'agent_id': root['id'], 'model': 'graph-root',
            })
            assert convo.status == 201, await convo.text()
            cid = (await convo.json())['conversationId']
            await page.goto(f'http://127.0.0.1:{port}/c/{cid}', wait_until='domcontentloaded')
            await page.locator('textarea').first.wait_for(timeout=12000)
            await page.locator('textarea').first.fill('Complete the graph task.')
            await page.locator('button[type="submit"]').first.click()
            await page.get_by_role('button', name='Markdown', exact=True).first.wait_for(timeout=20000)
            status = (await (await page.request.get(
                f'http://127.0.0.1:{port}/api/agents/chat/status/{cid}')).json())
            assert status['pendingAction']['namespace'].endswith('/graph:' + child['id'])
            await page.reload(wait_until='domcontentloaded')
            await page.get_by_role('button', name='Markdown', exact=True).first.wait_for(timeout=12000)
            await page.get_by_role('button', name='Markdown', exact=True).first.click()
            await page.get_by_role('button', name=re.compile(r'^(Submit|提交)$')).first.click()
            try:
                await page.get_by_text('Graph child received Markdown answer.', exact=False).first.wait_for(timeout=12000)
            except playwright.Error as exc:
                snapshot = (await (await page.request.get(
                    f'http://127.0.0.1:{port}/api/agents/chat/status/{cid}')).json())
                raise AssertionError({'status': snapshot, 'seen': seen,
                                      'submissions': submissions, 'errors': errors,
                                      'body': (await page.locator('body').inner_text())[-3500:]}) from exc
            assert len(submissions) == 1
            assert submissions[0]['actionId'] == status['pendingAction']['actionId']
            assert submissions[0]['answers'] == {'format': 'markdown'}
            await page.reload(wait_until='domcontentloaded')
            await page.get_by_text('Graph child received Markdown answer.', exact=False).first.wait_for(timeout=15000)
            assert [model for model, _ in seen] == ['graph-root', 'graph-child', 'graph-child']
            assert not errors, errors
    finally:
        if browser:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(task, 15)
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()
