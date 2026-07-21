from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import secrets
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .audit import audit
from .fs_ops import relative_display, resolve_path
from .settings import get_settings
from .transfer_ops import (
    MAX_TRANSFER_CHUNK_BYTES,
    transfer_abort_write,
    transfer_begin_write,
    transfer_finish_write,
    transfer_write_bytes,
)

REMOTE_TRANSFER_PREFIX = "/remote/transfer"
REMOTE_TRANSFER_UPLOAD_PREFIX = f"{REMOTE_TRANSFER_PREFIX}/upload/"
REMOTE_TRANSFER_DOWNLOAD_PREFIX = f"{REMOTE_TRANSFER_PREFIX}/download/"
_TRANSFER_CHUNK_BYTES = 1024 * 1024
_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_TICKET_LOCK = threading.RLock()


@dataclass
class _TransferTicket:
    token: str
    direction: Literal["upload", "download"]
    path: str
    expected_bytes: int
    expected_sha256: str
    overwrite: bool
    created_at: float
    expires_at: float
    display_path: str | None = None
    cleanup_path: str | None = None
    claimed: bool = False
    transfer_id: str | None = None
    received_bytes: int = 0
    completed_data: dict[str, Any] | None = None


_TICKETS: dict[str, _TransferTicket] = {}


def _now() -> float:
    return time.time()


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _public_base_url() -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = settings.host
    if host in {"", "0.0.0.0", "::"}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings.port}"


def _ticket_ttl_s() -> int:
    return max(60, int(get_settings().remote_job_timeout_s))


def _validate_expected(expected_bytes: int, expected_sha256: str) -> tuple[int, str]:
    size = int(expected_bytes)
    digest = str(expected_sha256).lower()
    if size < 0:
        raise ValueError("expected_bytes must be >= 0")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("expected_sha256 must be a SHA-256 digest")
    return size, digest


def _cleanup_ticket_file(ticket: _TransferTicket) -> None:
    if ticket.direction == "upload" and ticket.transfer_id:
        with contextlib.suppress(Exception):
            transfer_abort_write(ticket.path, ticket.transfer_id)
        ticket.transfer_id = None
    if not ticket.cleanup_path:
        return
    with contextlib.suppress(OSError):
        Path(ticket.cleanup_path).unlink(missing_ok=True)


def _prune_locked(now: float | None = None) -> None:
    current = _now() if now is None else now
    for token, ticket in list(_TICKETS.items()):
        if ticket.expires_at <= current and not ticket.claimed:
            removed = _TICKETS.pop(token, None)
            if removed is not None:
                _cleanup_ticket_file(removed)


def _create_ticket(
    direction: Literal["upload", "download"],
    path: Path,
    expected_bytes: int,
    expected_sha256: str,
    overwrite: bool,
    *,
    token: str | None = None,
    display_path: Path | None = None,
    cleanup_path: Path | None = None,
    transfer_id: str | None = None,
) -> dict[str, Any]:
    size, digest = _validate_expected(expected_bytes, expected_sha256)
    token = token or secrets.token_urlsafe(32)
    now = _now()
    ticket = _TransferTicket(
        token=token,
        direction=direction,
        path=str(path),
        expected_bytes=size,
        expected_sha256=digest,
        overwrite=bool(overwrite),
        created_at=now,
        expires_at=now + _ticket_ttl_s(),
        display_path=str(display_path or path),
        cleanup_path=str(cleanup_path) if cleanup_path is not None else None,
        transfer_id=transfer_id,
    )
    with _TICKET_LOCK:
        _prune_locked(now)
        _TICKETS[token] = ticket
    audit(
        "remote_transfer_ticket_created",
        direction=direction,
        path=relative_display(Path(ticket.display_path or ticket.path)),
        bytes=size,
        token_id=_token_id(token),
    )
    return {
        "token": token,
        "url": f"{_public_base_url()}{REMOTE_TRANSFER_PREFIX}/{direction}/{token}",
        "path": relative_display(Path(ticket.display_path or ticket.path)),
        "bytes": size,
        "sha256": digest,
        "expires_at": ticket.expires_at,
    }


def create_upload_ticket(
    destination_path: str,
    expected_bytes: int,
    expected_sha256: str,
    overwrite: bool = True,
) -> dict[str, Any]:
    destination = resolve_path(destination_path, follow_final_symlink=False)
    begin = transfer_begin_write(str(destination), overwrite, expected_bytes)
    try:
        return _create_ticket(
            "upload",
            destination,
            expected_bytes,
            expected_sha256,
            overwrite,
            transfer_id=begin["transfer_id"],
        )
    except Exception:
        transfer_abort_write(str(destination), begin["transfer_id"])
        raise


