"""Failure, fallback, and cache edges for the WebUI's two web tools."""
from __future__ import annotations

import json
import socket
import sys
import time
from types import SimpleNamespace

import httpx
import pytest

from local_shell_mcp.webui import web_research as web


def test_public_dns_and_url_validation(monkeypatch):
    monkeypatch.setattr(web.socket, 'getaddrinfo', lambda *a, **kw: [(None, None, None, None, ('8.8.8.8', 0))])
    assert web._public_address('example.org')
    assert web._safe_url('HTTPS://example.org?q=a#anchor') == 'https://example.org/?q=a'
    assert web._arxiv_fulltext('https://www.arxiv.org/abs/2502.09992') == 'https://arxiv.org/html/2502.09992'
    assert web._arxiv_fulltext('https://example.org/abs/2502.09992') == 'https://example.org/abs/2502.09992'
    monkeypatch.setattr(web.socket, 'getaddrinfo', lambda *a, **kw: [(None, None, None, None, ('10.0.0.1', 0))])
    assert not web._public_address('internal.example.org')
    monkeypatch.setattr(web.socket, 'getaddrinfo', lambda *a, **kw: (_ for _ in ()).throw(socket.gaierror()))
    assert not web._public_address('missing.example.org')
    for malformed in ('https://[broken', 'https://example.org:invalid', 'https://' + 'a' * 2100):
        with pytest.raises(web.WebResearchError):
            web._safe_url(malformed)
    with pytest.raises(web.WebResearchError):
        web._safe_url(17)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,message', [
    ('success', None),
    ('redirect', None),
    ('missing_redirect', 'Redirect has no Location'),
    ('redirect_loop', 'Too many redirects'),
    ('server_error', 'HTTP 503'),
    ('network_error', 'Unable to fetch URL'),
    ('unsupported', 'Unsupported document content type'),
    ('oversized', 'download limit'),
])
async def test_bounded_http_fetch_paths(monkeypatch, kind, message):
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if kind == 'redirect':
            if request.url.path == '/start':
                return httpx.Response(301, headers={'Location': '/end'})
            return httpx.Response(200, headers={'Content-Type': 'text/plain'}, content=b'document text')
        if kind == 'missing_redirect':
            return httpx.Response(302)
        if kind == 'redirect_loop':
            return httpx.Response(307, headers={'Location': '/forever'})
        if kind == 'server_error':
            return httpx.Response(503, content=b'failure')
        if kind == 'network_error':
            raise httpx.ConnectError('connection closed', request=request)
        if kind == 'unsupported':
            return httpx.Response(200, headers={'Content-Type': 'image/png'}, content=b'png')
        if kind == 'oversized':
            return httpx.Response(200, content=b'x' * 300)
        return httpx.Response(200, headers={'Content-Type': 'text/plain; charset=utf8'}, content=b'ok')

    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    url = 'https://example.org/start' if kind == 'redirect' else 'https://example.org/forever'
    if message:
        with pytest.raises(web.WebResearchError, match=message):
            await web._download(url, max_bytes=100)
    else:
        resolved, mime, body = await web._download(url, max_bytes=100)
        assert resolved.endswith('/end' if kind == 'redirect' else '/forever')
        assert mime.startswith('text/') and body in {b'ok', b'document text'}
    assert requests


