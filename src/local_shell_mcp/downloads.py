from __future__ import annotations

import contextlib
import hashlib
import json
import mimetypes
import os
import secrets
import shutil
import stat
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .audit import audit
from .fs_ops import relative_display, resolve_path
from .settings import get_settings

_DOWNLOAD_PREFIX = "/download"
_DOWNLOAD_STORE_VERSION = 3
_STORE_LOCK = threading.RLock()


def _now() -> float:
    return time.time()


def _store_path() -> Path:
    settings = get_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return settings.state_dir / "downloads.json"


def _snapshot_dir() -> Path:
    path = get_settings().state_dir / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(0o700)
    return path


def _snapshot_name(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest() + ".bin"


def _snapshot_path(link: dict[str, Any]) -> Path:
    name = str(link.get("snapshot_name") or "")
    if not name or Path(name).name != name:
        raise ValueError("download snapshot metadata is invalid")
    return _snapshot_dir() / name


def _remove_snapshot(link: dict[str, Any]) -> None:
    with contextlib.suppress(OSError, ValueError):
        _snapshot_path(link).unlink(missing_ok=True)


def _remove_all_snapshots_locked() -> None:
    for path in _snapshot_dir().glob("*.bin"):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _create_snapshot(source: Path, token: str) -> tuple[Path, os.stat_result, os.stat_result]:
    settings = get_settings()
    destination = _snapshot_dir() / _snapshot_name(token)
    temporary = destination.with_name(destination.name + f".{secrets.token_hex(8)}.tmp")
    try:
        with _open_download_file(source) as source_handle:
            before = os.fstat(source_handle.fileno())
            if (
                settings.file_download_max_file_bytes > 0
                and before.st_size > settings.file_download_max_file_bytes
            ):
                raise ValueError(f"File is too large: {before.st_size}")
            with temporary.open("xb") as output:
                shutil.copyfileobj(source_handle, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            after = os.fstat(source_handle.fileno())
            before_identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if before_identity != after_identity:
                raise RuntimeError("File changed while the download link was being created")
        with contextlib.suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, destination)
        snapshot_stat = destination.stat()
        return destination, before, snapshot_stat
    finally:
        temporary.unlink(missing_ok=True)


def _empty_store() -> dict[str, Any]:
    return {"version": _DOWNLOAD_STORE_VERSION, "links": {}}


def _read_store_locked() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        audit("download_store_unreadable", path=str(path))
        _remove_all_snapshots_locked()
        return _empty_store()
    if not isinstance(data, dict) or not isinstance(data.get("links"), dict):
        audit("download_store_invalid", path=str(path))
        _remove_all_snapshots_locked()
        return _empty_store()
    if data.get("version") != _DOWNLOAD_STORE_VERSION:
        audit(
            "download_store_version_reset",
            path=str(path),
            stored_version=data.get("version"),
            expected_version=_DOWNLOAD_STORE_VERSION,
        )
        _remove_all_snapshots_locked()
        return _empty_store()
    return data


def _write_store_locked(store: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}-{secrets.token_hex(4)}")
    tmp.write_text(
        json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    os.replace(tmp, path)


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


def _coerce_ttl(ttl_s: int | None) -> int:
    settings = get_settings()
    requested = settings.file_download_default_ttl_s if ttl_s is None else int(ttl_s)
    if requested <= 0:
        raise ValueError("ttl_s must be positive")
    return min(requested, settings.file_download_max_ttl_s)


def _coerce_max_downloads(max_downloads: int | None) -> int:
    settings = get_settings()
    requested = (
        settings.file_download_default_max_downloads
        if max_downloads is None
        else int(max_downloads)
    )
    if requested < 0:
        raise ValueError("max_downloads must be >= 0; use 0 for unlimited")
    return requested


def _safe_filename(filename: str | None, source: Path) -> str:
    candidate = Path(filename).name if filename else source.name
    candidate = "".join(
        character
        for character in candidate.strip()
        if ord(character) >= 32 and ord(character) != 127
    )
    return candidate[:255] or "download"


def _link_summary(token: str, link: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": token,
        "url": f"{_public_base_url()}{_DOWNLOAD_PREFIX}/{token}",
        "path": link.get("display_path"),
        "filename": link.get("filename"),
        "bytes": link.get("bytes"),
        "created_at": link.get("created_at"),
        "expires_at": link.get("expires_at"),
        "ttl_remaining_s": max(0, int(link.get("expires_at", 0) - _now())),
        "downloads": link.get("downloads", 0),
        "max_downloads": link.get("max_downloads", 0),
    }


def _token_id(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _prune_locked(store: dict[str, Any], now: float | None = None) -> bool:
    now = _now() if now is None else now
    links = store.get("links", {})
    changed = False
    for token, link in list(links.items()):
        expires_at = float(link.get("expires_at", 0))
        max_downloads = int(link.get("max_downloads", 0))
        downloads = int(link.get("downloads", 0))
        if expires_at <= now or (max_downloads > 0 and downloads >= max_downloads):
            _remove_snapshot(link)
            links.pop(token, None)
            changed = True
    return changed


def _prune_orphan_snapshots_locked(store: dict[str, Any]) -> bool:
    referenced = {
        str(link.get("snapshot_name") or "")
        for link in store.get("links", {}).values()
        if isinstance(link, dict) and str(link.get("snapshot_name") or "")
    }
    changed = False
    for path in _snapshot_dir().glob("*.bin"):
        if path.name in referenced:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        changed = True
    return changed


def create_share_link(
    path: str,
    ttl_s: int | None = None,
    filename: str | None = None,
    max_downloads: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.file_download_enabled:
        raise PermissionError("disabled")

    resolved = resolve_path(path, must_exist=True)
    ttl = _coerce_ttl(ttl_s)
    limit = _coerce_max_downloads(max_downloads)
    token = secrets.token_urlsafe(32)
    now = _now()

    with _STORE_LOCK:
        store = _read_store_locked()
        _prune_locked(store, now)
        _prune_orphan_snapshots_locked(store)
        try:
            snapshot, source_stat, snapshot_stat = _create_snapshot(resolved, token)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Not a regular shareable file: {path}") from exc
        link = {
            "path": str(resolved),
            "display_path": relative_display(resolved),
            "filename": _safe_filename(filename, resolved),
            "bytes": source_stat.st_size,
            "snapshot_name": snapshot.name,
            "device": int(snapshot_stat.st_dev),
            "inode": int(snapshot_stat.st_ino),
            "created_at": now,
            "expires_at": now + ttl,
            "downloads": 0,
            "max_downloads": limit,
        }
        try:
            store["links"][token] = link
            _write_store_locked(store)
        except Exception:
            snapshot.unlink(missing_ok=True)
            raise

    audit(
        "download_link_created",
        path=link["display_path"],
        token_id=_token_id(token),
        expires_at=link["expires_at"],
    )
    return _link_summary(token, link)


def list_share_links(include_expired: bool = False) -> dict[str, Any]:
    with _STORE_LOCK:
        store = _read_store_locked()
        changed = False if include_expired else _prune_locked(store)
        changed = _prune_orphan_snapshots_locked(store) or changed
        if changed:
            _write_store_locked(store)
        links = [_link_summary(token, link) for token, link in store.get("links", {}).items()]
    links.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return {"links": links}


def revoke_share_link(token: str) -> dict[str, Any]:
    with _STORE_LOCK:
        store = _read_store_locked()
        changed = _prune_orphan_snapshots_locked(store)
        removed = store.get("links", {}).pop(token, None)
        if removed is not None:
            _remove_snapshot(removed)
            changed = True
        if changed:
            _write_store_locked(store)
    if removed is not None:
        audit("download_link_revoked", path=removed.get("display_path"), token_id=_token_id(token))
    return {"revoked": removed is not None, "token": token}


def _error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error, "message": message}, status_code=status_code)


def _open_download_file(path: Path) -> BinaryIO:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("download target is not a regular file")
        return os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise


def _claim_download(
    token: str, *, consume: bool
) -> tuple[BinaryIO, Path, dict[str, Any]] | Response:
    settings = get_settings()
    if not settings.file_download_enabled:
        return _error_response(404, "download_disabled", "File downloads are disabled")

    with _STORE_LOCK:
        store = _read_store_locked()
        link = store.get("links", {}).get(token)
        if not link:
            return _error_response(404, "download_not_found", "Link not found")

        now = _now()
        if float(link.get("expires_at", 0)) <= now:
            _remove_snapshot(link)
            store.get("links", {}).pop(token, None)
            _write_store_locked(store)
            return _error_response(410, "download_expired", "Link has expired")

        max_downloads = int(link.get("max_downloads", 0))
        downloads = int(link.get("downloads", 0))
        if max_downloads > 0 and downloads >= max_downloads:
            _remove_snapshot(link)
            store.get("links", {}).pop(token, None)
            _write_store_locked(store)
            return _error_response(410, "download_exhausted", "Link has reached its use limit")

        try:
            path = _snapshot_path(link)
            handle = _open_download_file(path)
        except (FileNotFoundError, OSError, PermissionError, ValueError):
            store.get("links", {}).pop(token, None)
            _write_store_locked(store)
            return _error_response(
                404,
                "download_missing",
                "The shared file snapshot no longer exists",
            )

        opened_stat = os.fstat(handle.fileno())
        if int(link.get("device", -1)) != int(opened_stat.st_dev) or int(
            link.get("inode", -1)
        ) != int(opened_stat.st_ino):
            handle.close()
            store.get("links", {}).pop(token, None)
            _write_store_locked(store)
            return _error_response(
                410,
                "download_changed",
                "The target file changed after the link was created",
            )

        size = opened_stat.st_size
        if (
            settings.file_download_max_file_bytes > 0
            and size > settings.file_download_max_file_bytes
        ):
            handle.close()
            return _error_response(
                403,
                "download_too_large",
                "The target file exceeds the configured size limit",
            )

        claimed_link = dict(link)
        if consume:
            new_downloads = downloads + 1
            link["downloads"] = new_downloads
            link["last_download_at"] = now
            store["links"][token] = link
            claimed_link = dict(link)
            if max_downloads > 0 and new_downloads >= max_downloads:
                claimed_link["delete_snapshot_after_stream"] = True
            try:
                _write_store_locked(store)
            except Exception:
                handle.close()
                raise

    return handle, path, claimed_link


def _content_disposition(filename: str) -> str:
    fallback = (
        filename.encode("ascii", errors="ignore").decode("ascii").replace('"', "") or "download"
    )
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _file_chunks(
    handle: BinaryIO,
    chunk_size: int = 64 * 1024,
    cleanup_path: Path | None = None,
):  # noqa: ANN201
    try:
        while chunk := handle.read(chunk_size):
            yield chunk
    finally:
        handle.close()
        if cleanup_path is not None:
            with contextlib.suppress(OSError):
                cleanup_path.unlink(missing_ok=True)


async def download_endpoint(request: Request) -> Response:
    token = request.path_params.get("token", "")
    claimed = _claim_download(token, consume=request.method.upper() == "GET")
    if isinstance(claimed, Response):
        return claimed

    handle, path, link = claimed
    media_type = (
        mimetypes.guess_type(link.get("filename") or path.name)[0] or "application/octet-stream"
    )
    filename = link.get("filename") or path.name
    headers = {
        "Cache-Control": "private, no-store",
        "Content-Disposition": _content_disposition(filename),
        "Content-Length": str(os.fstat(handle.fileno()).st_size),
    }
    audit(
        "download_link_served",
        path=link.get("display_path"),
        token_id=_token_id(token),
        method=request.method,
    )
    if request.method.upper() == "HEAD":
        handle.close()
        return Response(status_code=200, media_type=media_type, headers=headers)
    cleanup_path = path if link.get("delete_snapshot_after_stream") else None
    return StreamingResponse(
        _file_chunks(handle, cleanup_path=cleanup_path),
        media_type=media_type,
        headers=headers,
    )


def download_routes() -> list[Route]:
    return [Route(f"{_DOWNLOAD_PREFIX}/{{token}}", download_endpoint, methods=["GET", "HEAD"])]


create_download_link = create_share_link
list_download_links = list_share_links
revoke_download_link = revoke_share_link