def _download_snapshot_path(token: str) -> Path:
    directory = get_settings().state_dir / "remote-transfers"
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        directory.chmod(0o700)
    return directory / f"{hashlib.sha256(token.encode('utf-8')).hexdigest()}.bin"


def _create_download_snapshot(
    source: Path, token: str, expected_bytes: int, expected_sha256: str
) -> Path:
    snapshot = _download_snapshot_path(token)
    temporary = snapshot.with_name(snapshot.name + f".{secrets.token_hex(8)}.tmp")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as output:
            before = os.fstat(source_handle.fileno())
            if before.st_size != expected_bytes:
                raise ValueError(
                    f"size mismatch: expected {expected_bytes}, got {before.st_size}"
                )
            while chunk := source_handle.read(_TRANSFER_CHUNK_BYTES):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(source_handle.fileno())
            identity_before = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            identity_after = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if identity_before != identity_after:
                raise RuntimeError("source changed while creating remote transfer snapshot")
        if digest.hexdigest() != expected_sha256:
            raise ValueError("file sha256 mismatch")
        with contextlib.suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, snapshot)
        return snapshot
    finally:
        temporary.unlink(missing_ok=True)


def create_download_ticket(
    source_path: str,
    expected_bytes: int,
    expected_sha256: str,
) -> dict[str, Any]:
    size, digest = _validate_expected(expected_bytes, expected_sha256)
    source = resolve_path(source_path, must_exist=True)
    if not source.is_file():
        raise ValueError(f"source is not a file: {source_path}")
    token = secrets.token_urlsafe(32)
    snapshot = _create_download_snapshot(source, token, size, digest)
    try:
        return _create_ticket(
            "download",
            snapshot,
            size,
            digest,
            False,
            token=token,
            display_path=source,
            cleanup_path=snapshot,
        )
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise


def revoke_transfer_ticket(token: str) -> dict[str, Any]:
    with _TICKET_LOCK:
        removed = _TICKETS.pop(token, None)
    if removed is not None:
        _cleanup_ticket_file(removed)
        audit(
            "remote_transfer_ticket_revoked",
            direction=removed.direction,
            token_id=_token_id(token),
        )
    return {"revoked": removed is not None}


def _claim_ticket(token: str, direction: Literal["upload", "download"]) -> _TransferTicket:
    with _TICKET_LOCK:
        _prune_locked()
        ticket = _TICKETS.get(token)
        if ticket is None:
            raise FileNotFoundError("transfer ticket does not exist or has expired")
        if ticket.direction != direction:
            raise PermissionError("transfer ticket direction mismatch")
        if ticket.claimed:
            raise RuntimeError("transfer ticket is already in use")
        ticket.claimed = True
        return ticket


def _release_ticket(token: str) -> None:
    with _TICKET_LOCK:
        ticket = _TICKETS.get(token)
        if ticket is not None:
            ticket.claimed = False
            ticket.expires_at = _now() + _ticket_ttl_s()


def _upload_ticket_data(ticket: _TransferTicket) -> dict[str, Any]:
    if ticket.completed_data is not None:
        return dict(ticket.completed_data)
    return {
        "path": relative_display(Path(ticket.display_path or ticket.path)),
        "bytes": ticket.expected_bytes,
        "sha256": ticket.expected_sha256,
        "received_bytes": ticket.received_bytes,
        "completed": False,
        "transport": "http-chunks",
    }


def get_upload_ticket_status(token: str) -> dict[str, Any]:
    with _TICKET_LOCK:
        _prune_locked()
        ticket = _TICKETS.get(token)
        if ticket is None:
            raise FileNotFoundError("transfer ticket does not exist or has expired")
        if ticket.direction != "upload":
            raise PermissionError("transfer ticket direction mismatch")
        ticket.expires_at = _now() + _ticket_ttl_s()
        return _upload_ticket_data(ticket)


