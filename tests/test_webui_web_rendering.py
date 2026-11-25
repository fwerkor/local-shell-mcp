"""Regression tests for dynamic web reading and its public-only transport."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from local_shell_mcp.webui import web_research as web

SHELL = b'<html><head><title>Profile</title></head><body><app-root></app-root><script src="/app.js"></script></body></html>'


@pytest.fixture
def fetch_env(monkeypatch, tmp_path):
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    path = tmp_path / 'doc.json'
    monkeypatch.setattr(web, '_cache_file', lambda owner, url: path)
    return path


@pytest.mark.asyncio
async def test_dynamic_fetch_replaces_title_only_legacy_cache(monkeypatch, fetch_env):
    fetch_env.write_text(json.dumps({'title': 'Profile', 'text': 'Profile', 'sections': []}))
    calls = []

    async def download(url, **kwargs):
        calls.append('static')
        return url, 'text/html', SHELL

    async def render(url):
        calls.append('render')
        return url, web._parse_document('text/html', b'<html><title>Profile</title><h1>Works</h1><p>Public research record</p></html>', url)

    monkeypatch.setattr(web, '_download', download)
    monkeypatch.setattr(web, '_render_html', render)
    first = await web.web_fetch('owner', 'https://example.org/profile')
    assert first['cached'] is False and 'Public research record' in first['content']
    assert first['sections'][0]['heading'] == '# Works'
    second = await web.web_fetch('owner', 'https://example.org/profile')
    assert second['cached'] is True and calls == ['static', 'render']


@pytest.mark.asyncio
@pytest.mark.parametrize('mime,body', [
    ('text/html', b'<html><title>Page</title><p>OK</p></html>'),
    ('text/plain', b'hello'),
    ('text/html', b'<html><title>OK</title><p>OK</p></html>'),
])
async def test_short_readable_documents_do_not_render(monkeypatch, fetch_env, mime, body):
    async def download(url, **kwargs):
        return url, mime, body

    async def render(url):
        pytest.fail('static document must not start a browser')

    monkeypatch.setattr(web, '_download', download)
    monkeypatch.setattr(web, '_render_html', render)
    result = await web.web_fetch('owner', 'https://example.org/hello')
    assert result['content'] in {'OK', 'hello'}


@pytest.mark.asyncio
@pytest.mark.parametrize('challenge', [False, True])
async def test_invalid_documents_never_cached(monkeypatch, fetch_env, challenge):
    async def download(url, **kwargs):
        body = '<html><title>百度安全验证</title></html>'.encode() if challenge else SHELL
        return url, 'text/html', body

    async def render(url):
        assert not challenge
        return url, web._parse_document('text/html', SHELL, url)

    monkeypatch.setattr(web, '_download', download)
    monkeypatch.setattr(web, '_render_html', render)
    with pytest.raises(web.WebResearchError, match='access denied|no readable content'):
        await web.web_fetch('owner', 'https://example.org/')
    assert not fetch_env.exists()


def test_html_quality_and_title_extraction():
    url = 'https://example.org/'
    data = web._parse_document('text/html', b'<html><title>Actual title</title><svg><title>Icon</title></svg><p>Body</p></html>', url)
    assert data['title'] == 'Actual title' and data['text'] == 'Body'
    assert web._html_problem(data) is None
    assert web._html_problem(web._parse_document('text/html', b'<title>OK</title><p>OK</p>', url)) is None
    assert web._html_problem({'title': 'App', 'text': 'Please enable JavaScript to continue.'})
    assert web._html_problem({'title': 'App', 'text': 'Loading...'})
    assert web._html_problem({'title': 'Just a moment...', 'text': 'Verify'})
    assert web._html_problem({'title': 'App', 'text': 'App\nUseful content'}) is None


class Route:
    def __init__(self, url, method='GET', resource_type='script'):
        self.request = SimpleNamespace(url=url, method=method, resource_type=resource_type,
                                       headers={'accept': '*/*', 'authorization': 'secret',
                                                'x-requested-with': 'XMLHttpRequest', 'x-api-key': 'secret'})
        self.result = None

    async def abort(self):
        self.result = 'blocked'

    async def fulfill(self, **kwargs):
        self.result = kwargs


@pytest.mark.asyncio
async def test_render_routes_limit_and_validate_every_resource(monkeypatch):
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_MAX_BYTES', 10)
    monkeypatch.setattr(web, '_MAX_RENDER_REQUESTS', 3)
    requests = []

    def response(request):
        requests.append(request)
        if request.url.path == '/redirect':
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/'})
        return httpx.Response(200, headers=[('content-type', 'text/javascript'), ('set-cookie', 'a=1; Path=/'), ('set-cookie', 'b=2; Path=/')], content=b'123456')

    budget = web._RenderBudget()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        for route in (Route('http://127.0.0.1/'), Route('https://example.org/', 'POST'),
                      Route('https://example.org/', resource_type='image'),
                      Route('https://example.org/', resource_type='eventsource')):
            await budget.handle(route, client)
            assert route.result == 'blocked'
        assert not requests
        redirect = Route('https://example.org/redirect')
        await budget.handle(redirect, client)
        assert redirect.result == 'blocked'
        good = Route('https://example.org/script')
        await budget.handle(good, client)
        assert good.result['body'] == b'123456'
        assert good.result['headers']['set-cookie'] == 'a=1; Path=/\nb=2; Path=/'
        assert 'authorization' not in requests[-1].headers
        assert 'x-api-key' not in requests[-1].headers
        assert requests[-1].headers['x-requested-with'] == 'XMLHttpRequest'
        exhausted = Route('https://example.org/other')
        await budget.handle(exhausted, client)
        assert exhausted.result == 'blocked' and budget.exhausted


@pytest.mark.asyncio
async def test_render_byte_budget_and_read_only_network_errors(monkeypatch):
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_MAX_BYTES', 3)

    def response(request):
        if request.url.path == '/error':
            raise httpx.ConnectError('closed', request=request)
        return httpx.Response(200, content=b'1234')

    budget = web._RenderBudget()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        failed = Route('https://example.org/error')
        await budget.handle(failed, client)
        assert failed.result == 'blocked' and not budget.exhausted
        big = Route('https://example.org/large')
        await budget.handle(big, client)
        assert big.result == 'blocked' and budget.exhausted


@pytest.mark.asyncio
async def test_real_browser_renders_script_without_private_network(monkeypatch):
    api = pytest.importorskip('playwright.async_api')
    async with api.async_playwright() as playwright:
        from pathlib import Path
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip('Chromium not installed')
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_RENDER_SETTLE', 0.3)
    seen = []
    private_connections = []

    def connected(reader, writer):
        private_connections.append(True)
        writer.close()

    listener = await asyncio.start_server(connected, '127.0.0.1', 0)
    async with listener:
        port = listener.sockets[0].getsockname()[1]

        async def response(request):
            seen.append(str(request.url))
            if request.url.path == '/app.js':
                return httpx.Response(200, headers={'content-type': 'text/javascript'}, text=(
                    "document.querySelector('app-root').textContent='Loading profile…';fetch('/data').then(r=>r.text()).then(t=>document.querySelector('app-root').textContent=t);"
                    f"fetch('http://127.0.0.1:{port}/secret').catch(()=>{{}});"
                    f"new WebSocket('ws://127.0.0.1:{port}/secret');"
                ))
            if request.url.path == '/data':
                await asyncio.sleep(1.2)
                return httpx.Response(200, text='Readable dynamic profile')
            return httpx.Response(200, headers={'content-type': 'text/html'}, content=SHELL)

        monkeypatch.setattr(web, '_PublicHTTPTransport', lambda: httpx.MockTransport(response))
        url, doc = await web._render_html('https://example.org/')
        assert url == 'https://example.org/' and doc['text'] == 'Readable dynamic profile'
        assert seen == ['https://example.org/', 'https://example.org/app.js', 'https://example.org/data']
        assert not private_connections


@pytest.mark.asyncio
@pytest.mark.parametrize('status,detail', [(401, 'authentication required'), (403, 'denied automated access'), (429, 'rate limiting')])
async def test_http_denial_is_explicit_and_never_rendered(monkeypatch, fetch_env, status, detail):
    monkeypatch.setattr(web, '_PublicHTTPTransport', lambda: httpx.MockTransport(
        lambda request: httpx.Response(status, content=b'denied')))

    async def render(url):
        pytest.fail('access denial must not trigger browser rendering')

    monkeypatch.setattr(web, '_render_html', render)
    with pytest.raises(web.WebResearchError, match=detail):
        await web.web_fetch('owner', 'https://example.org/')
    assert not fetch_env.exists()


@pytest.mark.asyncio
async def test_missing_browser_dependency_has_actionable_error(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, 'playwright.async_api', None)
    with pytest.raises(web.WebResearchError, match='install the browser extra'):
        await web._render_html('https://example.org/')


@pytest.mark.asyncio
async def test_dynamic_render_deadline(monkeypatch):
    pytest.importorskip('playwright.async_api')
    monkeypatch.setattr(web, '_RENDER_DEADLINE', 0.01)

    async def slow_proxy(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(web.asyncio, 'start_server', slow_proxy)
    with pytest.raises(web.WebResearchError, match='timed out'):
        await web._render_html('https://example.org/')


@pytest.mark.asyncio
async def test_render_skips_event_stream_without_consuming_it(monkeypatch):
    monkeypatch.setattr(web, '_public_address', lambda host: True)

    class PersistentStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail('persistent event stream must not be buffered')
            yield b'event: update'

    def response(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream; charset=utf-8'},
                              stream=PersistentStream())

    budget = web._RenderBudget()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        route = Route('https://example.org/events', resource_type='fetch')
        await budget.handle(route, client)
        assert route.result == 'blocked'
        assert not budget.exhausted and budget.bytes == 0
