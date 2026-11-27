"""Persistent conversation lifecycle APIs used by the original React client."""

from __future__ import annotations

import json
import uuid

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .routes import _body, _not_found, _owner, _repo
from .storage import _json, _now


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
    if "lsmSampling" in changes:
        from .sampling import validate_channel_sampling

        try:
            conversation = repo.conversation(owner, conversation_id)
            if conversation is None:
                _not_found()
            channel = changes.get('endpoint') or conversation.get('endpoint')
            changes["lsmSampling"] = validate_channel_sampling(changes["lsmSampling"], channel)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
    updated = repo.update_conversation(owner, conversation_id, changes)
    if updated is not None and "projectId" in changes:
        from .durable_tasks import mark_revoked

        mark_revoked(owner)
    if updated is None:
        _not_found()
    return JSONResponse(updated)


async def conversation_unread(request: Request):
    """One owner-scoped unread snapshot; read acknowledgments never clear newer results."""
    owner = _owner(request)
    with _repo().database.connect() as db:
        if request.method == "GET":
            rows = db.execute(
                "SELECT id,unread_marker FROM conversations WHERE owner=? AND unread_marker IS NOT NULL",
                (owner,),
            )
            return JSONResponse({"unread": {row["id"]: row["unread_marker"] for row in rows}})
        values = await _body(request)
        conversation_id = _conversation_id(values)
        unread = values.get("unread")
        expected = values.get("expected")
        if type(unread) is not bool or (expected is not None and not isinstance(expected, str)):
            raise HTTPException(400, detail="Invalid unread state")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT unread_marker FROM conversations WHERE id=? AND owner=?",
                         (conversation_id, owner)).fetchone()
        if row is None:
            _not_found()
        marker = row["unread_marker"]
        if unread:
            marker = "manual:" + uuid.uuid4().hex
        elif expected is None or expected == marker:
            marker = None
        db.execute("UPDATE conversations SET unread_marker=? WHERE id=? AND owner=?",
                   (marker, conversation_id, owner))
        return JSONResponse({"conversationId": conversation_id, "marker": marker})


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
    if removed:
        from .durable_tasks import mark_revoked

        mark_revoked(owner)
    return JSONResponse({"success": True, "deletedCount": removed})