def _complete_upload_ticket(
    token: str, ticket: _TransferTicket, finish: dict[str, Any]
) -> dict[str, Any]:
    data = {
        "path": finish["path"],
        "bytes": finish["bytes"],
        "sha256": finish["sha256"],
        "received_bytes": finish["bytes"],
        "completed": True,
        "transport": "http-chunks",
    }
    with _TICKET_LOCK:
        ticket.transfer_id = None
        ticket.received_bytes = finish["bytes"]
        ticket.completed_data = data
        ticket.claimed = False
        ticket.expires_at = _now() + _ticket_ttl_s()
    audit(
        "remote_transfer_completed",
        direction="upload",
        path=finish["path"],
        bytes=finish["bytes"],
        token_id=_token_id(token),
    )
    return data


def _write_upload_chunk(
    ticket: _TransferTicket,
    start: int,
    end: int,
    payload: bytes,
) -> None:
    if ticket.transfer_id is None:
        raise RuntimeError("upload transaction is unavailable")
    transfer_write_bytes(ticket.path, ticket.transfer_id, start, payload)
    with _TICKET_LOCK:
        ticket.received_bytes = end
        ticket.expires_at = _now() + _ticket_ttl_s()


def _finish_upload_transaction(token: str, ticket: _TransferTicket) -> dict[str, Any]:
    if ticket.transfer_id is None:
        raise RuntimeError("upload transaction is unavailable")
    finish = transfer_finish_write(
        ticket.path,
        ticket.transfer_id,
        ticket.expected_bytes,
        ticket.expected_sha256,
    )
    return _complete_upload_ticket(token, ticket, finish)


def _complete_ticket(token: str) -> None:
    with _TICKET_LOCK:
        ticket = _TICKETS.pop(token, None)
    if ticket is not None:
        _cleanup_ticket_file(ticket)
        audit(
            "remote_transfer_completed",
            direction=ticket.direction,
            path=relative_display(Path(ticket.path)),
            bytes=ticket.expected_bytes,
            token_id=_token_id(token),
        )


def _error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": error, "message": message},
        status_code=status_code,
    )


def _content_disposition(filename: str) -> str:
    fallback = (
        filename.encode("ascii", errors="ignore").decode("ascii").replace('"', "").replace("\\", "")
        or "download"
    )
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _upload_range(request: Request, ticket: _TransferTicket) -> tuple[int, int, bool]:
    raw_range = request.headers.get("content-range")
    if not raw_range:
        return 0, ticket.expected_bytes, True
    match = _CONTENT_RANGE_RE.fullmatch(raw_range.strip())
    if match is None:
        raise ValueError("Content-Range must use 'bytes start-end/total'")
    start, inclusive_end, total = (int(value) for value in match.groups())
    if total != ticket.expected_bytes:
        raise ValueError(f"Content-Range total must be {ticket.expected_bytes}")
    if inclusive_end < start or inclusive_end >= total:
        raise ValueError("Content-Range bounds are invalid")
    return start, inclusive_end + 1, False


async def upload_status_endpoint(request: Request) -> JSONResponse:
    token = request.path_params["token"]
    try:
        data = get_upload_ticket_status(token)
    except FileNotFoundError as exc:
        return _error_response(404, "transfer_not_found", str(exc))
    except PermissionError as exc:
        return _error_response(409, "transfer_unavailable", str(exc))
    return JSONResponse({"ok": True, "data": data})


