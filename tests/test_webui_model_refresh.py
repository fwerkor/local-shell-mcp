"""The Controller, rather than a browser, owns automatic model maintenance."""

import asyncio

import httpx
import pytest

from local_shell_mcp.webui import model_discovery, routes
from local_shell_mcp.webui.provider_profiles import profile
from test_webui_provider_profiles import setup_profiles, _ADMIN  # noqa: F401


PATH = '/api/lsm/providers'
BASE = 'https://models.invalid/v1'
CONNECTION = {'name': 'Automatic', 'provider': 'openai', 'base_url': BASE, 'api_key': 'secret'}
FIRST = {'models': ['flash', 'old'], 'model_contexts': {'flash': 1048576, 'old': 8192}}
SECOND = {'models': ['flash', 'new'], 'model_contexts': {'flash': 209715, 'new': 65536}}


def saved(database, name='Automatic'):
    with database.connect() as db:
        return db.execute('SELECT value FROM settings WHERE owner=? AND key=?',
                          ('__lsm_controller__', 'model.channel.' + name)).fetchone()[0]


@pytest.mark.asyncio
async def test_automatic_catalog_save_refresh_toggle_and_failure(setup_profiles, monkeypatch):
    _, app = setup_profiles
    calls = []
    catalog = FIRST

    async def fetch(kind, base, token, **kwargs):
        calls.append((kind, base, token))
        if catalog is None:
            raise httpx.ConnectError('sensitive upstream details')
        return catalog

    monkeypatch.setattr(model_discovery, '_fetch_models', fetch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://lsm.invalid', headers=_ADMIN) as client:
        created = await client.put(PATH, json={**CONNECTION, 'auto_discover': True})
        assert created.status_code == 200, created.text
        assert 'secret' not in created.text
        assert profile('Automatic')['models'] == FIRST['models']
        assert profile('Automatic')['model_contexts'] == FIRST['model_contexts']
        assert profile('Automatic')['model_context_overrides'] == {}
        assert profile('Automatic')['auto_discover'] is True
        assert calls == [('openai', BASE, 'secret')]
        # An existing manual channel must not be modified by the background worker.
        manual = {**CONNECTION, 'name': 'Manual', 'models': ['pinned'], 'model_contexts': {'pinned': 4096}}
        assert (await client.put(PATH, json=manual)).status_code == 200
        assert profile('Manual')['auto_discover'] is False
        database = routes._repo().database
        manual_raw = saved(database, 'Manual')

        # Explicit overrides are distinct from provider-reported limits.
        edit = {**CONNECTION, 'auto_discover': True, 'models': FIRST['models'],
                'model_contexts': {'flash': 32768}, 'model_sampling': {'flash': {'temperature': 0.3}}}
        edit.pop('api_key')
        assert (await client.put(PATH, json=edit)).status_code == 200
        before = profile('Automatic')['model_sync_at']
        catalog = SECOND
        await model_discovery.refresh_model_channels(database)
        current = profile('Automatic')
        assert current['models'] == SECOND['models']
        assert current['model_contexts'] == {'flash': 32768, 'new': 65536}
        assert current['discovered_model_contexts'] == SECOND['model_contexts']
        assert current['model_sampling'] == {'flash': {'temperature': 0.3}}
        assert current['model_sync_at'] >= before
        assert saved(database, 'Manual') == manual_raw
        assert (await client.get('/api/models')).json()['Automatic'] == ['flash', 'new']
        assert (await client.get('/api/endpoints/token-config')).json()['Automatic'] == {
            'flash': {'context': 32768}, 'new': {'context': 65536}}

        catalog = None
        before = profile('Automatic')
        result = await client.post(PATH + '/refresh', json={'channel': 'Automatic'})
        assert result.status_code == 200
        failed = profile('Automatic')
        assert failed['models'] == before['models']
        assert failed['model_contexts'] == before['model_contexts']
        assert failed['model_sync_at'] == before['model_sync_at']
        assert failed['model_sync_error']
        assert 'sensitive' not in result.text
        assert failed['auto_discover'] is True
        # Saving an existing channel during an outage retains its last good data.
        assert (await client.put(PATH, json={**edit, 'models': failed['models']})).status_code == 200
        assert profile('Automatic')['models'] == failed['models']

        # A successful empty catalog hides all available models, without deleting the channel.
        catalog = {'models': [], 'model_contexts': {}}
        await model_discovery.refresh_model_channels(database)
        assert profile('Automatic')['models'] == []
        assert 'Automatic' not in (await client.get('/api/models')).json()
        catalog = SECOND
        await model_discovery.refresh_model_channels(database)
        assert profile('Automatic')['models'] == SECOND['models']

        current = profile('Automatic')
        assert (await client.put(PATH, json={**edit, 'auto_discover': False,
                'models': current['models'], 'model_contexts': current['model_contexts']})).status_code == 200
        calls_before = len(calls)
        catalog = FIRST
        await model_discovery.refresh_model_channels(database)
        assert len(calls) == calls_before
        assert profile('Automatic')['models'] == SECOND['models']
        assert (await client.post(PATH + '/refresh', json={'channel': 'Automatic'})).status_code == 409
        # Enabling again fetches immediately.
        assert (await client.put(PATH, json={**edit, 'models': SECOND['models']})).status_code == 200
        assert profile('Automatic')['models'] == FIRST['models']
        assert profile('Automatic')['auto_discover'] is True


@pytest.mark.asyncio
async def test_inflight_refresh_cannot_overwrite_manual_edit_or_deleted_channel(setup_profiles, monkeypatch):
    _, app = setup_profiles
    started = asyncio.Event()
    release = asyncio.Event()
    block = False

    async def fetch(*args, **kwargs):
        if block:
            started.set()
            await release.wait()
            return SECOND
        return FIRST

    monkeypatch.setattr(model_discovery, '_fetch_models', fetch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://lsm.invalid', headers=_ADMIN) as client:
        assert (await client.put(PATH, json={**CONNECTION, 'auto_discover': True})).status_code == 200
        database = routes._repo().database
        block = True
        task = asyncio.create_task(model_discovery.refresh_model_channels(database))
        await asyncio.wait_for(started.wait(), 1)
        manual = {**CONNECTION, 'auto_discover': False, 'models': ['manual']}
        assert (await client.put(PATH, json=manual)).status_code == 200
        release.set()
        await task
        assert profile('Automatic')['models'] == ['manual']
        assert profile('Automatic')['auto_discover'] is False

        block = False
        assert (await client.put(PATH, json={**CONNECTION, 'auto_discover': True})).status_code == 200
        block = True
        started.clear()
        release.clear()
        task = asyncio.create_task(model_discovery.refresh_model_channels(database))
        await asyncio.wait_for(started.wait(), 1)
        assert (await client.delete(PATH + '?name=Automatic')).status_code == 200
        release.set()
        await task
        with pytest.raises(ValueError, match='Unknown model channel'):
            profile('Automatic')


@pytest.mark.asyncio
async def test_automatic_save_failure_and_saved_key_boundary(setup_profiles, monkeypatch):
    _, app = setup_profiles
    calls = []

    async def fetch(kind, base, token, **kwargs):
        calls.append((kind, base, token))
        raise httpx.ConnectError('private')

    monkeypatch.setattr(model_discovery, '_fetch_models', fetch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://lsm.invalid', headers=_ADMIN) as client:
        result = await client.put(PATH, json={**CONNECTION, 'auto_discover': True})
        assert result.status_code == 502 and 'private' not in result.text
        with pytest.raises(ValueError):
            profile('Automatic')
        assert (await client.put(PATH, json={**CONNECTION, 'models': ['manual']})).status_code == 200
        edited = {**CONNECTION, 'base_url': 'https://other.invalid', 'auto_discover': True}
        edited.pop('api_key')
        assert (await client.put(PATH, json=edited)).status_code == 400
        assert len(calls) == 1
        assert profile('Automatic')['base_url'] == BASE
        assert (await client.put(PATH, json={**CONNECTION, 'auto_discover': 'yes'})).status_code == 400
        assert (await client.post(PATH + '/refresh', json={'channel': 'missing'})).status_code == 404
        assert (await client.post(PATH + '/refresh', json={})).status_code == 400
        assert (await client.post(PATH + '/refresh', json={'channel': 'Automatic'},
                                  headers={'x-test-scope': 'files:read'})).status_code == 403


@pytest.mark.asyncio
async def test_refresh_loop_starts_immediately_and_recovers_after_cycle_failure(monkeypatch):
    rounds = 0
    done = asyncio.Event()

    async def refresh(database):
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            raise RuntimeError('database temporary failure')
        done.set()

    monkeypatch.setattr(model_discovery, 'REFRESH_INTERVAL', 0.01)
    monkeypatch.setattr(model_discovery, 'refresh_model_channels', refresh)
    task = asyncio.create_task(model_discovery.serve_model_refresh(None))
    try:
        await asyncio.wait_for(done.wait(), 1)
        assert rounds >= 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
