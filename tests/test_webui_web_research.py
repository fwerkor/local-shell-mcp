"""First-party WebUI search, full-text reading and safety boundaries."""
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from local_shell_mcp.webui import web_research as web
from local_shell_mcp.webui.generations import _web_search_requested


def test_default_on_and_explicit_off():
    assert _web_search_requested(None, {}) is True
    assert _web_search_requested(None, {'ephemeralAgent': {'web_search': False}}) is False
    assert _web_search_requested(None, {'ephemeralAgent': {'web_search': True}}) is True
    assert _web_search_requested({'model_parameters': {'web_search': False}}, {}) is False
    assert _web_search_requested({'web_search': False}, {}) is False
    assert _web_search_requested({'web_search': True, 'model_parameters': {'web_search': False}}, {}) is True
    assert _web_search_requested({'web_search': False}, {'ephemeralAgent': {'web_search': True}}) is True
    assert _web_search_requested(None, {'web_search': False}) is False
    assert _web_search_requested(None, {'ephemeralAgent': {'web_search': 'false'}}) is True


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'ftp://example.com/file', 'http://localhost/',
    'http://127.0.0.1/', 'http://10.0.0.1/', 'http://169.254.169.254/latest/meta-data/',
    'http://[::1]/', 'http://example.com:8888/', 'https://user:pass@example.com/',
])
def test_block_unsafe_url(url):
    with pytest.raises(web.WebResearchError):
        web._safe_url(url)


@pytest.mark.asyncio
async def test_revalidate_redirect_target(monkeypatch):
    real_client = httpx.AsyncClient
    def handler(request):
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/secret'})
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    # Even if name resolution is mocked, _safe_url must block direct loopback.
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kw: real_client(
        **{**kw, 'transport': httpx.MockTransport(handler)}))
    with pytest.raises(web.WebResearchError, match='Private'):
        await web._download('https://example.org/')


def test_html_extractor_ignores_scripts_navigation_and_keeps_headings():
    page = b'''<html><head><title>Paper Title</title><script>secret()</script></head>
    <body><nav>private navigation</nav><article><h1>Introduction</h1>
    <p>Diffusion experiments <b>show</b> accuracy.</p><h2>Methods</h2>
    <p>Long context is processed lazily.</p></article></body></html>'''
    data = web._parse_document('text/html', page, 'https://example.org')
    assert data['title'] == 'Paper Title'
    assert '# Introduction' in data['text']
    assert 'Diffusion experiments' in data['text']
    assert 'private navigation' not in data['text']
    assert 'secret()' not in data['text']
    assert any(item['heading'] == '## Methods' for item in data['sections'])


def test_pdf_pages_preserved(monkeypatch):
    class Doc:
        def __enter__(self):
            return [SimpleNamespace(get_text=lambda **kw: 'Method Section'),
                    SimpleNamespace(get_text=lambda **kw: 'Experimental Result')]
        def __exit__(self, *args):
            pass
    monkeypatch.setitem(sys.modules, 'pymupdf', SimpleNamespace(open=lambda **kw: Doc()))
    data = web._parse_document('application/pdf', b'%PDF-FAKE', 'https://example.org/paper.pdf')
    assert '[Page 1]' in data['text'] and '[Page 2]' in data['text']
    assert data['pages'] == 2
    assert data['sections'][1]['offset'] > data['sections'][0]['offset']


@pytest.mark.asyncio
async def test_arxiv_full_text_cache_and_query(monkeypatch, tmp_path):
    calls = []
    async def download(url, **kw):
        calls.append(url)
        return (url, 'text/html', b'<html><title>Research</title><article><h1>Intro</h1>' +
                b'<p>' + b'A' * 16000 + b'EXPERIMENTAL METHOD' + b'B' * 20000 + b'</p></article></html>')
    monkeypatch.setattr(web, '_download', download)
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_cache_file', lambda owner, url: tmp_path / (owner + '.json'))
    first = await web.web_fetch('alice', 'https://arxiv.org/abs/2502.09992', limit=8000)
    assert calls == ['https://arxiv.org/html/2502.09992']
    assert first['next_offset'] == 8000 and first['length'] > 30000
    match = await web.web_fetch('alice', 'https://arxiv.org/abs/2502.09992', query='EXPERIMENTAL METHOD', limit=500)
    assert 'EXPERIMENTAL METHOD' in match['content'] and len(calls) == 1
    assert match['offset'] > 8000
    middle = await web.web_fetch('alice', 'https://arxiv.org/abs/2502.09992', offset=10000, limit=400)
    assert middle['offset'] == 10000 and len(middle['content']) == 400
    # Cache is scoped to the authenticated user rather than URL alone.
    await web.web_fetch('bob', 'https://arxiv.org/abs/2502.09992')
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_search_rss_fallback_and_tool_errors(monkeypatch):
    monkeypatch.setitem(sys.modules, 'ddgs', None)
    async def download(url, **kw):
        assert 'format=rss' in url
        return url, 'application/rss+xml', b'''<rss><channel>
        <item><title>Research</title><link>https://arxiv.org/abs/2502.09992</link>
        <description>Diffusion language model</description></item>
        <item><title>Duplicate</title><link>https://arxiv.org/abs/2502.09992</link></item>
        </channel></rss>'''
    monkeypatch.setattr(web, '_download', download)
    found = await web.web_search('language diffusion')
    assert len(found['results']) == 1
    assert found['results'][0]['url'] == 'https://arxiv.org/abs/2502.09992'
    assert json.loads(await web.invoke_web_tool('alice', 'web_search', {'query': ''}))['error']
    assert json.loads(await web.invoke_web_tool('alice', 'web_fetch', {'url': 'file:///etc/passwd'}))['error']


@pytest.mark.asyncio
async def test_arxiv_html_to_pdf_fallback(monkeypatch, tmp_path):
    urls = []
    async def download(url, **kw):
        urls.append(url)
        if '/html/' in url:
            raise web.WebResearchError('HTTP 404 fetching URL')
        return url, 'text/plain', b'paper fulltext'
    monkeypatch.setattr(web, '_download', download)
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_cache_file', lambda owner, url: tmp_path / 'fallback.json')
    result = await web.web_fetch('alice', 'https://arxiv.org/abs/2502.09992')
    assert urls == ['https://arxiv.org/html/2502.09992', 'https://arxiv.org/pdf/2502.09992']
    assert result['content'] == 'paper fulltext'


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['A' * 500, 'ß' * 500])
async def test_query_window_contains_match_with_small_limit_and_unicode(monkeypatch, tmp_path, prefix):
    async def download(url, **kwargs):
        return url, 'text/plain; charset=utf-8', (prefix + 'TARGET MATCH' + 'B' * 500).encode()

    monkeypatch.setattr(web, '_download', download)
    monkeypatch.setattr(web, '_public_address', lambda host: True)
    monkeypatch.setattr(web, '_cache_file', lambda owner, url: tmp_path / 'document.json')
    result = await web.web_fetch('alice', 'https://example.org/doc', query='target match', limit=100)
    assert 'TARGET MATCH' in result['content']
    assert result['offset'] < len(prefix) < result['next_offset']
    assert len(result['content']) == 100
