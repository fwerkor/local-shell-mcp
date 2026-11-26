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
        body = await _body(request)
        return JSONResponse(repository.create(owner, body), status_code=201)
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
        from .durable_tasks import mark_revoked

        mark_revoked(owner)
        return JSONResponse({}, status_code=200)
    else:
        try:
            body = await _body(request)
            result = repository.update(owner, agent_id, body)
            if {"machine_permissions", "machine_default_permission", "tools"} & body.keys():
                from .durable_tasks import mark_revoked

                mark_revoked(owner)
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
    from .durable_tasks import mark_revoked

    mark_revoked(_owner(request))
    return JSONResponse(result)


async def tool_catalog(request: Request):
    _owner(request)
    from .ask_user_tools import ASK_USER_MANIFEST
    # Web research is exposed through the built-in capability, not as plugins.
    return JSONResponse([{**ASK_USER_MANIFEST, "authenticated": True}])


async def tool_auth(request: Request):
    _owner(request)
    from .ask_user_tools import ASK_USER_QUESTION_TOOL_NAME

    if request.path_params["tool_id"] != ASK_USER_QUESTION_TOOL_NAME:
        _not_found()
    return JSONResponse({"authenticated": True})


async def external_mcp_servers(request: Request):
    """Expose the *LSM* dynamic registry, never credentials or startup arguments.

    LibreChat's separate MCP server registry is not the source of truth for
    servers registered through LSM mcp_manage.
    """
    _owner(request)
    from ..dynamic_mcp import DynamicMCPManager
    from ..settings import get_settings

    settings = get_settings()
    manager = DynamicMCPManager(settings.state_dir, max_timeout_s=settings.max_timeout_s)
    try:
        result = await manager.manage(action="list")
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, detail="Unable to read external MCP registry") from exc
    return JSONResponse({"servers": [
        {"name": item["name"], "transport": item["transport"],
         "enabled": item["enabled"], "tool_count": item["tool_count"]}
        for item in result["servers"]
    ]})


def agent_routes() -> list[Route]:
    from .action_routes import action_routes

    return [
        *action_routes(),
        Route("/api/lsm/mcp/servers", external_mcp_servers, methods=["GET"]),
        Route("/api/agents/tools", tool_catalog, methods=["GET"]),
        Route("/api/agents/tools/{tool_id}/auth", tool_auth, methods=["GET"]),
        Route("/api/agents", list_or_create, methods=["GET", "POST"]),
        Route("/api/agents/{agent_id}/versions", versions, methods=["GET"]),
        Route("/api/agents/{agent_id}/expanded", expanded, methods=["GET"]),
        Route("/api/agents/{agent_id}/duplicate", duplicate, methods=["POST"]),
        Route("/api/agents/{agent_id}/revert", revert, methods=["POST"]),
        Route("/api/agents/{agent_id}", detail, methods=["GET", "PATCH", "DELETE"]),
    ]
