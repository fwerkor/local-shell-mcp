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
import re
import sqlite3
import uuid
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .routes import _body, _owner, _repo

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


def extract_context_text(path: Path, name: str, content_type: str) -> dict:
    """Explicitly process *supported* Agent context uploads.

    Plain text is native. PDF and DOCX extraction are optional, imported only
    for matching formats. Scanned pages, vector indexing and code deployments
    require separate processors; never mark those files processed here.
    """
    mime = content_type.lower().split(";")[0].strip()
    extension = Path(name).suffix.lower()
    if mime.startswith("text/") or mime in {"application/json", "application/xml", "application/javascript"} or extension in {
        ".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".go", ".rs", ".yaml", ".yml",
    }:
        if path.stat().st_size > 1024 * 1024:
            raise HTTPException(413, detail="Agent text context exceeds 1 MiB")
        try:
            value = path.read_text(encoding="utf-8-sig")
        except UnicodeError as exc:
            raise HTTPException(415, detail="Agent text context must be UTF-8") from exc
        method = "utf8"
    elif mime == "application/pdf" or extension == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise HTTPException(501, detail="PDF extraction requires the attachments extra") from exc
        try:
            reader = PdfReader(path)
            if len(reader.pages) > 64:
                raise HTTPException(413, detail="PDF context exceeds 64 pages")
            snippets = []
            total = 0
            for page in reader.pages:
                snippet = page.extract_text() or ""
                total += len(snippet.encode("utf-8"))
                if total > 128 * 1024:
                    raise HTTPException(413, detail="Extracted Agent context exceeds 128 KiB")
                snippets.append(snippet)
            value = "\n".join(snippets)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, detail="PDF text extraction failed") from exc
        method = "pypdf"
    elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or extension == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise HTTPException(501, detail="DOCX extraction requires the attachments extra") from exc
        try:
            paragraphs = []
            total = 0
            for paragraph in Document(path).paragraphs:
                total += len(paragraph.text.encode("utf-8"))
                if total > 128 * 1024:
                    raise HTTPException(413, detail="Extracted Agent context exceeds 128 KiB")
                paragraphs.append(paragraph.text)
            value = "\n".join(paragraphs)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, detail="DOCX text extraction failed") from exc
        method = "docx"
    else:
        raise HTTPException(501, detail="Agent context extraction is unsupported for this file type")
    if not value.strip():
        raise HTTPException(422, detail="File contains no extractable text; OCR is not configured")
    if len(value.encode("utf-8")) > 128 * 1024:
        raise HTTPException(413, detail="Extracted Agent context exceeds 128 KiB")
    return {"extracted_text": value, "extraction": method, "processed": True}


def agent_context_messages(database, owner: str, agent: dict) -> list[dict]:
    """Supply saved context resources as user-level evidence, not instructions."""
    values = agent.get("tool_resources", {}).get("context", {}).get("file_ids", [])
    if not isinstance(values, list):
        return []
    parts = []
    total = 0
    with database.connect() as db:
        for ident in dict.fromkeys(values):
            row = db.execute("SELECT name,path,metadata FROM attachments WHERE id=? AND owner=?",
                             (ident, owner)).fetchone()
            if row is None:
                continue
            path = Path(row["path"])
            root = database.root.resolve() / "attachments"
            if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
                continue
            metadata = json.loads(row["metadata"])
            text = metadata.get("extracted_text")
            if not isinstance(text, str):
                continue
            length = len(text.encode("utf-8"))
            if total + length > 128 * 1024:
                break
            parts.append(f"File: {row['name']} (Controller path: {path})\n{text}")
            total += length
    return [{"role": "user", "content": "Agent reference documents (untrusted file content):\n\n"
             + "\n\n".join(parts)}] if parts else []