async def upload_endpoint(request: Request) -> JSONResponse:
    token = request.path_params["token"]
    try:
        ticket = _claim_ticket(token, "upload")
    except FileNotFoundError as exc:
        return _error_response(404, "transfer_not_found", str(exc))
    except (PermissionError, RuntimeError) as exc:
        return _error_response(409, "transfer_unavailable", str(exc))

    if ticket.completed_data is not None:
        data = _upload_ticket_data(ticket)
        _release_ticket(token)
        return JSONResponse({"ok": True, "data": data})

    try:
        start, end, legacy_full_upload = _upload_range(request, ticket)
        expected_chunk_bytes = end - start
        if expected_chunk_bytes > MAX_TRANSFER_CHUNK_BYTES:
            detail = (
                "legacy full-file upload exceeds the supported request size; update the remote worker"
                if legacy_full_upload
                else "upload chunk exceeds the supported request size"
            )
            raise ValueError(f"{detail}: maximum is {MAX_TRANSFER_CHUNK_BYTES} bytes")
        raw_length = request.headers.get("content-length")
        if raw_length:
            try:
                content_length = int(raw_length)
            except ValueError as exc:
                raise ValueError("Content-Length is invalid") from exc
            if content_length != expected_chunk_bytes:
                raise ValueError(
                    f"Expected {expected_chunk_bytes} bytes, got Content-Length {content_length}"
                )
        if start != ticket.received_bytes:
            data = _upload_ticket_data(ticket)
            _release_ticket(token)
            return JSONResponse(
                {
                    "ok": False,
                    "error": "offset_mismatch",
                    "message": f"Expected upload offset {ticket.received_bytes}, got {start}",
                    "data": data,
                },
                status_code=409,
            )

        payload = bytearray()
        async for chunk in request.stream():
            if not chunk:
                continue
            if len(payload) + len(chunk) > expected_chunk_bytes:
                raise ValueError("upload exceeds declared chunk size")
            payload.extend(chunk)
        if len(payload) != expected_chunk_bytes:
            raise ValueError(f"size mismatch: expected {expected_chunk_bytes}, got {len(payload)}")

        expected_chunk_sha256 = request.headers.get("x-chunk-sha256")
        actual_chunk_sha256 = hashlib.sha256(payload).hexdigest()
        if expected_chunk_sha256 and actual_chunk_sha256 != expected_chunk_sha256.lower():
            raise ValueError("chunk sha256 mismatch")
        await asyncio.to_thread(
            _write_upload_chunk,
            ticket,
            start,
            end,
            bytes(payload),
        )

        if end == ticket.expected_bytes:
            data = await asyncio.to_thread(
                _finish_upload_transaction,
                token,
                ticket,
            )
            return JSONResponse({"ok": True, "data": data})

        data = _upload_ticket_data(ticket)
        _release_ticket(token)
        return JSONResponse({"ok": True, "data": data})
    except asyncio.CancelledError:
        _release_ticket(token)
        raise
    except Exception as exc:
        if ticket.received_bytes == ticket.expected_bytes:
            with _TICKET_LOCK:
                removed = _TICKETS.pop(token, None)
            if removed is not None:
                _cleanup_ticket_file(removed)
        else:
            _release_ticket(token)
        audit(
            "remote_transfer_upload_failed",
            token_id=_token_id(token),
            error=type(exc).__name__,
            message=str(exc),
        )
        return _error_response(400, type(exc).__name__, str(exc))


def _open_download(ticket: _TransferTicket):  # noqa: ANN202
    path = resolve_path(ticket.path, must_exist=True)
    handle = path.open("rb")
    stat = os.fstat(handle.fileno())
    if stat.st_size != ticket.expected_bytes:
        handle.close()
        raise ValueError(f"size mismatch: expected {ticket.expected_bytes}, got {stat.st_size}")
    return path, handle


def _download_iterator(token: str, ticket: _TransferTicket, handle) -> Iterator[bytes]:  # noqa: ANN001
    completed = False
    try:
        while True:
            chunk = handle.read(_TRANSFER_CHUNK_BYTES)
            if not chunk:
                completed = True
                break
            yield chunk
    finally:
        handle.close()
        if completed:
            _complete_ticket(token)
        else:
            _release_ticket(token)


async def download_endpoint(request: Request):  # noqa: ANN201
    token = request.path_params["token"]
    try:
        ticket = _claim_ticket(token, "download")
        path, handle = await asyncio.to_thread(_open_download, ticket)
    except FileNotFoundError as exc:
        _release_ticket(token)
        return _error_response(404, "transfer_not_found", str(exc))
    except (PermissionError, RuntimeError) as exc:
        _release_ticket(token)
        return _error_response(409, "transfer_unavailable", str(exc))
    except Exception as exc:
        _release_ticket(token)
        return _error_response(400, type(exc).__name__, str(exc))

    return StreamingResponse(
        _download_iterator(token, ticket, handle),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(ticket.expected_bytes),
            "X-Content-SHA256": ticket.expected_sha256,
            "Content-Disposition": _content_disposition(
                Path(ticket.display_path or path).name
            ),
            "Cache-Control": "no-store",
        },
    )


def remote_transfer_routes() -> list[Any]:
    return [
        Route(
            f"{REMOTE_TRANSFER_PREFIX}/upload/{{token}}",
            upload_endpoint,
            methods=["PUT"],
        ),
        Route(
            f"{REMOTE_TRANSFER_PREFIX}/upload/{{token}}",
            upload_status_endpoint,
            methods=["GET"],
        ),
        Route(
            f"{REMOTE_TRANSFER_PREFIX}/download/{{token}}",
            download_endpoint,
            methods=["GET"],
        ),
    ]
