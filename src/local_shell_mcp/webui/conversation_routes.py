"""Persistent conversation lifecycle APIs used by the original React client."""

from __future__ import annotations

import uuid

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .routes import _body, _not_found, _owner, _repo
from .storage import _now


def _argument(body: dict) -> dict:
    source = body.get("arg") or body
    if not isinstance(source, dict):
        raise HTTPException(400, detail="Expected conversation argument")
    return source


def _conversation_id(values: dict) -> str:
    cid = values.get("conversationId")
    if not isinstance(cid, str) or not cid:
        raise HTTPException(400, detail="Conversation id is required")
    return cid


async def update_conversation(request: Request):
    owner = _owner(request)
    values = _argument(await _body(request))
    conversation_id = _conversation_id(values)
    repo = _repo()
    changes = {key: val for key, val in values.items() if key != "conversationId"}
    updated = repo.update_conversation(owner, conversation_id, changes)
    if updated is None:
        _not_found()
    return JSONResponse(updated)


async def archive_conversation(request: Request):
    owner = _owner(request)
    values = _argument(await _body(request))
    repo = _repo()
    updated = repo.update_conversation(owner, _conversation_id(values),
                                       {"isArchived": bool(values.get("isArchived", True))})
    if updated is None:
        _not_found()
    return JSONResponse(updated)


async def pin_conversation(request: Request):
    owner = _owner(request)
    values = _argument(await _body(request))
    repo = _repo()
    updated = repo.update_conversation(owner, _conversation_id(values),
                                       {"pinned": bool(values.get("pinned", True))})
    if updated is None:
        _not_found()
    return JSONResponse(updated)


async def archive_all(request: Request):
    owner = _owner(request)
    with _repo().database.connect() as db:
        changed = db.execute("UPDATE conversations SET archived=1,updated_at=? WHERE owner=? AND archived=0",
                             (_now(), owner)).rowcount
    return JSONResponse({"success": True, "modifiedCount": changed})


async def delete_all(request: Request):
    owner = _owner(request)
    with _repo().database.connect() as db:
        removed = db.execute("DELETE FROM conversations WHERE owner=?", (owner,)).rowcount
    return JSONResponse({"success": True, "deletedCount": removed})


def _clone(owner: str, values: dict, *, only_to_message: str | None = None) -> dict:
    repo = _repo()
    cid = _conversation_id(values)
    with repo.database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        source = db.execute("SELECT * FROM conversations WHERE id=? AND owner=?", (cid, owner)).fetchone()
        if source is None:
            raise HTTPException(404, detail="Conversation not found")
        messages = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id", (cid,)).fetchall()
        if only_to_message:
            by_id = {row["id"]: row for row in messages}
            selected: set[str] = set()
            cursor = only_to_message
            while cursor and cursor != "00000000-0000-0000-0000-000000000000":
                if cursor not in by_id:
                    raise HTTPException(404, detail="Target message not found")
                if cursor in selected:
                    raise HTTPException(409, detail="Message graph contains a cycle")
                selected.add(cursor)
                cursor = by_id[cursor]["parent_id"]
            messages = [row for row in messages if row["id"] in selected]
        new_cid = str(uuid.uuid4())
        now = _now()
        db.execute(
            "INSERT INTO conversations(id,owner,title,project_id,agent_id,model,endpoint,archived,pinned,metadata,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_cid, owner, values.get("title") or source["title"], source["project_id"],
             source["agent_id"], source["model"], source["endpoint"], 0, 0,
             source["metadata"], now, now),
        )
        ids = {row["id"]: str(uuid.uuid4()) for row in messages}
        for i, row in enumerate(messages):
            db.execute(
                "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (ids[row["id"]], new_cid, ids.get(row["parent_id"]), row["role"],
                 row["text"], row["content"], row["metadata"], now + i, now + i),
            )
        response = repo._convo(db.execute("SELECT * FROM conversations WHERE id=?", (new_cid,)).fetchone())
        response["messages"] = [repo._message(row) for row in db.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id", (new_cid,)
        ).fetchall()]
    return response


async def duplicate_conversation(request: Request):
    owner = _owner(request)
    values = await _body(request)
    result = _clone(owner, values)
    return JSONResponse(result, status_code=201)


async def fork_conversation(request: Request):
    owner = _owner(request)
    values = await _body(request)
    target = values.get("targetMessageId") or values.get("messageId")
    if not isinstance(target, str) or not target:
        raise HTTPException(400, detail="Target message id is required")
    result = _clone(owner, values, only_to_message=target)
    return JSONResponse(result, status_code=201)


async def generate_title(request: Request):
    owner = _owner(request)
    cid = request.path_params["conversation_id"]
    result = _repo().conversation(owner, cid)
    if result is None:
        _not_found()
    return JSONResponse({"title": result.get("title") or "New chat", "conversationId": cid})


def conversation_routes() -> list[Route]:
    return [
        Route("/api/convos/update", update_conversation, methods=["POST"]),
        Route("/api/convos/archive", archive_conversation, methods=["POST"]),
        Route("/api/convos/archive/all", archive_all, methods=["POST"]),
        Route("/api/convos/pin", pin_conversation, methods=["POST"]),
        Route("/api/convos/all", delete_all, methods=["DELETE"]),
        Route("/api/convos/duplicate", duplicate_conversation, methods=["POST"]),
        Route("/api/convos/fork", fork_conversation, methods=["POST"]),
        Route("/api/convos/gen_title/{conversation_id}", generate_title, methods=["GET"]),
    ]
