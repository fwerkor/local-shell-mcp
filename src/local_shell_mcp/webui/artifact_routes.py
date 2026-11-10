"""The retained React artifact editor's original message-update endpoint."""
from __future__ import annotations

import json
import re
import sqlite3

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .artifacts import edit_artifact
from .auth import _same_origin
from .routes import _body, _owner, _repo
from .storage import _json, _now


async def update_artifact(request: Request):
    owner = _owner(request)
    _same_origin(request)
    payload = await _body(request)
    index, original, updated = (payload.get(name) for name in ("index", "original", "updated"))
    if type(index) is not int or index < 0 or not isinstance(original, str) or not isinstance(updated, str):
        return JSONResponse({"error": "Invalid request parameters"}, status_code=400)
    repo = _repo()
    try:
        return _update(repo, owner, request.path_params["message_id"], index, original, updated)
    except sqlite3.Error:
        return JSONResponse({"error": "Internal server error"}, status_code=500)


def _update(repo, owner: str, message_id: str, index: int, original: str, updated: str):
    with repo.database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT m.*,c.metadata AS conversation_metadata FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                         "WHERE m.id=? AND c.owner=?", (message_id, owner)).fetchone()
        if row is None:
            return JSONResponse({"error": "Message not found"}, status_code=404)
        # The original immutable-child guard also reserves IDs before child
        # conversation creation finishes (agents/subagentThreadIds.ts).
        if (json.loads(row["conversation_metadata"]).get("subagentThread") is not None
                or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-8[0-9a-f]{3}-b[0-9a-f]{3}-[0-9a-f]{12}",
                                row["conversation_id"], re.IGNORECASE)):
            return JSONResponse({"error": "This subagent thread is view-only. Continue it from its parent agent or create a separate chat."}, status_code=409)
        try:
            value, _ = edit_artifact(repo._message(row), index, original, updated)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        metadata = json.loads(row["metadata"])
        metadata["userSubmittedPaths"] = value["userSubmittedPaths"]
        db.execute("UPDATE messages SET text=?,content=?,metadata=?,updated_at=? WHERE id=?",
                   (value["text"], _json(value.get("content") or {}), _json(metadata), _now(), row["id"]))
        response = {"conversationId": value["conversationId"], "text": value["text"]}
        if "content" in value:
            response["content"] = value["content"]
        return JSONResponse(response)


def artifact_routes() -> list[Route]:
    return [Route("/api/messages/artifact/{message_id}", update_artifact, methods=["POST"])]
