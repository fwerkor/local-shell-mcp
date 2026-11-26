"""Admin-only model discovery and controller-owned saved catalog refresh."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .provider_profiles import (
    _CHANNEL_PREFIX,
    _DEFAULTS,
    _OWNER,
    _PREFIX,
    _access,
    profile,
    public_profiles,
    validate_connection,
)
from .routes import _body, _repo

logger = logging.getLogger(__name__)

_MAX_MODELS = 128
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _chat_compatible(model: str, item: dict, kind: str = "openai") -> bool:
    # Some OpenAI-compatible catalogs (e.g. OpenRouter) include explicit
    # output modalities or supported endpoints. Prefer those to ID heuristics.
    architecture = item.get('architecture')
    modalities = architecture.get('output_modalities') if isinstance(architecture, dict) else None
    if isinstance(modalities, list) and modalities and 'text' not in modalities:
        return False
    endpoints = item.get('supported_endpoints')
    if isinstance(endpoints, list) and endpoints:
        suffix = 'responses' if kind == 'openai-responses' else 'chat/completions'
        return any(isinstance(e, str) and e.rstrip('/').endswith(suffix) for e in endpoints)
    # Local inference servers can describe non-generative models by task
    # rather than publishing supported_endpoints.
    non_chat = {
        'embed', 'embedding', 'embeddings', 'rerank', 'reranking', 'score',
        'classify', 'classification', 'reward', 'pooling', 'transcription',
        'speech', 'text-to-speech', 'image-generation', 'moderation',
    }
    for key in ('task', 'model_type', 'type'):
        value = item.get(key)
        if isinstance(value, str) and value.strip().lower().replace('_', '-') in non_chat:
            return False
    tasks = item.get('supported_tasks')
    if isinstance(tasks, list) and tasks:
        normalized = {t.strip().lower().replace('_', '-') for t in tasks if isinstance(t, str)}
        if normalized and normalized <= non_chat:
            return False
    # Older catalogs often expose only IDs, including non-chat OpenAI models.
    leaf = model.lower().rsplit('/', 1)[-1]
    if re.fullmatch(r'(?:babbage|davinci)(?:-\d+)?|gpt-3\.5-turbo-instruct(?:-\d+)?', leaf):
        return False
    return not re.search(
        r'(?:^|[-_.])(?:embeddings?|rerank(?:er)?|whisper|tts|transcri(?:be|ption)|'
        r'dall-e|image|moderation|realtime|text-search|code-search|sora)(?:$|[-_.0-9])', leaf
    )


def _parse_page(kind: str, data: dict, models: dict[str, int | None]) -> dict:
    items = data.get('models' if kind == 'google' else 'data')
    if not isinstance(items, list):
        raise ValueError('Invalid provider model list')
    for item in items:
        if not isinstance(item, dict):
            continue
        model = item.get('name' if kind == 'google' else 'id')
        if not isinstance(model, str):
            continue
        if kind == 'google':
            methods = item.get('supportedGenerationMethods')
            if not isinstance(methods, list) or 'generateContent' not in methods:
                continue
            model = model.removeprefix('models/')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', model):
                continue
        if not model.strip() or model != model.strip() or len(model) > 200 or any(ord(c) < 32 for c in model):
            continue
        if kind in {'openai', 'openai-responses'} and not _chat_compatible(model, item, kind):
            continue
        fields = ('inputTokenLimit',) if kind == 'google' else (
            'context_window', 'context_length', 'max_model_len', 'max_context_tokens', 'max_input_tokens')
        limit = next((item[key] for key in fields if type(item.get(key)) is int
                      and 0 < item[key] <= 2_000_000), None)
        if model not in models or limit is not None:
            models[model] = limit
        if len(models) > _MAX_MODELS:
            raise ValueError('Provider lists more than 128 models; enter the desired models manually')
    if kind == 'google' and data.get('nextPageToken'):
        cursor = data['nextPageToken']
        if not isinstance(cursor, str) or len(cursor) > 4096:
            raise ValueError('Invalid model list cursor')
        return {'pageToken': cursor}
    if kind == 'anthropic' and data.get('has_more'):
        cursor = data.get('last_id')
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
            raise ValueError('Invalid model list cursor')
        return {'after_id': cursor}
    return {}


async def _fetch_models(kind: str, base: str, token: str, *, allow_empty: bool = False, account: bool = False) -> dict:
    headers = {'accept': 'application/json'}
    if token:
        if kind == 'google':
            headers['x-goog-api-key'] = token
        elif kind == 'anthropic':
            headers['x-api-key'] = token
        else:
            headers['Authorization'] = f'Bearer {token}'
    if kind == 'anthropic':
        headers['anthropic-version'] = '2023-06-01'
    models: dict[str, int | None] = {}
    params: dict = {}
    seen: set[tuple] = set()
    # Do not follow redirects, expose upstream errors, or send saved keys to an
    # edited URL. Bound the entire discovery, including paginated responses.
    async with asyncio.timeout(15), httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        for _ in range(16):
            async with client.stream('GET', base + '/models', headers=headers, params=params) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise ValueError('Provider model list is too large')
                    content.extend(chunk)
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError('Invalid provider model list')
            if account:
                if not isinstance(data.get("models"), list):
                    raise ValueError("Invalid account model list")
                data = {"data": [{**item, "id": item.get("slug")} for item in data["models"]
                                 if isinstance(item, dict) and item.get("visibility") == "list"]}
            params = _parse_page(kind, data, models)
            if not params:
                break
            cursor = tuple(params.items())
            if cursor in seen:
                raise ValueError('Provider repeated a model list page')
            seen.add(cursor)
        else:
            raise ValueError('Provider model list has too many pages')
    if not models and not allow_empty:
        raise ValueError('Provider returned no supported models; enter model identifiers manually')
    return {'models': list(models), 'model_contexts': {m: n for m, n in models.items() if n is not None}}


async def discover_models(request):
    _access(request)
    body = await _body(request)
    try:
        kind, base, token = validate_connection(body)
        channel = body.get('existing_channel')
        if token is None and channel is not None:
            saved = profile(channel)
            if saved.get("oauth_id"):
                if (saved["provider"], saved["base_url"]) != (kind, base):
                    raise ValueError("Account credentials are bound to the original API endpoint")
                from .model_oauth import catalog_for
                result = await catalog_for(_repo().database, saved)
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            token = saved.get('api_key')
            if token and (saved['provider'] != kind or saved['base_url'].rstrip('/') != base):
                raise ValueError('Enter an API key to discover models at a changed endpoint')
        result = await _fetch_models(kind, base, token or '')
    except (httpx.HTTPError, TimeoutError, json.JSONDecodeError, UnicodeError):
        raise HTTPException(502, detail='Could not retrieve model list. Check the endpoint and API key, or enter models manually.') from None
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


# The Controller owns this cadence; no browser, toggle-specific timer or user
# interval preference is required.
REFRESH_INTERVAL = 600
_SYNC_ERROR = 'Unable to refresh model information. Last successful data is retained.'


def connection_identity(value: dict) -> tuple:
    return (value.get('provider'), (value.get('base_url') or '').rstrip('/'), value.get('oauth_id') or value.get('api_key') or '')


def _apply_catalog(value: dict, catalog: dict, overrides: dict) -> None:
    models = catalog['models']
    reported = {m: n for m, n in catalog['model_contexts'].items() if m in models}
    overrides = {m: n for m, n in overrides.items() if m in models}
    value.update(
        models=models,
        discovered_model_contexts=reported,
        model_context_overrides=overrides,
        model_contexts={**reported, **overrides},
        model_sync_at=time.time(),
        model_sync_error=None,
    )
    # Only active models need defaults in the editable catalog. Historical
    # conversations and Agent references are not rewritten.
    value['model_sampling'] = {m: v for m, v in (value.get('model_sampling') or {}).items()
                               if m in models}


async def prepare_auto_save(value: dict, previous: dict) -> tuple[tuple, dict | None]:
    """Resolve and probe a connection before opening the SQLite write transaction."""
    identity = connection_identity(previous)
    if previous.get("oauth_id"):
        from .model_oauth import catalog_for
        try:
            return identity, await catalog_for(_repo().database, previous)
        except (httpx.HTTPError, TimeoutError, ValueError):
            return identity, None
    same_endpoint = identity[:2] == connection_identity(value)[:2]
    if value['api_key'] is None and identity[2] and not same_endpoint:
        raise HTTPException(400, detail='Enter an API key to use automatic discovery at a changed endpoint')
    token = value['api_key'] if value['api_key'] is not None else identity[2]
    try:
        return identity, await _fetch_models(value['provider'], value['base_url'], token,
                                             allow_empty=previous.get('auto_discover') is True and same_endpoint)
    except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError):
        # A newly configured connection must have a verified catalog. An
        # existing connection may still be saved during a temporary outage.
        if same_endpoint and token == identity[2] and (previous.get('models') or previous.get('auto_discover') is True):
            return identity, None
        raise HTTPException(502, detail='Unable to discover models. Check the connection or turn off automatic discovery.') from None


def apply_auto_save(value: dict, previous: dict, catalog: dict | None) -> None:
    overrides = value['model_contexts']
    if catalog is not None:
        _apply_catalog(value, catalog, overrides)
        return
    if previous.get('auto_discover') is True:
        reported = previous.get('discovered_model_contexts') or {}
    else:
        # An old/manual list is a valid fallback, not discovered metadata.
        reported = {}
        overrides = {**(previous.get('model_contexts') or {}), **overrides}
    _apply_catalog(value, {'models': previous['models'], 'model_contexts': reported}, overrides)
    value['model_sync_at'] = previous.get('model_sync_at')
    value['model_sync_error'] = _SYNC_ERROR


async def _refresh_snapshot(database, key: str, raw: str) -> bool:
    """Fetch without a write lock; CAS prevents stale replies from undoing edits/deletes."""
    value = json.loads(raw)
    if value.get('auto_discover') is not True:
        return False
    try:
        if value.get("oauth_id"):
            from .model_oauth import catalog_for
            catalog = await catalog_for(database, value)
        else:
            kind, base, token = validate_connection(value)
            catalog = await _fetch_models(kind, base, token or '', allow_empty=True)
    except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError):
        value['model_sync_error'] = _SYNC_ERROR
    else:
        _apply_catalog(value, catalog, value.get('model_context_overrides') or {})
    with database.connect() as db:
        if value.get("oauth_id"):
            current = db.execute("SELECT value FROM settings WHERE owner=? AND key=?", (_OWNER, key)).fetchone()
            if current:
                latest, original = json.loads(current[0]), json.loads(raw)
                fields = ("oauth_credentials", "oauth_error")
                if all(latest.get(k) == original.get(k) for k in set(latest) | set(original) if k not in fields):
                    for k in fields:
                        value[k] = latest.get(k)
                    raw = current[0]
        cursor = db.execute(
            'UPDATE settings SET value=? WHERE owner=? AND key=? AND value=?',
            (json.dumps(value), _OWNER, key, raw))
        return cursor.rowcount == 1


async def refresh_model_channels(database) -> None:
    with database.connect() as db:
        rows = db.execute(
            "SELECT key,value FROM settings WHERE owner=? AND "
            "(key LIKE ? OR key LIKE ?) AND (json_extract(value,'$.auto_discover')=1 OR json_extract(value,'$.oauth_id') IS NOT NULL)",
            (_OWNER, _PREFIX + '%', _CHANNEL_PREFIX + '%')).fetchall()
    semaphore = asyncio.Semaphore(4)

    async def refresh(row):
        async with semaphore:
            value = json.loads(row['value'])
            if value.get("oauth_id") and not value.get("auto_discover"):
                from .model_oauth import access_token
                await access_token(database, value["name"], value["oauth_id"])
            else:
                await _refresh_snapshot(database, row['key'], row['value'])

    results = await asyncio.gather(*(refresh(row) for row in rows), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            # Do not log upstream URLs, bodies or credentials.
            logger.warning('Model catalog refresh failed: %s', type(result).__name__)


async def serve_model_refresh(database) -> None:
    while True:
        try:
            await refresh_model_channels(database)
        except Exception as exc:
            logger.warning('Model catalog refresh cycle failed: %s', type(exc).__name__)
        await asyncio.sleep(REFRESH_INTERVAL)


async def refresh_model_channel(request):
    _access(request)
    body = await _body(request)
    channel = body.get('channel')
    if not isinstance(channel, str):
        raise HTTPException(400, detail='Specify a saved channel')
    key = _PREFIX + channel if channel in _DEFAULTS else _CHANNEL_PREFIX + channel
    database = _repo().database
    with database.connect() as db:
        row = db.execute('SELECT value FROM settings WHERE owner=? AND key=?',
                         (_OWNER, key)).fetchone()
    if row is None:
        raise HTTPException(404, detail='Channel not found')
    if json.loads(row['value']).get('auto_discover') is not True:
        raise HTTPException(409, detail='Automatic model discovery is disabled')
    if not await _refresh_snapshot(database, key, row['value']):
        raise HTTPException(409, detail='Channel changed during refresh; retry')
    return JSONResponse(public_profiles(), headers={'Cache-Control': 'no-store'})
