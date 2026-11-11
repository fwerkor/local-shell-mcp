"""File-backed tool attachments using LibreChat's canonical file metadata.

Source contract: LibreChat v0.8.8 api/server/controllers/agents/callbacks.js
writeAttachment/createToolEndCallback. An association is not a new file,
nor may untrusted tool output claim a file from another user or run.
"""
from __future__ import annotations

import json
from pathlib import Path

from .storage import _json, _now

_MAX_PREVIEW_BYTES = 128 * 1024
_STATUS = frozenset({"pending", "ready", "failed"})


def _attachment(row, message_id, tool_call_id, conversation_id):
    from .attachments import file_record

    return {
        **file_record(row),
        "messageId": message_id,
        "toolCallId": tool_call_id,
        "conversationId": conversation_id,
    }


def response_attachments(db, owner: str, message_ids):
    """Read canonical live file records, not stale message metadata snapshots."""
    ids = list(dict.fromkeys(message_ids))
    if not ids:
        return {}
    rows = db.execute(
        "SELECT l.response_message_id,l.tool_call_id,r.conversation_id,f.* "
        "FROM tool_attachment_links l JOIN runs r ON r.id=l.run_id "
        "JOIN conversations c ON c.id=r.conversation_id "
        "JOIN attachments f ON f.id=l.file_id AND f.owner=c.owner "
        "WHERE c.owner=? AND l.response_message_id IN (" + ",".join("?" for _ in ids) + ") "
        "ORDER BY l.rowid", (owner, *ids),
    ).fetchall()
    collected = {ident: [] for ident in ids}
    for row in rows:
        collected[row["response_message_id"]].append(_attachment(
            row, row["response_message_id"], row["tool_call_id"], row["conversation_id"],
        ))
    return collected


def controller_tool_file_ids(output):
    """Source artifact.files only; never infer ownership from arbitrary paths.

    The native LSM tool executor returns JSON-serialized structured MCP data.
    File bytes must already have been published into Controller metadata; code
    environment IDs / raw paths are not treated as Controller file references.
    """
    if isinstance(output, str):
        if len(output) > 256 * 1024:
            return []
        try:
            output = json.loads(output)
        except ValueError:
            return []
    if not isinstance(output, dict):
        return []
    if "artifact" not in output and isinstance(output.get("data"), dict):
        output = output["data"]
    artifact = output.get("artifact")
    if not isinstance(artifact, dict) or not isinstance(artifact.get("files"), list):
        return []
    identities = []
    for entry in artifact["files"][:16]:
        if not isinstance(entry, dict):
            continue
        ident = entry.get("file_id")
        if isinstance(ident, str) and ident and len(ident) <= 200 and ident not in identities:
            identities.append(ident)
    return identities


def link_tool_attachment(database, owner: str, run_id: str, tool_call_id: str, file_id: str):
    """Register a *previously owned* Controller file to an actual emitted call.

    The graph's run and its persisted tool call must both exist; a caller
    cannot create an attachment for a forged messageId or a different owner.
    Returns None on an idempotent repeat without duplicating SSE events.
    """
    if any(not isinstance(value, str) or not value or len(value) > 200
           for value in (run_id, tool_call_id, file_id)):
        raise ValueError("Invalid tool attachment identity")
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        run = db.execute(
            "SELECT r.*,c.owner FROM runs r JOIN conversations c ON c.id=r.conversation_id "
            "WHERE r.id=? AND c.owner=? AND r.status='running'",
            (run_id, owner),
        ).fetchone()
        if run is None:
            raise PermissionError("Tool attachment run is not active or owned")
        matching_call = False
        for event in db.execute(
            "SELECT data FROM generation_events WHERE run_id=? "
            "AND json_extract(data,'$.event')='on_run_step'", (run_id,),
        ):
            value = json.loads(event["data"]).get("data", {})
            calls = value.get("stepDetails", {}).get("tool_calls", [])
            if any(isinstance(call, dict) and call.get("id") == tool_call_id for call in calls):
                matching_call = True
                break
        if not matching_call:
            raise PermissionError("Tool call does not belong to the run")
        file = db.execute("SELECT * FROM attachments WHERE id=? AND owner=?",
                          (file_id, owner)).fetchone()
        if file is None:
            raise PermissionError("Unowned or deleted Controller file")
        path = Path(file["path"])
        root = database.root.resolve() / "attachments"
        if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
            raise OSError("Controller attachment is unavailable")
        response_id = json.loads(run["state"])["responseMessageId"]
        inserted = db.execute(
            "INSERT OR IGNORE INTO tool_attachment_links(run_id,response_message_id,tool_call_id,file_id) "
            "VALUES(?,?,?,?)", (run_id, response_id, tool_call_id, file_id),
        )
        if not inserted.rowcount:
            return None
        record = _attachment(file, response_id, tool_call_id, run["conversation_id"])
        # Write the association and replayable event in one SQLite transaction.
        db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                   (run_id, _json({"event": "attachment", "data": record})))
        return record


