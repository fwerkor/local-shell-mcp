"""Authenticated chat attachments stored within LSM's private state tree.

The React workspace uploads directly to the Controller. File bytes stay under
`.local-shell-mcp/attachments`; SQLite holds the owner-scoped metadata. The
old unreleased LibreChat staging directory and external bridge are unused.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
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
        target = _safe_attachment_path(owner, name, settings.state_dir)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    file_id = "file_" + uuid.uuid4().hex
    descriptor: int | None = None
    published = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(target, flags, 0o600)
        received = 0
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            async for chunk in request.stream():
                received += len(chunk)
                if received > length:
                    raise ValueError("Attachment exceeds declared content length")
                await asyncio.to_thread(handle.write, chunk)
            if received != length:
                raise ValueError("Incomplete attachment upload")
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
        content_type = request.headers.get("content-type") or "application/octet-stream"
        if len(content_type) > 256:
            content_type = "application/octet-stream"
        with _repo().database.connect() as db:
            db.execute(
                "INSERT INTO attachments(id,owner,name,path,content_type,metadata) "
                "VALUES(?,?,?,?,?,?)",
                (file_id, owner, name, str(target), content_type, "{}"),
            )
        published = True
        return JSONResponse({
            "ok": True,
            "data": {"machine": "local", "path": str(target), "size": received, "file_id": file_id},
        })
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


def attachment_routes() -> list[Route]:
    return [
        Route("/api/lsm/controller/attachments/upload", upload_attachment, methods=["POST"]),
    ]