def test_pdf_pypdf_fallback_and_failures(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pymupdf', None)

    class Reader:
        def __init__(self, *args, **kwargs):
            self.pages = [SimpleNamespace(extract_text=lambda **kwargs: 'First page'),
                          SimpleNamespace(extract_text=lambda **kwargs: 'Second page')]

    monkeypatch.setitem(sys.modules, 'pypdf', SimpleNamespace(PdfReader=Reader))
    pdf = web._parse_document('application/pdf', b'%PDF-1.5', 'https://example.org/a.pdf')
    assert pdf['pages'] == 2 and '[Page 2]' in pdf['text']
    monkeypatch.setitem(sys.modules, 'pypdf', None)
    with pytest.raises(web.WebResearchError, match='requires pypdf'):
        web._parse_document('application/pdf', b'%PDF-1.5', 'https://example.org/a.pdf')


def test_pdf_parser_limit_and_errors(monkeypatch):
    class Document:
        def __init__(self, *, pages=1, broken=False):
            self.pages = pages
            self.broken = broken
        def __len__(self):
            return self.pages
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def __iter__(self):
            if self.broken:
                raise RuntimeError('bad page')
            yield SimpleNamespace(get_text=lambda **kwargs: 'long contents')

    monkeypatch.setitem(sys.modules, 'pymupdf', SimpleNamespace(open=lambda **kw: Document(pages=501)))
    with pytest.raises(web.WebResearchError, match='500 page'):
        web._parse_document('application/pdf', b'%PDF-1', 'https://example.org/a.pdf')
    monkeypatch.setitem(sys.modules, 'pymupdf', SimpleNamespace(open=lambda **kw: Document(broken=True)))
    with pytest.raises(web.WebResearchError, match='Unable to parse PDF'):
        web._parse_document('application/pdf', b'%PDF-1', 'https://example.org/a.pdf')
    monkeypatch.setitem(sys.modules, 'pymupdf', SimpleNamespace(open=lambda **kw: Document()))
    monkeypatch.setattr(web, '_MAX_TEXT', 5)
    with pytest.raises(web.WebResearchError, match='3 MiB text limit'):
        web._parse_document('application/pdf', b'%PDF-1', 'https://example.org/a.pdf')
    with pytest.raises(web.WebResearchError, match='3 MiB text limit'):
        web._parse_document('text/plain', b'long plain text', 'https://example.org/readme')


def test_pypdf_fallback_error_paths(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pymupdf', None)

    class TooMany:
        def __init__(self, *args, **kwargs):
            self.pages = [None] * 501

    monkeypatch.setitem(sys.modules, 'pypdf', SimpleNamespace(PdfReader=TooMany))
    with pytest.raises(web.WebResearchError, match='500 page'):
        web._parse_document('application/pdf', b'%PDF-1', 'https://example.org/a.pdf')
    monkeypatch.setitem(sys.modules, 'pypdf', SimpleNamespace(PdfReader=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('bad'))))
    with pytest.raises(web.WebResearchError, match='Unable to parse PDF'):
        web._parse_document('application/pdf', b'%PDF-1', 'https://example.org/a.pdf')


def test_private_cache_directory_lifetime_and_eviction(monkeypatch, tmp_path):
    monkeypatch.setattr('local_shell_mcp.settings.get_settings', lambda: SimpleNamespace(state_dir=tmp_path))
    alice = web._cache_file('alice', 'https://example.org/')
    bob = web._cache_file('bob', 'https://example.org/')
    assert alice != bob and alice.parent.is_dir()
    assert web._load_cache(alice) is None
    web._store_cache(alice, {'text': 'hello'})
    assert web._load_cache(alice)['text'] == 'hello'
    alice.write_text('{invalid}', encoding='utf-8')
    assert web._load_cache(alice) is None
    alice.write_text(json.dumps({'wrong': True}), encoding='utf-8')
    assert web._load_cache(alice) is None
    web._store_cache(alice, {'text': 'hello again'})
    age = time.time() - web._CACHE_TTL - 10
    import os
    os.utime(alice, (age, age))
    assert web._load_cache(alice) is None
    for index in range(web._MAX_CACHE_FILES + 5):
        web._store_cache(alice.parent / f'{index:03}.json', {'text': str(index)})
    assert len(list(alice.parent.glob('*.json'))) == web._MAX_CACHE_FILES


@pytest.mark.asyncio
async def test_ddgs_results_deduplication_and_service_fallback(monkeypatch):
    class DDGS:
        def __init__(self, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def text(self, query, **kw):
            return [
                {'href': 'https://arxiv.org/abs/2502.09992', 'title': 'Paper', 'body': 'A paper'},
                {'href': 'https://arxiv.org/abs/2502.09992', 'title': 'Duplicate'},
                {'href': 'ftp://example.org/data', 'title': 'Unsupported'},
                {'href': 'https://example.org/other', 'title': 'Other'},
            ]
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=DDGS))
    results = await web.web_search('diffusion')
    assert len(results['results']) == 2

    class Broken(DDGS):
        def text(self, query, **kw):
            raise RuntimeError('rate limited')
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=Broken))
    async def rss(url, **kwargs):
        return url, 'application/rss+xml', b'<rss><channel><item><title>OpenAI news</title><link>https://openai.com/</link><description>OpenAI updates</description></item></channel></rss>'
    monkeypatch.setattr(web, '_download', rss)
    fallback = await web.web_search('OpenAI')
    assert fallback['results'][0]['url'] == 'https://openai.com/'


