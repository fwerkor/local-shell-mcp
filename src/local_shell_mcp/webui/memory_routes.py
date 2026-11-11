"""LibreChat /api/memories controller backed by the single SQLite store.

Source: api/server/routes/memories.js and packages/api/src/memory/handlers.ts.
"""
from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .agents import AgentRepository
from .memory import _VALID_KEY, MemoryRepository, _utf16_length, memory_config
from .routes import _body, _owner, _repo


def _context(request: Request, *, write: bool = False):
    owner = _owner(request)
    repo = _repo()
    if memory_config(repo, owner) is None:
        raise HTTPException(403, detail='Memory is unavailable or disabled')
    return owner, repo, MemoryRepository(repo.database), memory_config(repo, owner) or {}


def _partition(owner: str, repo, request: Request, *, create: bool = False, allow_missing: bool = False) -> str:
    agent_id = (request.query_params.get('agentId') if not create else None) or ''
    if not agent_id:
        return ''
    if not isinstance(agent_id, str) or len(agent_id) > 128:
        raise HTTPException(400, detail='Invalid agentId')
    # Deleted Agent's opaque memory can still be deleted, but not read/edited
    # through the partition bypass. The original middleware permits this.
    if AgentRepository(repo.database).get(owner, agent_id) is None and not allow_missing:
        raise HTTPException(404, detail='Agent not found.')
    return agent_id


def _validate(key: object, value: object, config: dict) -> tuple[str, str]:
    if not isinstance(key, str) or not key.strip():
        raise HTTPException(400, detail='Key is required and must be a non-empty string.')
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, detail='Value is required and must be a non-empty string.')
    key = key.strip()
    if _utf16_length(key) > 1000:
        raise HTTPException(400, detail='Key exceeds maximum length of 1000 characters.')
    if not _VALID_KEY.fullmatch(key):
        raise HTTPException(400, detail='Key must only contain lowercase letters and underscores.')
    if _utf16_length(value) > (config.get('charLimit') or 10000):
        raise HTTPException(400, detail='Value exceeds maximum character length.')
    return key, value


def _write(repo: MemoryRepository, owner: str, config: dict, key: str, value: str, **kwargs) -> dict:
    try:
        return repo.write(owner, key, value, char_limit=config.get('charLimit') or 10000,
                          token_limit=config.get('tokenLimit'), **kwargs)
    except FileExistsError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, detail='Memory not found.') from exc
    except OverflowError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


async def memories(request: Request):
    owner, repo, store, config = _context(request)
    if request.method == 'GET':
        items = store.list(owner)
        for item in items:
            if agent_id := item.get('agentId'):
                agent = AgentRepository(repo.database).get(owner, agent_id)
                if agent:
                    item['agentName'] = agent.get('name')
        total = sum(item['tokenCount'] for item in items if not item.get('agentId'))
        limit = config.get('tokenLimit') or None
        return JSONResponse({'memories': items, 'totalTokens': total, 'tokenLimit': limit,
                             'charLimit': config.get('charLimit') or 10000,
                             'usagePercentage': min(100, int(total / limit * 100 + 0.5)) if limit else None})
    data = await _body(request)
    key, value = _validate(data.get('key'), data.get('value'), config)
    agent_id = data.get('agentId')
    if not isinstance(agent_id, str) or not agent_id.strip():
        agent_id = ''
    if agent_id and AgentRepository(repo.database).get(owner, agent_id) is None:
        raise HTTPException(404, detail='Agent not found.')
    record = _write(store, owner, config, key, value.strip(), agent_id=agent_id, create=True)
    return JSONResponse({'created': True, 'memory': record}, status_code=201)


async def preference(request: Request):
    owner, repo, _, _ = _context(request)
    body = await _body(request)
    if type(body.get('memories')) is not bool:
        raise HTTPException(400, detail='memories must be a boolean value.')
    repo.save_setting(owner, 'user.memories', body['memories'])
    return JSONResponse({'updated': True, 'preferences': {'memories': body['memories']}})


async def memory_by_id(request: Request):
    owner, repo, store, config = _context(request)
    part = _partition(owner, repo, request, allow_missing=request.method == 'DELETE')
    identifier = request.path_params['id']
    if request.method == 'DELETE':
        if not store.delete(owner, entry_id=identifier, agent_id=part):
            raise HTTPException(404, detail='Memory not found.')
        return JSONResponse({'deleted': True})
    body = await _body(request)
    value = body.get('value')
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, detail='Value is required and must be a non-empty string.')
    key = body.get('key')
    if key is None:
        record = next((entry for entry in store.list(owner, part) if entry['_id'] == identifier), None)
        if record is None:
            raise HTTPException(404, detail='Memory not found.')
        key = record['key']
    key, value = _validate(key, value, config)
    record = _write(store, owner, config, key, value, agent_id=part, existing_id=identifier)
    return JSONResponse({'updated': True, 'memory': record})


async def memory_by_key(request: Request):
    owner, repo, store, config = _context(request)
    part = _partition(owner, repo, request, allow_missing=request.method == 'DELETE')
    key = request.path_params['key']
    if request.method == 'DELETE':
        if not store.delete(owner, key=key, agent_id=part):
            raise HTTPException(404, detail='Memory not found.')
        return JSONResponse({'deleted': True})
    body = await _body(request)
    new_key, value = _validate(body.get('key', key), body.get('value'), config)
    prior = next((entry for entry in store.list(owner, part) if entry['key'] == key), None)
    if prior is None:
        raise HTTPException(404, detail='Memory not found.')
    record = _write(store, owner, config, new_key, value, agent_id=part, existing_id=prior['_id'])
    return JSONResponse({'updated': True, 'memory': record})


def memory_routes() -> list[Route]:
    return [Route('/api/memories', memories, methods=['GET', 'POST']),
            Route('/api/memories/preferences', preference, methods=['PATCH']),
            Route('/api/memories/id/{id}', memory_by_id, methods=['PATCH', 'DELETE']),
            Route('/api/memories/{key}', memory_by_key, methods=['PATCH', 'DELETE'])]
