"""Native Python agent-management HTTP endpoints for the unified WebUI."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .agents import AgentRepository
from .routes import _body, _integer, _not_found, _owner


def _agents() -> AgentRepository:
    from ..settings import get_settings
    from ..sqlite_store import shared_database

    return AgentRepository(shared_database(get_settings().state_dir.resolve()))


async def list_or_create(request: Request):
    owner = _owner(request)
    repository = _agents()
    if request.method == "GET":
        query = request.query_params
        try:
            return JSONResponse(repository.list(owner, limit=_integer(query.get("limit")),
                                                cursor=query.get("cursor"), category=query.get("category"),
                                                search=query.get("search")))
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
    try:
        return JSONResponse(repository.create(owner, await _body(request)), status_code=201)
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


async def detail(request: Request):
    owner = _owner(request)
    repository = _agents()
    agent_id = request.path_params["agent_id"]
    if request.method == "GET":
        result = repository.get(owner, agent_id)
    elif request.method == "DELETE":
        if not repository.delete(owner, agent_id):
            _not_found()
        return JSONResponse({}, status_code=200)
    else:
        try:
            result = repository.update(owner, agent_id, await _body(request))
        except PermissionError as exc:
            raise HTTPException(403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
    if result is None:
        _not_found()
    return JSONResponse(result)


async def expanded(request: Request):
    result = _agents().get(_owner(request), request.path_params["agent_id"])
    if result is None:
        _not_found()
    return JSONResponse(result)


async def versions(request: Request):
    result = _agents().versions(_owner(request), request.path_params["agent_id"])
    if result is None:
        _not_found()
    return JSONResponse(result)


async def duplicate(request: Request):
    try:
        result = _agents().duplicate(_owner(request), request.path_params["agent_id"])
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    if result is None:
        _not_found()
    return JSONResponse(result, status_code=201)


async def revert(request: Request):
    data = await _body(request)
    try:
        result = _agents().revert(
            _owner(request), request.path_params["agent_id"], int(data.get("version_index")),
        )
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, detail="Invalid agent version index") from exc
    if result is None:
        _not_found()
    return JSONResponse(result)


def _native_tool_catalog() -> list[dict]:
    from .lsm_tool_registry import _operation, _registry

    entries = []
    for tool in _registry()._tool_manager.list_tools():
        # Authoring exposes the audited registry independently of the current
        # machine ACL. Native dispatch remains the execution permission gate.
        if tool.name not in {"mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call"}:
            try:
                _operation(tool)
            except PermissionError:
                continue
        entries.append({"name": tool.name, "pluginKey": tool.name,
                        "description": tool.description or "", "agentsOnly": True,
                        "authConfig": [], "authenticated": True})
    return entries


async def tool_catalog(request: Request):
    _owner(request)
    from .ask_user_tools import ASK_USER_MANIFEST

    # The original manifest and PluginController authentication shape are
    # reused. Availability does not enable a saved or ephemeral Agent's tool.
    return JSONResponse([{**ASK_USER_MANIFEST, "authenticated": True}, *_native_tool_catalog()])


async def tool_auth(request: Request):
    _owner(request)
    from .ask_user_tools import ASK_USER_QUESTION_TOOL_NAME

    if request.path_params["tool_id"] != ASK_USER_QUESTION_TOOL_NAME and not any(
        item["pluginKey"] == request.path_params["tool_id"] for item in _native_tool_catalog()
    ):
        _not_found()
    return JSONResponse({"authenticated": True})


def agent_routes() -> list[Route]:
    from .action_routes import action_routes

    return [
        *action_routes(),
        Route("/api/agents/tools", tool_catalog, methods=["GET"]),
        Route("/api/agents/tools/{tool_id}/auth", tool_auth, methods=["GET"]),
        Route("/api/agents", list_or_create, methods=["GET", "POST"]),
        Route("/api/agents/{agent_id}/versions", versions, methods=["GET"]),
        Route("/api/agents/{agent_id}/expanded", expanded, methods=["GET"]),
        Route("/api/agents/{agent_id}/duplicate", duplicate, methods=["POST"]),
        Route("/api/agents/{agent_id}/revert", revert, methods=["POST"]),
        Route("/api/agents/{agent_id}", detail, methods=["GET", "PATCH", "DELETE"]),
    ]