@pytest.mark.asyncio
async def test_search_rss_malformed_relevance_site_empty_and_cap(monkeypatch):
    monkeypatch.setitem(sys.modules, 'ddgs', None)
    async def bad_xml(url, **kwargs):
        return url, 'text/xml', b'<<bad-xml'
    monkeypatch.setattr(web, '_download', bad_xml)
    with pytest.raises(web.WebResearchError, match='invalid response'):
        await web.web_search('example')

    async def rss(url, **kw):
        entries = [
            '<item><title>Offsite wrong</title><link>https://example.com/</link><description>diffusion language model</description></item>',
            '<item><title>Not relevant</title><link>https://arxiv.org/abs/1</link><description>nothing</description></item>',
            '<item><title>Bad</title><link>ftp://arxiv.org/abs/2</link></item>',
            '<item><title>No URL</title></item>',
        ]
        for index in range(13):
            entries.append(f'<item><title>diffusion language {index}</title><link>https://arxiv.org/abs/{index+100}</link><description>model</description></item>')
        return url, 'application/rss+xml', ('<rss><channel>' + ''.join(entries) + '</channel></rss>').encode()
    monkeypatch.setattr(web, '_download', rss)
    results = await web.web_search('site:arxiv.org diffusion language model')
    assert len(results['results']) == 10
    assert all('arxiv.org' in row['url'] for row in results['results'])

    async def empty(url, **kw):
        return url, 'application/rss+xml', b'<rss><channel/></rss>'
    monkeypatch.setattr(web, '_download', empty)
    assert (await web.web_search('site:arxiv.org diffusion'))['results'] == []


@pytest.mark.asyncio
async def test_fetch_invalid_arguments_missing_query_and_page_markers(monkeypatch, tmp_path):
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_cache_file', lambda owner, url: tmp_path / 'paper.json')
    async def download(url, **kw):
        return url, 'text/plain', b'Alpha\nMethod content\nConclusion'
    monkeypatch.setattr(web, '_download', download)
    for argument in ({'offset': -1}, {'offset': True}, {'limit': 10}, {'limit': 15000},
                     {'query': 23}, {'query': 'a' * 201}):
        with pytest.raises(web.WebResearchError):
            await web.web_fetch('alice', 'https://example.org/article', **argument)
    with pytest.raises(web.WebResearchError, match='query cannot be empty'):
        await web.web_fetch('alice', 'https://example.org/article', query=' ')
    assert (await web.web_fetch('alice', 'https://example.org/article', query='missing'))['found'] is False
    bad_page = {'url': 'https://example.org/a.pdf', 'title': 'PDF', 'pages': 2,
                'text': '[Page 1]\nAlpha\n[Page 2]\nBeta',
                'sections': [{'page': 1, 'offset': 0}, {'page': 2, 'offset': 16}]}
    web._store_cache(tmp_path / 'paper.json', bad_page)
    matched = await web.web_fetch('alice', 'https://example.org/article', query='Beta', limit=150)
    assert matched['page'] == 1  # query adds context that begins on the previous page
    tail = await web.web_fetch('alice', 'https://example.org/article', offset=20, limit=100)
    assert tail['page'] == 2


@pytest.mark.asyncio
async def test_non_arxiv_fetch_failure_and_dispatch_arguments(monkeypatch, tmp_path):
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_cache_file', lambda owner, url: tmp_path / 'file.json')
    async def error(url, **kw):
        raise web.WebResearchError('HTTP 503 fetching URL')
    monkeypatch.setattr(web, '_download', error)
    with pytest.raises(web.WebResearchError, match='503'):
        await web.web_fetch('alice', 'https://example.org/')
    for name, arguments in [
        ('web_search', {'query': 'fine', 'unexpected': 2}),
        ('web_fetch', {'url': 'https://example.org/', 'unexpected': 2}),
        ('not_a_web_tool', {}),
    ]:
        response = json.loads(await web.invoke_web_tool('alice', name, arguments))
        assert 'error' in response
    output = json.loads(await web.invoke_web_tool('alice', 'web_fetch', {'url': 'https://example.org/'}))
    assert 'error' in output