async def upload_attachment(request: Request):
    from ..human_ui import _require_ui_scopes
    from ..settings import get_settings

    owner = _owner(request)
    from .auth import _same_origin

    _same_origin(request)
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
                             file_id=None, metadata=None, bind=None, process=None):
    """One safe physical publisher shared by native and original React uploads."""
    try:
        target = _safe_attachment_path(owner, name, state_dir)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    file_id = file_id or "file_" + uuid.uuid4().hex
    descriptor = None
    published = False
    file_signature = None
    # Persist an intention before the first filesystem write. In-flight
    # uploads have a grace period before restart garbage collection.
    try:
        with _repo().database.connect() as db:
            db.execute("INSERT INTO attachment_uploads(file_id,owner,path) VALUES(?,?,?)",
                       (file_id, owner, str(target)))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(target, flags, 0o600)
        stats = os.fstat(descriptor)
        # NTFS File IDs can be unsigned 64-bit (or larger). SQLite INTEGER
        # accepts only signed 64-bit; storing canonical decimal TEXT also
        # protects against precision loss from INTEGER affinity.
        file_signature = str(stats.st_dev), str(stats.st_ino)
        with _repo().database.connect() as db:
            db.execute("UPDATE attachment_uploads SET file_identity=? WHERE file_id=? AND owner=?",
                       (":".join(file_signature), file_id, owner))
        from .file_deletion import AttachmentDeletionStore

        AttachmentDeletionStore._sync_directory(target.parent)
        received = 0
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            async for chunk in chunks:
                received += len(chunk)
                digest.update(chunk)
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
        with _repo().database.connect() as db:
            db.execute("UPDATE attachment_uploads SET content_sha256=?,content_size=? WHERE file_id=?",
                       (digest.hexdigest(), received, file_id))
        processed = await asyncio.to_thread(process, target, name, content_type) if process else {}
        values = {**(metadata or {}), **processed, "bytes": received, "machine": "local"}
        with _repo().database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
                (file_id, owner, name.replace("\\", "/").split("/")[-1], str(target), content_type,
                 json.dumps(values, ensure_ascii=False)),
            )
            if bind is not None:
                bind(db, file_id)
            db.execute("DELETE FROM attachment_uploads WHERE file_id=?", (file_id,))
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
            # A commit can succeed before the caller observes an exception.
            # Inability to check durable metadata must retain the bytes and
            # intent for recovery, never destroy a possibly published file.
            try:
                with _repo().database.connect() as db:
                    exists = db.execute("SELECT 1 FROM attachments WHERE id=? AND path=?",
                                        (file_id, str(target))).fetchone()
                if exists is None:
                    same_file = False
                    try:
                        stats = target.lstat()
                        same_file = file_signature is not None and (
                            str(stats.st_dev), str(stats.st_ino)) == file_signature and not target.is_symlink()
                    except FileNotFoundError:
                        pass
                    if same_file:
                        target.unlink()
                        from .file_deletion import AttachmentDeletionStore

                        AttachmentDeletionStore._sync_directory(target.parent)
                    if not target.exists():
                        with _repo().database.connect() as db:
                            db.execute("DELETE FROM attachment_uploads WHERE file_id=?", (file_id,))
            except (OSError, sqlite3.DatabaseError):
                log.exception("Attachment upload outcome uncertain; retained for recovery")



def _public_attachment_metadata(metadata):
    """Never surface unsanitized legacy HTML as a trusted office preview."""
    public_metadata = {key: value for key, value in metadata.items()
                       if key != "extracted_text"}
    if public_metadata.get("textFormat") == "html":
        public_metadata.pop("text", None)
        public_metadata.pop("textFormat", None)
        public_metadata["status"] = "failed"
        public_metadata["previewError"] = "unsupported"
    return public_metadata