def update_attachment_preview(database, owner: str, file_id: str, status: str, *,
                              text: str | None = None, text_format: str | None = None,
                              error: str | None = None):
    """Publish pending -> ready/failed and persist updates after SSE closes."""
    if status not in _STATUS or not isinstance(file_id, str) or not file_id:
        raise ValueError("Invalid file preview")
    # Upstream HTML previews pass through a sanitizing renderer. Until that
    # pipeline is available, never label arbitrary tool text as trusted HTML.
    if text_format not in {None, "text"}:
        raise ValueError("Invalid preview text format")
    if text is not None and (
        not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_PREVIEW_BYTES
    ):
        raise ValueError("Preview text exceeds limit")
    if status != "ready" and text is not None:
        raise ValueError("Preview content requires ready status")
    if status == "failed" and (not isinstance(error, str) or error not in {
        "timeout", "parser-error", "orphaned", "unsupported",
    }):
        raise ValueError("Invalid preview error code")
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM attachments WHERE id=? AND owner=?",
                         (file_id, owner)).fetchone()
        if row is None:
            raise KeyError("Attachment not found")
        metadata = json.loads(row["metadata"])
        previous = metadata.get("status")
        if previous in {"ready", "failed"} and status == "pending":
            raise ValueError("Cannot revert a terminal preview to pending")
        if previous == "failed" and status == "ready":
            raise ValueError("Cannot overwrite a failed preview")
        metadata["status"] = status
        metadata.pop("text", None)
        metadata.pop("textFormat", None)
        metadata.pop("previewError", None)
        if status == "ready" and text is not None:
            metadata.update(text=text, textFormat=text_format or "text")
        if status == "failed":
            metadata["previewError"] = error
        db.execute("UPDATE attachments SET metadata=? WHERE id=?", (_json(metadata), file_id))
        events = []
        links = db.execute(
            "SELECT l.run_id,l.response_message_id,l.tool_call_id,r.conversation_id,r.status "
            "FROM tool_attachment_links l JOIN runs r ON r.id=l.run_id "
            "WHERE l.file_id=?", (file_id,),
        ).fetchall()
        updated_file = db.execute("SELECT * FROM attachments WHERE id=?", (file_id,)).fetchone()
        for link in links:
            record = _attachment(
                updated_file, link["response_message_id"], link["tool_call_id"],
                link["conversation_id"],
            )
            events.append(record)
            if link["status"] == "running":
                db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                           (link["run_id"], _json({"event": "attachment", "data": record})))
            else:
                # History consumers read the file's current status through the
                # live link table; don't publish into a completed SSE stream.
                message = db.execute(
                    "SELECT metadata FROM messages WHERE id=? AND conversation_id=?",
                    (link["response_message_id"], link["conversation_id"]),
                ).fetchone()
                if message:
                    snapshot = json.loads(message["metadata"])
                    attachment_list = snapshot.get("attachments") or []
                    attachment_list = [
                        entry for entry in attachment_list if not (
                            entry.get("file_id") == file_id and
                            entry.get("toolCallId") == link["tool_call_id"])
                    ]
                    snapshot["attachments"] = [*attachment_list, record]
                    db.execute("UPDATE messages SET metadata=?,updated_at=? WHERE id=?",
                               (_json(snapshot), _now(), link["response_message_id"]))
        return events
