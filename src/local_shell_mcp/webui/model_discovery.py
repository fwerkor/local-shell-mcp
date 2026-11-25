"""Admin-only model metadata discovery; never changes saved channels."""
from __future__ import annotations

import asyncio
import json
import re

import httpx
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .provider_profiles import _access, profile, validate_connection
from .routes import _body

_MAX_MODELS = 128
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


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


async def _fetch_models(kind: str, base: str, token: str) -> dict:
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
            params = _parse_page(kind, data, models)
            if not params:
                break
            cursor = tuple(params.items())
            if cursor in seen:
                raise ValueError('Provider repeated a model list page')
            seen.add(cursor)
        else:
            raise ValueError('Provider model list has too many pages')
    if not models:
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
            if saved['provider'] != kind or saved['base_url'].rstrip('/') != base:
                raise ValueError('Enter an API key to discover models at a changed endpoint')
            token = saved.get('api_key')
        result = await _fetch_models(kind, base, token or '')
    except (httpx.HTTPError, TimeoutError, json.JSONDecodeError, UnicodeError):
        raise HTTPException(502, detail='Could not retrieve model list. Check the endpoint and API key, or enter models manually.') from None
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})