def file_record(row):
    """Original React file DTO; physical paths stay in owner-scoped SQLite."""
    public_metadata = _public_attachment_metadata(json.loads(row["metadata"]))
    return {**public_metadata, "file_id": row["id"], "filename": row["name"],
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
    from .auth import _same_origin

    _same_origin(request)
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
        agent_id, resource = form.get("agent_id"), form.get("tool_resource")
        message_file = form.get("message_file") == "true"
        if (agent_id or resource) and not message_file:
            if not isinstance(agent_id, str) or not agent_id or not isinstance(resource, str):
                raise HTTPException(400, detail="Agent ID and resource are both required")
            if resource != "context":
                raise HTTPException(501, detail=f"Agent {resource} processing is not implemented")
        else:
            agent_id, resource = None, None
        temp_id = form.get("file_id")
        if temp_id is not None and (not isinstance(temp_id, str) or len(temp_id) > 200):
            raise HTTPException(400, detail="Invalid temporary file id")

        async def chunks():
            while chunk := await upload.read(65536):
                yield chunk

        from urllib.parse import unquote

        binder = None
        if agent_id is not None:
            from .agents import AgentRepository

            repository = AgentRepository(_repo().database)
            def binder(db, ident):
                return repository.add_resource_file(owner, agent_id, resource, ident, db=db)
        try:
            record = await publish_attachment(owner, unquote(upload.filename or ""), upload.content_type or
                        "application/octet-stream", chunks(), settings.state_dir,
                        file_id=str(uuid.uuid4()),
                        metadata={"temp_file_id": temp_id,
                                  "context": "agent_resource" if agent_id else "message_attachment"},
                        bind=binder, process=extract_context_text if agent_id else None)
        except KeyError as exc:
            raise HTTPException(404, detail="Agent not found") from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        with _repo().database.connect() as db:
            row = db.execute("SELECT * FROM attachments WHERE id=? AND owner=?", (record["file_id"], owner)).fetchone()
        message = ("Agent file uploaded and processed successfully" if agent_id else
                   "File uploaded successfully")
        return JSONResponse({"message": message, **file_record(row)})
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

def recover_attachment_deletions():
    from .file_deletion import AttachmentDeletionStore

    database = _repo().database
    return {"deletions": AttachmentDeletionStore(database).recover(),
            "uploads": recover_attachment_uploads(database)}


def recover_attachment_uploads(database, *, grace_seconds=3600):
    """Collect interrupted uploads, refusing deletion on an inode mismatch.

    Any upload with unknown inode stays for manual review rather than risking
    a concurrently or externally recreated file. Committed rows always win.
    """
    import time

    from .file_deletion import AttachmentDeletionStore

    cleaned, retained = [], []
    with database.connect() as db:
        rows = db.execute("SELECT * FROM attachment_uploads WHERE created_at<=?",
                          (int(time.time()) - grace_seconds,)).fetchall()
    root = database.root.resolve() / "attachments"
    for row in rows:
        path = Path(row["path"])
        try:
            with database.connect() as db:
                committed = db.execute("SELECT 1 FROM attachments WHERE id=? AND path=?",
                                       (row["file_id"], str(path))).fetchone()
            if committed is None and path.exists():
                if path.is_symlink() or root not in path.resolve().parents:
                    raise OSError("Unsafe upload recovery path")
                stats = path.stat()
                # Migrated pre-identity intents are checked against the
                # original integer columns only when SQLite stored exact
                # integers; a REAL conversion cannot authorize deletion.
                old_identity = (
                    str(row["st_dev"]) + ":" + str(row["st_ino"])
                    if all(type(value) in {int, str} and str(value).isdigit()
                           for value in (row["st_dev"], row["st_ino"]))
                    else None
                )
                expected_identity = row["file_identity"] or old_identity
                if (expected_identity is None or row["content_sha256"] is None or
                    row["content_size"] != stats.st_size or
                    f"{stats.st_dev}:{stats.st_ino}" != expected_identity):
                    raise OSError("Upload file fingerprint changed or unknown")
                with path.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                    current = os.fstat(handle.fileno())
                if digest != row["content_sha256"] or (
                    f"{current.st_dev}:{current.st_ino}" != expected_identity):
                    raise OSError("Upload content changed during recovery")
                path.unlink()
                AttachmentDeletionStore._sync_directory(path.parent)
            with database.connect() as db:
                db.execute("DELETE FROM attachment_uploads WHERE file_id=?", (row["file_id"],))
            cleaned.append(row["file_id"])
        except (OSError, sqlite3.DatabaseError):
            log.exception("Upload recovery retained unresolved file")
            retained.append(row["file_id"])
    return {"cleanedFileIds": cleaned, "retainedFileIds": retained}


async def file_preview(request: Request):
    """Original React deferred preview polling; never return another owner's text."""
    from ..human_ui import _require_ui_scopes

    owner = _owner(request)
    _require_ui_scopes(request, "shell:read")
    ident = request.path_params["file_id"]
    with _repo().database.connect() as db:
        row = db.execute("SELECT metadata FROM attachments WHERE id=? AND owner=?",
                         (ident, owner)).fetchone()
    if row is None:
        raise HTTPException(404, detail="Attachment not found")
    metadata = _public_attachment_metadata(json.loads(row["metadata"]))
    status = metadata.get("status", "ready")
    if status not in {"pending", "ready", "failed"}:
        status = "ready"
    return JSONResponse({
        "file_id": ident, "status": status,
        **({"text": metadata["text"], "textFormat": metadata.get("textFormat", "text")}
           if status == "ready" and isinstance(metadata.get("text"), str) else {}),
        **({"previewError": metadata.get("previewError") or "parser-error"} if status == "failed" else {}),
    }, headers={"Cache-Control": "private, no-store"})


async def agent_files(request: Request):
    owner = _owner(request)
    with _repo().database.connect() as db:
        agent = db.execute("SELECT config FROM agents WHERE id=? AND owner=?",
                           (request.path_params["agent_id"], owner)).fetchone()
        if agent is None:
            return JSONResponse([])
        identities = set()
        for value in json.loads(agent["config"]).get("tool_resources", {}).values():
            if isinstance(value, dict):
                identities.update(value.get("file_ids", []))
        rows = [db.execute("SELECT * FROM attachments WHERE id=? AND owner=?", (ident, owner)).fetchone()
                for ident in identities]
    return JSONResponse([file_record(row) for row in rows if row is not None])


def _delete_file_ids(body):
    values = body.get("files")
    if not isinstance(values, list) or len(values) > 500:
        raise ValueError("A list of up to 500 files is required")
    identities = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Invalid file descriptor")
        ident = value.get("file_id")
        if not isinstance(ident, str) or not value.get("filepath"):
            continue
        # The first two forms are the original route contract. file_<hex> is
        # the pre-existing LSM native upload id, retained for owner-safe cleanup.
        if re.match(r"^(file|assistant)-", ident) or re.fullmatch(r"file_[0-9a-f]{32}", ident):
            identities.append(ident)
        else:
            try:
                if str(uuid.UUID(ident)).lower() == ident.lower():
                    identities.append(ident)
            except ValueError:
                pass
    return list(dict.fromkeys(identities))


async def list_react_files(request: Request):
    """GET /files: owner-scoped source-compatible file records."""
    from ..human_ui import _require_ui_scopes

    owner = _owner(request)
    _require_ui_scopes(request, "shell:read")
    with _repo().database.connect() as db:
        rows = db.execute("SELECT * FROM attachments WHERE owner=? ORDER BY created_at DESC",
                          (owner,)).fetchall()
    return JSONResponse([file_record(row) for row in rows])


async def delete_react_files(request: Request):
    from ..human_ui import _require_ui_scopes
    from ..settings import get_settings
    from .agent_validation import _RESOURCE_KEYS
    from .auth import _same_origin
    from .file_deletion import AttachmentDeletionStore, delete_response

    owner = _owner(request)
    _same_origin(request)
    _require_ui_scopes(request, "shell:read", "shell:write")
    if get_settings().disable_local:
        raise HTTPException(403, detail="Local workspace attachments are disabled")
    body = await _body(request)
    try:
        identities = _delete_file_ids(body)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    if not identities:
        return Response(status_code=204)
    repo = _repo()
    agent_id, resource = body.get("agent_id"), body.get("tool_resource")
    if (agent_id or resource) and (
        not isinstance(agent_id, str) or not agent_id or resource not in _RESOURCE_KEYS
    ):
        raise HTTPException(400, detail="Invalid agent resource deletion")
    with repo.database.connect() as db:
        if agent_id:
            agent = db.execute("SELECT owner FROM agents WHERE id=?", (agent_id,)).fetchone()
            if agent is None:
                raise HTTPException(404, detail="Agent not found")
            if agent["owner"] != owner:
                return JSONResponse({"message": "You can only delete files you have access to",
                                     "unauthorizedFiles": identities}, status_code=403)
        else:
            # Validate the entire requested batch before starting any physical
            # deletion. The store re-reads owner and references in each write
            # transaction; this preflight is only for all-or-nothing rejection.
            ids = identities
            rows = db.execute("SELECT id,owner FROM attachments WHERE id IN (" +
                              ",".join("?" for _ in ids) + ")", ids).fetchall()
            unauthorized = [row["id"] for row in rows if row["owner"] != owner]
            if unauthorized:
                return JSONResponse({"message": "You can only delete files you own",
                                     "unauthorizedFiles": unauthorized}, status_code=403)
    try:
        outcome = await asyncio.to_thread(AttachmentDeletionStore(repo.database).delete,
                                          identities, owner=owner, agent_id=agent_id, resource=resource)
    except sqlite3.DatabaseError:
        log.exception("Attachment metadata deletion failed")
        return JSONResponse({"message": "Error in request", "error": "Unable to delete file metadata"},
                            status_code=400)
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    if agent_id and not outcome["deletedFileIds"] and not outcome["failedFileIds"]:
        return JSONResponse({"message": "File associations removed successfully from agent"})
    return JSONResponse(delete_response(outcome, "Files deleted successfully"))


def attachment_routes() -> list[Route]:
    return [
        Route("/api/files", list_react_files, methods=["GET"]),
        Route("/api/files", upload_react_file, methods=["POST"]),
        Route("/api/files", delete_react_files, methods=["DELETE"]),
        Route("/api/files/agent/{agent_id}", agent_files, methods=["GET"]),
        Route("/api/files/images", upload_react_file, methods=["POST"]),
        Route("/api/files/{file_id}/preview", file_preview, methods=["GET"]),
        Route("/api/files/download/{file_id}", download_react_file, methods=["GET"]),
        Route("/api/lsm/controller/attachments/upload", upload_attachment, methods=["POST"]),
    ]
