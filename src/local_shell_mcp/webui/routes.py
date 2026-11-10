"""Python WebUI HTTP endpoints using LibreChat's route and JSON conventions.

Routes use the existing LSM request principal. They do not grant direct access
to controller operations or bypass the outer OAuth middleware.
"""

from __future__ import annotations

from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..settings import get_settings
from .storage import WorkspaceRepository


def _owner(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    subject = getattr(principal, "subject", None)
    if isinstance(subject, str) and subject:
        return subject
    if get_settings().auth_mode == "none":
        return "local"
    raise HTTPException(401, detail="WebUI authentication required")


def _repo() -> WorkspaceRepository:
    from ..sqlite_store import shared_database

    return WorkspaceRepository(shared_database(get_settings().state_dir.resolve()))


def _integer(raw: Any, default: int = 25) -> int:
    if raw is None:
        return default
    try:
        return max(1, min(int(raw), 100))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, detail="Invalid page limit") from exc


async def _body(request: Request) -> dict:
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, detail="Invalid JSON request") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, detail="Expected JSON object")
    return value


def _result(value: object, *, status: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status)


def _not_found() -> None:
    raise HTTPException(404, detail="Resource not found")


async def conversations(request: Request):
    import sqlite3

    owner = _owner(request)
    repo = _repo()
    if request.method == "GET":
        query = request.query_params
        return _result(repo.conversations(
            owner,
            archived=query.get("isArchived", "false").lower() in {"true", "1"},
            pinned=query.get("pinned", "false").lower() in {"true", "1"},
            project_id=query.get("projectId"), search=query.get("search"),
            cursor=query.get("cursor"), limit=_integer(query.get("limit")),
        ))
    if request.method == "DELETE":
        payload = await _body(request)
        conversation_id = payload.get("arg", {}).get("conversationId") if isinstance(payload.get("arg"), dict) else payload.get("conversationId")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise HTTPException(400, detail="A conversationId is required")
        if not repo.delete_conversation(owner, conversation_id):
            _not_found()
        return _result({"conversationIds": [conversation_id]})
    payload = await _body(request)
    conversation_id = payload.get("conversationId")
    try:
        if isinstance(conversation_id, str) and repo.conversation(owner, conversation_id):
            return _result(repo.update_conversation(owner, conversation_id, payload))
        return _result(repo.create_conversation(owner, payload), status=201)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail="Conversation conflict or invalid project") from exc


async def conversation(request: Request):
    owner = _owner(request)
    repo = _repo()
    conversation_id = request.path_params["conversation_id"]
    if request.method == "GET":
        result = repo.conversation(owner, conversation_id)
        if result is None:
            _not_found()
        return _result(result)
    if request.method == "DELETE":
        if not repo.delete_conversation(owner, conversation_id):
            _not_found()
        return _result({"conversationIds": [conversation_id]})
    changes = await _body(request)
    result = repo.update_conversation(owner, conversation_id, changes)
    if result is None:
        _not_found()
    return _result(result)


async def messages(request: Request):
    owner = _owner(request)
    repo = _repo()
    query = request.query_params
    if request.method == "GET":
        conversation_id = query.get("conversationId")
        if conversation_id:
            try:
                return _result(repo.messages(owner, conversation_id,
                                            cursor=query.get("cursor"),
                                            limit=_integer(query.get("pageSize"), 25)))
            except KeyError:
                _not_found()
        if query.get("search"):
            return _result({"messages": repo.search_messages(owner, query["search"],
                                                                _integer(query.get("pageSize"), 25)),
                            "nextCursor": None})
        raise HTTPException(400, detail="Provide conversationId or search")
    raise HTTPException(405)


async def conversation_messages(request: Request):
    import sqlite3

    owner = _owner(request)
    repo = _repo()
    conversation_id = request.path_params["conversation_id"]
    if request.method == "GET":
        try:
            # The original LibreChat GET /api/messages/:conversationId endpoint
            # returns an array, unlike the paginated GET /api/messages query.
            pages = []
            cursor = None
            while True:
                page = repo.messages(owner, conversation_id, limit=200, cursor=cursor)
                pages.append(page["messages"])
                cursor = page["nextCursor"]
                if cursor is None:
                    break
            return _result([message for page in reversed(pages) for message in page])
        except KeyError:
            _not_found()
    payload = await _body(request)
    try:
        return _result(repo.add_message(owner, conversation_id, payload), status=201)
    except KeyError:
        _not_found()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail="Duplicate message or conflicting parent") from exc


async def projects(request: Request):
    owner = _owner(request)
    repo = _repo()
    if request.method == "GET":
        return _result(repo.projects(owner, limit=_integer(request.query_params.get("limit")),
                                     search=request.query_params.get("search")))
    data = await _body(request)
    try:
        result = repo.create_project(owner, str(data.get("name") or ""),
                                     str(data.get("description") or ""),
                                     **{k: v for k, v in data.items() if k not in {"name", "description"}})
        return _result(result, status=201)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


async def project(request: Request):
    owner = _owner(request)
    project_id = request.path_params["project_id"]
    repo = _repo()
    if request.method == "GET":
        result = repo.project(owner, project_id)
    elif request.method == "DELETE":
        if not repo.delete_project(owner, project_id):
            _not_found()
        return _result({"deleted": True})
    else:
        try:
            result = repo.update_project(owner, project_id, await _body(request))
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
    if result is None:
        _not_found()
    return _result(result)


async def assign_project(request: Request):
    owner = _owner(request)
    repo = _repo()
    payload = await _body(request)
    conversation_id = request.path_params["conversation_id"]
    project_id = payload.get("projectId")
    if project_id is not None and repo.project(owner, str(project_id)) is None:
        _not_found()
    result = repo.update_conversation(owner, conversation_id, {"projectId": project_id})
    if result is None:
        _not_found()
    return _result(result)


async def message_search(request: Request):
    owner = _owner(request)
    query = request.query_params.get("q", "")
    return _result({"messages": _repo().search_messages(owner, query,
                      limit=_integer(request.query_params.get("limit"))), "nextCursor": None})


def webui_routes() -> list[Route]:
    from .artifact_routes import artifact_routes

    return [
        *artifact_routes(),
        Route("/api/convos", conversations, methods=["GET", "POST", "PUT", "DELETE"]),
        Route("/api/convos/{conversation_id}", conversation, methods=["GET", "PUT", "PATCH", "DELETE"]),
        Route("/api/messages", messages, methods=["GET"]),
        Route("/api/messages/{conversation_id}", conversation_messages, methods=["GET", "POST"]),
        Route("/api/projects", projects, methods=["GET", "POST"]),
        Route("/api/projects/conversations/{conversation_id}", assign_project, methods=["PUT"]),
        Route("/api/projects/{project_id}", project, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/search/messages", message_search, methods=["GET"]),
    ]
