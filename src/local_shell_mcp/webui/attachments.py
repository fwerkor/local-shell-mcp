"""Authenticated chat attachments stored within LSM's private state tree.

The React workspace uploads directly to the Controller. File bytes stay under
`.local-shell-mcp/attachments`; SQLite holds the owner-scoped metadata. The
old unreleased LibreChat staging directory and external bridge are unused.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .routes import _owner, _repo

MAX_ATTACHMENT_BYTES = 32 * 1024 * 1024
log = logging.getLogger(__name__)


def _safe_attachment_path(owner: str, filename: str, state_dir: Path) -> Path:
    if not isinstance(filename, str) or not 1 <= len(filename) <= 200:
        raise ValueError("Invalid attachment filename")
    name = filename.replace("\\", "/").split("/")[-1]
    if name in {"", ".", ".."} or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise ValueError("Invalid attachment filename")
    root = state_dir.resolve()
    recipient = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:32]
    parent = root / "attachments" / recipient
    if root not in parent.resolve().parents:
        raise PermissionError("Unsafe attachment directory")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.is_symlink():
        raise PermissionError("Attachment directory cannot be a symlink")
    return parent / (uuid.uuid4().hex + "-" + name)


async def upload_attachment(request: Request):
    from ..human_ui import _require_ui_scopes
    from ..settings import get_settings

    owner = _owner(request)
    _require_ui_scopes(request, "shell:read", "shell:write")
    settings = get_settings()
    if settings.disable_local:
        raise HTTPException(403, detail="Local workspace attachments are disabled")
    try:
        length = int(request.headers.get("content-length") or "-1")
    except ValueError as exc:
        raise HTTPException(400, detail="A valid content length is required") from exc
    if not 0 < length <= MAX_ATTACHMENT_BYTES:
        raise HTTPException(400, detail="Attachment must be between 1 byte and 32 MiB")
    try:
        name = request.query_params.get("name", "")
        _safe_attachment_path(owner, name, settings.state_dir)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    record = await publish_attachment(owner, name, request.headers.get("content-type") or "application/octet-stream",
                                      request.stream(), settings.state_dir, expected_size=length)
    return JSONResponse({"ok": True, "data": {
        "machine": "local", "path": record["path"], "size": record["bytes"], "file_id": record["file_id"],
    }})


async def publish_attachment(owner, name, content_type, chunks, state_dir, *, expected_size=None,
                             file_id=None, metadata=None, bind=None):
    """One safe physical publisher shared by native and original React uploads."""
    try:
        target = _safe_attachment_path(owner, name, state_dir)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    file_id = file_id or "file_" + uuid.uuid4().hex
    descriptor = None
    published = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(target, flags, 0o600)
        received = 0
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            async for chunk in chunks:
                received += len(chunk)
                if received > MAX_ATTACHMENT_BYTES:
                    raise ValueError("Attachment exceeds 32 MiB")
                if expected_size is not None and received > expected_size:
                    raise ValueError("Attachment exceeds declared content length")
                await asyncio.to_thread(handle.write, chunk)
            if received == 0 or expected_size is not None and received != expected_size:
                raise ValueError("Incomplete attachment upload")
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
        if len(content_type) > 256:
            content_type = "application/octet-stream"
        values = {**(metadata or {}), "bytes": received, "machine": "local"}
        with _repo().database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
                (file_id, owner, name.replace("\\", "/").split("/")[-1], str(target), content_type,
                 json.dumps(values, ensure_ascii=False)),
            )
            if bind is not None:
                bind(db, file_id)
        published = True
        return {"file_id": file_id, "path": str(target), "bytes": received}
    except asyncio.CancelledError:
        raise
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except OSError:
        log.exception("WebUI attachment storage failure")
        raise HTTPException(500, detail="Unable to store attachment") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not published:
            target.unlink(missing_ok=True)



def file_record(row):
    """Original React file DTO; physical paths stay in owner-scoped SQLite."""
    return {**json.loads(row["metadata"]), "file_id": row["id"], "filename": row["name"],
            "type": row["content_type"], "filepath": "/api/files/download/" + row["id"],
            "source": "local", "createdAt": row["created_at"],
            "conversationId": row["conversation_id"]}


def resolve_files(db, owner, files):
    if not isinstance(files, list) or len(files) > 32:
        raise ValueError("Invalid attachment list")
    records = []
    seen = set()
    for value in files:
        ident = value.get("file_id") if isinstance(value, dict) else None
        if not isinstance(ident, str) or not ident:
            raise ValueError("Invalid attachment id")
        if ident in seen:
            continue
        row = db.execute("SELECT * FROM attachments WHERE id=? AND owner=?", (ident, owner)).fetchone()
        if row is None:
            raise KeyError("Attachment not found")
        records.append(file_record(row))
        seen.add(ident)
    return records


async def upload_react_file(request: Request):
    from starlette.datastructures import UploadFile
    from starlette.formparsers import MultiPartException, MultiPartParser

    from ..human_ui import _require_ui_scopes
    from ..settings import get_settings

    owner = _owner(request)
    _require_ui_scopes(request, "shell:read", "shell:write")
    settings = get_settings()
    if settings.disable_local:
        raise HTTPException(403, detail="Local workspace attachments are disabled")
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(400, detail="A multipart file upload is required")

    async def bounded():
        count = 0
        async for chunk in request.stream():
            count += len(chunk)
            if count > MAX_ATTACHMENT_BYTES + 65536:
                raise MultiPartException("Attachment exceeds 32 MiB")
            yield chunk

    form = None
    parser = MultiPartParser(request.headers, bounded(), max_files=1, max_fields=16, max_part_size=16384)
    try:
        form = await parser.parse()
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or sum(isinstance(v, UploadFile) for _, v in form.multi_items()) != 1:
            raise HTTPException(400, detail="Exactly one file is required")
        # Agent resource registration is a distinct write contract. Reject it until
        # its versioned Agent update can commit atomically with publication.
        if (form.get("agent_id") or form.get("tool_resource")) and form.get("message_file") != "true":
            raise HTTPException(400, detail="Agent resource uploads are not available")
        temp_id = form.get("file_id")
        if temp_id is not None and (not isinstance(temp_id, str) or len(temp_id) > 200):
            raise HTTPException(400, detail="Invalid temporary file id")

        async def chunks():
            while chunk := await upload.read(65536):
                yield chunk

        from urllib.parse import unquote

        record = await publish_attachment(owner, unquote(upload.filename or ""), upload.content_type or
                    "application/octet-stream", chunks(), settings.state_dir,
                    file_id=str(uuid.uuid4()), metadata={"temp_file_id": temp_id, "context": "message_attachment"})
        with _repo().database.connect() as db:
            row = db.execute("SELECT * FROM attachments WHERE id=? AND owner=?", (record["file_id"], owner)).fetchone()
        return JSONResponse({"message": "Agent file uploaded and processed successfully", **file_record(row)})
    except MultiPartException as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    finally:
        if form is not None:
            await form.close()
        else:
            for handle in parser._files_to_close_on_error:
                handle.close()


async def download_react_file(request: Request):
    from ..human_ui import _require_ui_scopes
    from ..settings import get_settings

    owner = _owner(request)
    _require_ui_scopes(request, "shell:read")
    with _repo().database.connect() as db:
        row = db.execute("SELECT * FROM attachments WHERE id=? AND owner=?",
                         (request.path_params["file_id"], owner)).fetchone()
    if row is None:
        raise HTTPException(404, detail="Attachment not found")
    path = Path(row["path"])
    root = get_settings().state_dir.resolve() / "attachments"
    if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
        raise HTTPException(404, detail="Attachment not found")
    return FileResponse(path, media_type="application/octet-stream", filename=row["name"],
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})

def attachment_routes() -> list[Route]:
    return [
        Route("/api/files", upload_react_file, methods=["POST"]),
        Route("/api/files/images", upload_react_file, methods=["POST"]),
        Route("/api/files/download/{file_id}", download_react_file, methods=["GET"]),
        Route("/api/lsm/controller/attachments/upload", upload_attachment, methods=["POST"]),
    ]
