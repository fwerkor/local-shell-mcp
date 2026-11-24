"""Unread markers survive reloads and stale acknowledgments cannot erase new results."""
import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import conversation_routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.mark.asyncio
async def test_unread_lifecycle(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / 'state')
    repo = WorkspaceRepository(db)
    store = GenerationStore(db)
    monkeypatch.setattr(conversation_routes, '_repo', lambda: repo)
    monkeypatch.setattr(conversation_routes, '_owner', lambda request: request.headers['x-owner'])
    app = Starlette(routes=conversation_routes.conversation_routes())
    route = '/api/convos/unread'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                 headers={'x-owner': 'alice'}) as client:
        run, _ = store.begin('alice', {'text': 'Hello'})
        cid = run.conversation_id
        assert (await client.get(route)).json() == {'unread': {}}
        assert store.finish('alice', run.run_id, status='complete', text='Answer')
        marker = (await client.get(route)).json()['unread'][cid]
        assert marker == 'run:' + run.run_id
        assert (await client.get(route, headers={'x-owner': 'bob'})).json() == {'unread': {}}
        assert (await client.post(route, json={'conversationId': cid, 'unread': False},
                                  headers={'x-owner': 'bob'})).status_code == 404
        manual = (await client.post(route, json={'conversationId': cid, 'unread': True})).json()['marker']
        assert manual.startswith('manual:')
        assert (await client.post(route, json={'conversationId': cid, 'unread': False,
                                              'expected': marker})).json()['marker'] == manual
        reopened = SQLiteDatabase(db.root)
        with reopened.connect() as conn:
            assert conn.execute('SELECT unread_marker FROM conversations WHERE id=?',
                                (cid,)).fetchone()[0] == manual
        assert (await client.post(route, json={'conversationId': cid, 'unread': False,
                                              'expected': manual})).json()['marker'] is None
        assert (await client.get(route)).json() == {'unread': {}}
        assert (await client.post(route, json={'conversationId': cid, 'unread': 'false'})).status_code == 400
        assert not store.finish('alice', run.run_id, status='complete', text='Duplicate')
        assert (await client.get(route)).json() == {'unread': {}}