def _clone_attachment_links(db, owner: str, source_id: str, new_id: str,
                            messages, identities: dict[str, str], now: int) -> None:
    """Carry live, owner-checked file references over to a new message graph.

    Cloned messages get new IDs, so original run-linked references cannot be
    reused. Completed provenance runs hold the copied links without replaying
    the source generation or changing the original run's identity.
    """
    assistants = [row["id"] for row in messages if row["role"] == "assistant"]
    if not assistants:
        return
    links = db.execute(
        "SELECT l.run_id,l.response_message_id,l.tool_call_id,l.file_id,r.agent_id,r.state "
        "FROM tool_attachment_links l JOIN runs r ON r.id=l.run_id "
        "JOIN attachments a ON a.id=l.file_id AND a.owner=? "
        "WHERE r.conversation_id=? AND l.response_message_id IN ("
        + ",".join("?" for _ in assistants) + ") ORDER BY l.rowid",
        (owner, source_id, *assistants),
    ).fetchall()
    runs: dict[tuple[str, str], str] = {}
    for link in links:
        key = (link["run_id"], link["response_message_id"])
        run_id = runs.get(key)
        if run_id is None:
            run_id = str(uuid.uuid4())
            runs[key] = run_id
            original_state = json.loads(link["state"])
            new_response_id = identities[link["response_message_id"]]
            new_user_id = identities.get(original_state.get("userMessageId")) or next(
                (identities[row["id"]] for row in messages if row["role"] == "user"), new_response_id,
            )
            # GenerationStore.latest/get must be able to decode every run,
            # including completed provenance-only runs in cloned chats.
            clone_state = {
                "responseMessageId": new_response_id, "userMessageId": new_user_id,
                "generationCreatedAt": now // 1000, "generationProtocolVersion":
                original_state.get("generationProtocolVersion", 2),
            }
            db.execute(
                "INSERT INTO runs(id,conversation_id,agent_id,status,state,created_at,updated_at) "
                "VALUES(?,?,?,'complete',?,?,?)",
                (run_id, new_id, link["agent_id"], _json(clone_state), now, now),
            )
        db.execute(
            "INSERT INTO tool_attachment_links(run_id,response_message_id,tool_call_id,file_id) "
            "VALUES(?,?,?,?)",
            (run_id, identities[link["response_message_id"]], link["tool_call_id"], link["file_id"]),
        )


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
            metadata = json.loads(row["metadata"])
            if isinstance(metadata.get("attachments"), list):
                # Client UI resources resolve through message-level attachments.
                # Their clone must be owned by the copied message/conversation.
                metadata["attachments"] = [
                    {**item, "messageId": ids[row["id"]], "conversationId": new_cid}
                    if isinstance(item, dict) else item
                    for item in metadata["attachments"]
                ]
            db.execute(
                "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (ids[row["id"]], new_cid, ids.get(row["parent_id"]), row["role"],
                 row["text"], row["content"], _json(metadata), now + i, now + i),
            )
        for original_id, copied_id in ids.items():
            db.execute("INSERT INTO webui_manual_skill_contexts(message_id,content) "
                       "SELECT ?,content FROM webui_manual_skill_contexts WHERE message_id=?",
                       (copied_id, original_id))
        # Canonical model steps are stored in runs.state, not React preview
        # messages. Copy only terminal runs whose assistant is in the selected
        # branch; preserve content and provider signatures without aliasing
        # generation identity, conversation owner or the original run.
        for original_id, copied_id in ids.items():
            message = next(row for row in messages if row["id"] == original_id)
            if message["role"] != "assistant":
                continue
            prior_runs = db.execute(
                "SELECT * FROM runs WHERE conversation_id=? AND "
                "json_extract(state,'$.responseMessageId')=? AND "
                "status IN ('complete','aborted','error','interrupted') "
                "ORDER BY created_at DESC LIMIT 1", (cid, original_id),
            ).fetchone()
            if prior_runs is None:
                continue
            state = json.loads(prior_runs["state"])
            state["responseMessageId"] = copied_id
            state["userMessageId"] = ids.get(state["userMessageId"], state["userMessageId"])
            state.pop("clientRequestId", None)
            state["generationCreatedAt"] = now // 1000
            db.execute(
                "INSERT INTO runs(id,conversation_id,agent_id,status,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                ("run_" + uuid.uuid4().hex, new_cid, prior_runs["agent_id"],
                 prior_runs["status"], _json(state), now, now),
            )
        _clone_attachment_links(db, owner, cid, new_cid, messages, ids, now)
        response = repo._convo(db.execute("SELECT * FROM conversations WHERE id=?", (new_cid,)).fetchone())
        from .tool_attachments import response_attachments, visible_response_attachments

        cloned_rows = db.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id", (new_cid,)
        ).fetchall()
        live = response_attachments(db, owner, [row["id"] for row in cloned_rows if row["role"] == "assistant"])
        response["messages"] = []
        for row in cloned_rows:
            message = repo._message(row)
            if row["role"] == "assistant" and (row["id"] in live or "attachments" in message):
                message["attachments"] = visible_response_attachments(
                    live.get(row["id"], []), message.get("attachments"))
            response["messages"].append(message)
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
        Route("/api/convos/unread", conversation_unread, methods=["GET", "POST"]),
        Route("/api/convos/update", update_conversation, methods=["POST"]),
        Route("/api/convos/archive", archive_conversation, methods=["POST"]),
        Route("/api/convos/archive/all", archive_all, methods=["POST"]),
        Route("/api/convos/pin", pin_conversation, methods=["POST"]),
        Route("/api/convos/all", delete_all, methods=["DELETE"]),
        Route("/api/convos/duplicate", duplicate_conversation, methods=["POST"]),
        Route("/api/convos/fork", fork_conversation, methods=["POST"]),
        Route("/api/convos/gen_title/{conversation_id}", generate_title, methods=["GET"]),
    ]
