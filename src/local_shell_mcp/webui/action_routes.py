"""Original /api/agents/actions routes, keyed to existing LSM principal."""
from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .actions import ActionRepository
from .routes import _body, _owner


def _repository():
    from ..settings import get_settings
    from ..sqlite_store import shared_database
    return ActionRepository(shared_database(get_settings().state_dir.resolve()))


async def actions_list(request: Request):
    return JSONResponse(_repository().list(_owner(request)))


async def actions_save(request: Request):
    owner = _owner(request)
    try:
        agent, action = _repository().save(owner, request.path_params["agent_id"], await _body(request))
    except PermissionError as error:
        raise HTTPException(403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    return JSONResponse([agent, action])


async def actions_delete(request: Request):
    owner = _owner(request)
    try:
        deleted = _repository().delete(owner, request.path_params["agent_id"], request.path_params["action_id"])
    except KeyError as error:
        raise HTTPException(404, detail=str(error)) from error
    if not deleted:
        raise HTTPException(404, detail="Action not found")
    return JSONResponse({"message": "Action deleted successfully"})


def action_routes() -> list[Route]:
    return [
        Route("/api/agents/actions", actions_list, methods=["GET"]),
        Route("/api/agents/actions/{agent_id}", actions_save, methods=["POST"]),
        Route("/api/agents/actions/{agent_id}/{action_id}", actions_delete, methods=["DELETE"]),
    ]
