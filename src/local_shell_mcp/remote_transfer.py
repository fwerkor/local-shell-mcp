from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
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
    transfer_abort_write,
    transfer_begin_write,
    transfer_finish_write,
    transfer_write_bytes,
)

REMOTE_TRANSFER_PREFIX = "/remote/transfer"
REMOTE_TRANSFER_UPLOAD_PREFIX = f"{REMOTE_TRANSFER_PREFIX}/upload/"
REMOTE_TRANSFER_DOWNLOAD_PREFIX = f"{REMOTE_TRANSFER_PREFIX}/download/"
_TRANSFER_CHUNK_BYTES = 1024 * 1024
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
    claimed: bool = False


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


def _prune_locked(now: float | None = None) -> None:
    current = _now() if now is None else now
    for token, ticket in list(_TICKETS.items()):
        if ticket.expires_at <= current:
            _TICKETS.pop(token, None)


def _create_ticket(
    direction: Literal["upload", "download"],
    path: Path,
    expected_bytes: int,
    expected_sha256: str,
    overwrite: bool,
) -> dict[str, Any]:
    size, digest = _validate_expected(expected_bytes, expected_sha256)
    token = secrets.token_urlsafe(32)
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
    )
    with _TICKET_LOCK:
        _prune_locked(now)
        _TICKETS[token] = ticket
    audit(
        "remote_transfer_ticket_created",
        direction=direction,
        path=relative_display(path),
        bytes=size,
        token_id=_token_id(token),
    )
    return {
        "token": token,
        "url": f"{_public_base_url()}{REMOTE_TRANSFER_PREFIX}/{direction}/{token}",
        "path": relative_display(path),
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
    return _create_ticket("upload", destination, expected_bytes, expected_sha256, overwrite)


def create_download_ticket(
    source_path: str,
    expected_bytes: int,
    expected_sha256: str,
) -> dict[str, Any]:
    source = resolve_path(source_path, must_exist=True)
    if not source.is_file():
        raise ValueError(f"source is not a file: {source_path}")
    return _create_ticket("download", source, expected_bytes, expected_sha256, False)


def revoke_transfer_ticket(token: str) -> dict[str, Any]:
    with _TICKET_LOCK:
        removed = _TICKETS.pop(token, None)
    if removed is not None:
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


def _complete_ticket(token: str) -> None:
    with _TICKET_LOCK:
        ticket = _TICKETS.pop(token, None)
    if ticket is not None:
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


async def upload_endpoint(request: Request) -> JSONResponse:
    token = request.path_params["token"]
    try:
        ticket = _claim_ticket(token, "upload")
    except FileNotFoundError as exc:
        return _error_response(404, "transfer_not_found", str(exc))
    except (PermissionError, RuntimeError) as exc:
        return _error_response(409, "transfer_unavailable", str(exc))

    raw_length = request.headers.get("content-length")
    if raw_length:
        try:
            content_length = int(raw_length)
        except ValueError:
            _release_ticket(token)
            return _error_response(400, "invalid_content_length", "Content-Length is invalid")
        if content_length != ticket.expected_bytes:
            _release_ticket(token)
            return _error_response(
                400,
                "size_mismatch",
                f"Expected {ticket.expected_bytes} bytes, got Content-Length {content_length}",
            )

    begin: dict[str, Any] | None = None
    offset = 0
    digest = hashlib.sha256()
    try:
        begin = await asyncio.to_thread(
            transfer_begin_write,
            ticket.path,
            ticket.overwrite,
            ticket.expected_bytes,
        )
        async for chunk in request.stream():
            if not chunk:
                continue
            if offset + len(chunk) > ticket.expected_bytes:
                raise ValueError("upload exceeds expected transfer size")
            digest.update(chunk)
            await asyncio.to_thread(
                transfer_write_bytes,
                ticket.path,
                begin["transfer_id"],
                offset,
                chunk,
            )
            offset += len(chunk)
        if offset != ticket.expected_bytes:
            raise ValueError(f"size mismatch: expected {ticket.expected_bytes}, got {offset}")
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != ticket.expected_sha256:
            raise ValueError("file sha256 mismatch")
        finish = await asyncio.to_thread(
            transfer_finish_write,
            ticket.path,
            begin["transfer_id"],
            ticket.expected_bytes,
            ticket.expected_sha256,
        )
        _complete_ticket(token)
        return JSONResponse(
            {
                "ok": True,
                "data": {
                    "path": finish["path"],
                    "bytes": finish["bytes"],
                    "sha256": finish["sha256"],
                    "transport": "http-stream",
                },
            }
        )
    except asyncio.CancelledError:
        if begin is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    transfer_abort_write,
                    ticket.path,
                    begin["transfer_id"],
                )
        _release_ticket(token)
        raise
    except Exception as exc:
        if begin is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    transfer_abort_write,
                    ticket.path,
                    begin["transfer_id"],
                )
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
            "Content-Disposition": _content_disposition(path.name),
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
            f"{REMOTE_TRANSFER_PREFIX}/download/{{token}}",
            download_endpoint,
            methods=["GET"],
        ),
    ]
