"""Message bookmarks are owner-scoped and reference persisted messages."""
import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import message_bookmark_routes as routes
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def app(tmp_path, monkeypatch):
    repo = WorkspaceRepository(SQLiteDatabase(tmp_path))
    monkeypatch.setattr(routes, '_repo', lambda: repo)
    monkeypatch.setattr(routes, '_owner', lambda request: request.headers.get('x-owner', 'alice'))
    return Starlette(routes=routes.message_bookmark_routes()), repo


@pytest.mark.asyncio
async def test_message_bookmarks_lifecycle(app):
    server, repo = app
    convo = repo.create_conversation('alice', {'title': 'Alice chat', 'tags': ['existing']})
    cid = convo['conversationId']
    msg = repo.add_message('alice', cid, {'text': 'Remember this', 'role': 'assistant'})
    mid = msg['messageId']
    url = '/api/message-bookmarks/' + mid
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        assert (await c.get('/api/message-bookmarks')).json() == []
        first = await c.put(url, json={})
        assert first.status_code == 200, first.text
        assert first.json()['preview'] == 'Remember this'
        assert first.json()['conversationId'] == cid
        assert first.json()['conversationTitle'] == 'Alice chat'
        assert (await c.put(url, json={'title': '  Important  '})).json()['title'] == 'Important'
        assert (await c.put(url, json={})).json()['title'] == 'Important'
        assert (await c.put(url, json={'title': 2})).status_code == 400
        assert (await c.put(url, json={'title': 'x' * 257})).status_code == 400
        assert len((await c.get('/api/message-bookmarks')).json()) == 1
        assert repo.conversation('alice', cid)['tags'] == ['existing']
        assert (await c.delete(url)).status_code == 200
        assert (await c.get('/api/message-bookmarks')).json() == []
        await c.put(url, json={})
        assert repo.delete_conversation('alice', cid)
        assert (await c.get('/api/message-bookmarks')).json() == []
        with repo.database.connect() as db:
            assert db.execute('SELECT count(*) FROM webui_message_bookmarks').fetchone()[0] == 0
        assert (await c.put(url, json={})).status_code == 404


@pytest.mark.asyncio
async def test_bookmarks_owner_boundary_and_message_deletion(app):
    server, repo = app
    cid = repo.create_conversation('alice', {'title': 'A'})['conversationId']
    mid = repo.add_message('alice', cid, {'text': 'Private'})['messageId']
    other = repo.create_conversation('bob', {'title': 'B'})['conversationId']
    other_mid = repo.add_message('bob', other, {'text': 'Other'})['messageId']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        url = '/api/message-bookmarks/' + mid
        assert (await c.put(url, json={})).status_code == 200
        assert (await c.put('/api/message-bookmarks/' + other_mid, json={})).status_code == 404
        assert (await c.put(url, headers={'x-owner': 'bob'}, json={'title': 'Bad'})).status_code == 404
        assert (await c.get('/api/message-bookmarks', headers={'x-owner': 'bob'})).json() == []
        assert (await c.delete(url, headers={'x-owner': 'bob'})).status_code == 200
        assert len((await c.get('/api/message-bookmarks')).json()) == 1
        with repo.database.connect() as db:
            db.execute('DELETE FROM messages WHERE id=?', (mid,))
        assert (await c.get('/api/message-bookmarks')).json() == []
