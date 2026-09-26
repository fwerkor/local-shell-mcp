from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .fs_ops import (
    _path_lock,
    _path_locks,
    acquire_temp_file_lease,
    prune_temp_dir,
    refresh_temp_file_lease,
    relative_display,
    release_temp_file_lease,
    resolve_path,
    temp_dir,
)
from .settings import get_settings

DEFAULT_TRANSFER_CHUNK_BYTES = 1024 * 1024
MAX_TRANSFER_CHUNK_BYTES = 4 * 1024 * 1024
_TRANSFER_TMP_MARKER = "local-shell-mcp-transfer"
_TEMP_LEASE_REFRESH_INTERVAL_S = 1.0


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("transfer operation was cancelled")


def _poll_transfer_activity(
    cancel_event: threading.Event | None,
    lease_path: Path | None,
    last_refresh_at: float,
) -> float:
    _raise_if_cancelled(cancel_event)
    if lease_path is None:
        return last_refresh_at
    now = time.monotonic()
    if now - last_refresh_at >= _TEMP_LEASE_REFRESH_INTERVAL_S:
        refresh_temp_file_lease(lease_path, create=False)
        return now
    return last_refresh_at


class _LeaseRefreshingReader:
    def __init__(
        self,
        handle: Any,
        lease_path: Path,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._handle = handle
        self._lease_path = lease_path
        self._cancel_event = cancel_event
        self._last_refresh = 0.0

    def _before_io(self) -> None:
        self._last_refresh = _poll_transfer_activity(
            self._cancel_event,
            self._lease_path,
            self._last_refresh,
        )

    def read(self, size: int = -1) -> bytes:
        self._before_io()
        data = self._handle.read(size)
        _raise_if_cancelled(self._cancel_event)
        return data

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self._before_io()
        result = self._handle.seek(offset, whence)
        _raise_if_cancelled(self._cancel_event)
        return result

    def tell(self) -> int:
        return self._handle.tell()


def _copy_stream(
    source: Any,
    destination: Any,
    *,
    lease_path: Path,
    cancel_event: threading.Event | None = None,
) -> None:
    reader = _LeaseRefreshingReader(source, lease_path, cancel_event)
    while True:
        chunk = reader.read(DEFAULT_TRANSFER_CHUNK_BYTES)
        if not chunk:
            return
        destination.write(chunk)


def _entry_signature(path: Path) -> tuple[Any, ...]:
    info = path.lstat()
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        raise ValueError(f"directory transfer does not support symlinks: {relative_display(path)}")
    if stat.S_ISDIR(mode):
        return ("dir",)
    if stat.S_ISREG(mode):
        return ("file", info.st_size, info.st_mtime_ns, info.st_ino)
    raise ValueError(f"directory transfer does not support special files: {relative_display(path)}")


def _snapshot_transferable_tree(
    path: Path,
    cancel_event: threading.Event | None = None,
    lease_path: Path | None = None,
) -> dict[str, tuple[Any, ...]]:
    snapshot: dict[str, tuple[Any, ...]] = {}
    last_lease_refresh = 0.0

    def poll() -> None:
        nonlocal last_lease_refresh
        last_lease_refresh = _poll_transfer_activity(
            cancel_event,
            lease_path,
            last_lease_refresh,
        )

    def visit(directory: Path) -> None:
        children: list[Path] = []
        iterator = directory.iterdir()
        while True:
            poll()
            try:
                child = next(iterator)
            except StopIteration:
                break
            children.append(child)
        children.sort(key=lambda item: item.name)
        for child in children:
            poll()
            relative = child.relative_to(path).as_posix()
            signature = _entry_signature(child)
            snapshot[relative] = signature
            if signature[0] == "dir":
                visit(child)

    visit(path)
    return snapshot


async def _run_cancellable_transfer(
    function: Any,
    *args: Any,
    cancelled_result_cleanup: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cancel_event = threading.Event()
    worker = asyncio.create_task(asyncio.to_thread(function, *args, cancel_event))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel_event.set()
        try:
            result = await asyncio.shield(worker)
        except Exception:
            pass
        else:
            if cancelled_result_cleanup is not None:
                with contextlib.suppress(Exception):
                    cancelled_result_cleanup(result)
        raise


def _archive_path_from_result(result: dict[str, Any]) -> Path | None:
    value = result.get("archive_path")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = get_settings().workspace_root / path
    return path


def _cleanup_cancelled_pack_result(result: dict[str, Any]) -> None:
    archive = _archive_path_from_result(result)
    if archive is None:
        return
    try:
        archive.unlink(missing_ok=True)
    finally:
        release_temp_file_lease(archive)


def normalize_chunk_size(chunk_size: int | None = None) -> int:
    requested = DEFAULT_TRANSFER_CHUNK_BYTES if chunk_size is None else int(chunk_size)
    if requested <= 0:
        raise ValueError("chunk_size must be greater than zero")
    return min(requested, MAX_TRANSFER_CHUNK_BYTES)


def _sha256_file(
    path: Path,
    chunk_size: int = DEFAULT_TRANSFER_CHUNK_BYTES,
    cancel_event: threading.Event | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            _raise_if_cancelled(cancel_event)
            refresh_temp_file_lease(path, create=False)
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    _raise_if_cancelled(cancel_event)
    return digest.hexdigest()


def transfer_stat(path: str, sha256: bool = True) -> dict[str, Any]:
    p = resolve_path(path, must_exist=True)
    refresh_temp_file_lease(p, create=False)
    stat = p.stat()
    if p.is_file():
        result: dict[str, Any] = {
            "path": relative_display(p),
            "type": "file",
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }
        if sha256:
            result["sha256"] = _sha256_file(p)
        return result
    if p.is_dir():
        return {
            "path": relative_display(p),
            "type": "dir",
            "size": None,
            "modified": stat.st_mtime,
        }
    return {
        "path": relative_display(p),
        "type": "other",
        "size": stat.st_size,
        "modified": stat.st_mtime,
    }


def transfer_read_chunk(
    path: str, offset: int = 0, chunk_size: int | None = None
) -> dict[str, Any]:
    p = resolve_path(path, must_exist=True)
    refresh_temp_file_lease(p, create=False)
    if not p.is_file():
        raise IsADirectoryError(str(p))
    size = p.stat().st_size
    start = int(offset)
    if start < 0:
        raise ValueError("offset must be >= 0")
    limit = normalize_chunk_size(chunk_size)
    with p.open("rb") as fh:
        fh.seek(start)
        data = fh.read(limit)
    digest = hashlib.sha256(data).hexdigest()
    return {
        "path": relative_display(p),
        "offset": start,
        "bytes": len(data),
        "size": size,
        "eof": start + len(data) >= size,
        "sha256": digest,
        "data_b64": base64.b64encode(data).decode("ascii"),
    }


def _transfer_temp_path(dst: Path, transfer_id: str) -> Path:
    safe_id = "".join(ch for ch in transfer_id if ch.isalnum() or ch in "-_")
    if not safe_id or safe_id != transfer_id:
        raise ValueError("transfer_id contains unsupported characters")
    return dst.parent / f".{dst.name}.{_TRANSFER_TMP_MARKER}-{safe_id}.tmp"


def _transfer_metadata_path(tmp: Path) -> Path:
    return tmp.with_name(tmp.name + ".json")


def _write_transfer_metadata(tmp: Path, metadata: dict[str, Any]) -> None:
    path = _transfer_metadata_path(tmp)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    refresh_temp_file_lease(temporary)
    try:
        temporary.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        with contextlib.suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
        release_temp_file_lease(temporary)


def _read_transfer_metadata(tmp: Path) -> dict[str, Any]:
    path = _transfer_metadata_path(tmp)
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"transfer metadata is missing or invalid: {path}") from exc
    if not isinstance(metadata, dict):
        raise ValueError(f"transfer metadata is invalid: {path}")
    return metadata


def _received_ranges(metadata: dict[str, Any]) -> list[list[int]]:
    raw = metadata.get("received_ranges", [])
    if not isinstance(raw, list):
        raise ValueError("transfer metadata received_ranges is invalid")
    ranges: list[list[int]] = []
    for item in raw:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(value, int) for value in item)
            or item[0] < 0
            or item[1] < item[0]
        ):
            raise ValueError("transfer metadata received_ranges is invalid")
        ranges.append([item[0], item[1]])
    return ranges


def _record_received_range(metadata: dict[str, Any], start: int, end: int) -> None:
    if end < start:
        raise ValueError("transfer range is invalid")
    if end == start:
        return
    ranges = _received_ranges(metadata)
    for existing_start, existing_end in ranges:
        if start < existing_end and end > existing_start:
            raise ValueError("transfer chunk overlaps previously received data")
    ranges.append([start, end])
    ranges.sort()
    merged: list[list[int]] = []
    for range_start, range_end in ranges:
        if merged and merged[-1][1] == range_start:
            merged[-1][1] = range_end
        else:
            merged.append([range_start, range_end])
    metadata["received_ranges"] = merged


def transfer_begin_write(
    path: str, overwrite: bool = True, expected_bytes: int | None = None
) -> dict[str, Any]:
    dst = resolve_path(path, follow_final_symlink=False)
    expected = None if expected_bytes is None else int(expected_bytes)
    if expected is not None and expected < 0:
        raise ValueError("expected_bytes must be >= 0")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with _path_lock(dst):
        if os.path.lexists(dst) and dst.is_dir() and not dst.is_symlink():
            raise IsADirectoryError(str(dst))
        if os.path.lexists(dst) and not overwrite:
            raise FileExistsError(str(dst))
        transfer_id = uuid.uuid4().hex
        tmp = _transfer_temp_path(dst, transfer_id)
        with tmp.open("xb"):
            pass
        refresh_temp_file_lease(tmp)
        refresh_temp_file_lease(_transfer_metadata_path(tmp))
        try:
            _write_transfer_metadata(
                tmp,
                {
                    "destination": str(dst),
                    "overwrite": bool(overwrite),
                    "expected_bytes": expected,
                    "received_ranges": [],
                },
            )
        except Exception:
            tmp.unlink(missing_ok=True)
            release_temp_file_lease(tmp)
            release_temp_file_lease(_transfer_metadata_path(tmp))
            raise
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "transfer_id": transfer_id,
        "created": not os.path.lexists(dst),
        "expected_bytes": expected,
    }


def transfer_write_chunk(
    path: str,
    transfer_id: str,
    offset: int,
    data_b64: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    start = int(offset)
    if start < 0:
        raise ValueError("offset must be >= 0")
    try:
        data = base64.b64decode(data_b64.encode("ascii"), validate=True)
    except binascii.Error as exc:
        raise ValueError("data_b64 is not valid base64") from exc
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("chunk sha256 mismatch")
    return _write_transfer_payload(dst, tmp, start, data, digest)


def _write_transfer_payload(
    dst: Path,
    tmp: Path,
    start: int,
    payload: bytes,
    digest: str,
) -> dict[str, Any]:
    refresh_temp_file_lease(tmp, create=False)
    refresh_temp_file_lease(_transfer_metadata_path(tmp), create=False)
    with _path_lock(tmp):
        if not tmp.exists():
            raise FileNotFoundError(str(tmp))
        metadata = _read_transfer_metadata(tmp)
        expected = metadata.get("expected_bytes")
        if expected is not None and start + len(payload) > int(expected):
            raise ValueError("chunk exceeds expected transfer size")
        _record_received_range(metadata, start, start + len(payload))
        with tmp.open("r+b") as fh:
            fh.seek(start)
            fh.write(payload)
            fh.flush()
        _write_transfer_metadata(tmp, metadata)
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "offset": start,
        "bytes": len(payload),
        "sha256": digest,
    }


def transfer_write_bytes(
    path: str,
    transfer_id: str,
    offset: int,
    data: bytes,
) -> dict[str, Any]:
    """Write an already-decoded binary chunk into a transactional transfer."""

    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    start = int(offset)
    if start < 0:
        raise ValueError("offset must be >= 0")
    payload = bytes(data)
    return _write_transfer_payload(
        dst,
        tmp,
        start,
        payload,
        hashlib.sha256(payload).hexdigest(),
    )


def transfer_prepare_stream_write(path: str, transfer_id: str) -> dict[str, Any]:
    """Reset a transactional temp file for one sequential raw-binary upload."""

    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    metadata_path = _transfer_metadata_path(tmp)
    refresh_temp_file_lease(tmp, create=False)
    refresh_temp_file_lease(metadata_path, create=False)
    with _path_lock(tmp):
        if not tmp.exists():
            raise FileNotFoundError(str(tmp))
        metadata = _read_transfer_metadata(tmp)
        with tmp.open("wb"):
            pass
        metadata["received_ranges"] = []
        _write_transfer_metadata(tmp, metadata)
    return {
        "path": relative_display(dst),
        "temp_path": str(tmp),
        "expected_bytes": metadata.get("expected_bytes"),
    }


def transfer_refresh_stream_write(path: str, transfer_id: str) -> None:
    """Refresh temp-file leases for an active sequential raw-binary upload."""

    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    metadata_path = _transfer_metadata_path(tmp)
    if not tmp.exists() or not metadata_path.exists():
        raise FileNotFoundError(str(tmp if not tmp.exists() else metadata_path))
    refresh_temp_file_lease(tmp, create=False)
    refresh_temp_file_lease(metadata_path, create=False)


def transfer_mark_complete_write(path: str, transfer_id: str) -> dict[str, Any]:
    """Record that an external sequential writer populated the whole transfer temp file."""

    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    refresh_temp_file_lease(tmp, create=False)
    refresh_temp_file_lease(_transfer_metadata_path(tmp), create=False)
    with _path_lock(tmp):
        if not tmp.exists():
            raise FileNotFoundError(str(tmp))
        metadata = _read_transfer_metadata(tmp)
        expected = metadata.get("expected_bytes")
        size = tmp.stat().st_size
        if expected is not None and size != int(expected):
            raise ValueError(f"size mismatch: expected {expected}, got {size}")
        metadata["received_ranges"] = [] if size == 0 else [[0, size]]
        _write_transfer_metadata(tmp, metadata)
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "bytes": size,
    }


def _finish_transfer_write(
    path: str,
    transfer_id: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
    mark_complete: bool = False,
) -> dict[str, Any]:
    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    metadata_path = _transfer_metadata_path(tmp)
    refresh_temp_file_lease(tmp, create=False)
    refresh_temp_file_lease(metadata_path, create=False)
    with _path_locks([dst, tmp]):
        if not tmp.exists():
            raise FileNotFoundError(str(tmp))
        metadata = _read_transfer_metadata(tmp)
        expected = (
            int(expected_bytes) if expected_bytes is not None else metadata.get("expected_bytes")
        )
        if expected is not None:
            expected = int(expected)
        size = tmp.stat().st_size
        if expected is not None and size != expected:
            raise ValueError(f"size mismatch: expected {expected}, got {size}")
        if mark_complete:
            metadata["received_ranges"] = [] if size == 0 else [[0, size]]
            _write_transfer_metadata(tmp, metadata)
        received = _received_ranges(metadata)
        required_size = size if expected is None else expected
        complete = received == [] if required_size == 0 else received == [[0, required_size]]
        if not complete:
            raise ValueError("transfer has missing or non-contiguous data ranges")
        digest = _sha256_file(tmp) if expected_sha256 else None
        if expected_sha256 and digest != expected_sha256:
            raise ValueError("file sha256 mismatch")
        if not bool(metadata.get("overwrite", True)) and os.path.lexists(dst):
            raise FileExistsError(str(dst))
        destination_lease_created = acquire_temp_file_lease(dst)
        try:
            os.replace(tmp, dst)
        except Exception:
            if destination_lease_created:
                release_temp_file_lease(dst)
            raise
        metadata_path.unlink(missing_ok=True)
        release_temp_file_lease(tmp)
        release_temp_file_lease(metadata_path)
    return {
        "path": relative_display(dst),
        "bytes": size,
        "sha256": digest,
        "completed": True,
    }


def transfer_finish_write(
    path: str,
    transfer_id: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    return _finish_transfer_write(
        path,
        transfer_id,
        expected_bytes,
        expected_sha256,
    )


def transfer_finish_verified_write(
    path: str,
    transfer_id: str,
    expected_bytes: int,
    expected_sha256: str,
    verified_sha256: str,
) -> dict[str, Any]:
    """Commit a sequential upload after checking its streaming and staged digests."""

    streamed_digest = str(verified_sha256).lower()
    if len(streamed_digest) != 64 or any(
        character not in "0123456789abcdef" for character in streamed_digest
    ):
        raise ValueError("verified_sha256 must be a SHA-256 digest")
    if streamed_digest != str(expected_sha256).lower():
        raise ValueError("file sha256 mismatch")
    return _finish_transfer_write(
        path,
        transfer_id,
        expected_bytes,
        expected_sha256,
        mark_complete=True,
    )


def transfer_abort_write(path: str, transfer_id: str) -> dict[str, Any]:
    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    metadata_path = _transfer_metadata_path(tmp)
    deleted = False
    with _path_lock(tmp):
        if tmp.exists():
            tmp.unlink()
            deleted = True
        metadata_path.unlink(missing_ok=True)
        release_temp_file_lease(tmp)
        release_temp_file_lease(metadata_path)
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "deleted": deleted,
    }


def transfer_alloc_temp_path(suffix: str = ".bin") -> dict[str, Any]:
    prune_temp_dir()
    safe_suffix = (
        suffix if suffix.startswith(".") and "/" not in suffix and "\\" not in suffix else ".bin"
    )
    path = temp_dir() / f"remote-transfer-{uuid.uuid4().hex}{safe_suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return {"path": relative_display(path)}


def transfer_pack_dir(
    path: str,
    compression: str = "gz",
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    prune_temp_dir()
    if compression not in {"gz", "none"}:
        raise ValueError("compression must be 'gz' or 'none'")
    src = resolve_path(path, must_exist=True)
    if not src.is_dir():
        raise NotADirectoryError(str(src))
    _raise_if_cancelled(cancel_event)
    snapshot = _snapshot_transferable_tree(src, cancel_event)
    suffix = ".tar.gz" if compression == "gz" else ".tar"
    mode = "w:gz" if compression == "gz" else "w"
    archive = temp_dir() / f"transfer-pack-{uuid.uuid4().hex}{suffix}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    refresh_temp_file_lease(archive)
    try:
        last_lease_refresh = 0.0
        with tarfile.open(archive, mode) as tar:
            for relative, signature in snapshot.items():
                last_lease_refresh = _poll_transfer_activity(
                    cancel_event,
                    archive,
                    last_lease_refresh,
                )
                source = src / relative
                if _entry_signature(source) != signature:
                    raise RuntimeError(
                        "source directory changed during packing; retry after writes finish"
                    )
                info = tar.gettarinfo(str(source), arcname=relative)
                if signature[0] == "dir":
                    tar.addfile(info)
                    continue
                with source.open("rb") as handle:
                    tar.addfile(
                        info,
                        _LeaseRefreshingReader(handle, archive, cancel_event),
                    )
                if _entry_signature(source) != signature:
                    raise RuntimeError(
                        "source directory changed during packing; retry after writes finish"
                    )
        _raise_if_cancelled(cancel_event)
        if _snapshot_transferable_tree(src, cancel_event, archive) != snapshot:
            raise RuntimeError("source directory changed during packing; retry after writes finish")
        size = archive.stat().st_size
        digest = _sha256_file(archive, cancel_event=cancel_event)
    except Exception:
        archive.unlink(missing_ok=True)
        release_temp_file_lease(archive)
        raise
    return {
        "path": relative_display(src),
        "archive_path": relative_display(archive),
        "bytes": size,
        "sha256": digest,
        "compression": compression,
    }


async def transfer_pack_dir_async(path: str, compression: str = "gz") -> dict[str, Any]:
    return await _run_cancellable_transfer(
        transfer_pack_dir,
        path,
        compression,
        cancelled_result_cleanup=_cleanup_cancelled_pack_result,
    )


def _safe_members(
    tar: tarfile.TarFile,
    dst: Path,
    cancel_event: threading.Event | None = None,
    lease_path: Path | None = None,
) -> list[tarfile.TarInfo]:
    settings = get_settings()
    base = dst.resolve(strict=False)
    max_entries = max(1, settings.max_transfer_archive_entries)
    total_bytes = 0
    seen_paths: set[str] = set()
    safe: list[tarfile.TarInfo] = []
    members = iter(tar) if hasattr(tar, "__iter__") else iter(tar.getmembers())
    for member in members:
        _raise_if_cancelled(cancel_event)
        if lease_path is not None:
            refresh_temp_file_lease(lease_path, create=False)
        if len(safe) >= max_entries:
            raise ValueError(f"archive contains more than {max_entries} entries")
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"unsafe archive member path: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError(f"unsupported archive member type: {member.name}")
        if getattr(member, "sparse", None):
            raise ValueError(f"sparse archive members are not supported: {member.name}")
        normalized_name = str(member_path)
        if normalized_name in seen_paths:
            raise ValueError(f"duplicate archive member path: {member.name}")
        seen_paths.add(normalized_name)
        if member.isfile():
            total_bytes += max(0, int(member.size))
            max_bytes = max(1, settings.max_transfer_unpacked_bytes)
            if total_bytes > max_bytes:
                raise ValueError(f"archive expands to more than {max_bytes} bytes")
        target = (dst / member.name).resolve(strict=False)
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"archive member escapes destination: {member.name}") from exc
        safe.append(member)
    return safe


def _remove_existing_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def transfer_unpack_archive(
    archive_path: str,
    dst_path: str,
    overwrite: bool = True,
    cleanup_archive: bool = True,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    archive = resolve_path(archive_path, must_exist=True)
    if not archive.is_file():
        raise FileNotFoundError(str(archive))
    refresh_temp_file_lease(archive, create=False)
    _raise_if_cancelled(cancel_event)
    dst = resolve_path(dst_path, follow_final_symlink=False)
    dst.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{dst.name}.unpack-", dir=str(dst.parent)))
    backup: Path | None = None
    members: list[tarfile.TarInfo] = []
    committed = False
    try:
        with archive.open("rb") as archive_handle:
            archive_reader = _LeaseRefreshingReader(archive_handle, archive, cancel_event)
            with tarfile.open(fileobj=archive_reader, mode="r:*") as tar:
                members = _safe_members(tar, staging, cancel_event, archive)
                for member in members:
                    _raise_if_cancelled(cancel_event)
                    target = staging / member.name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    if member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source = tar.extractfile(member)
                        if source is None:
                            raise ValueError(f"archive member has no file data: {member.name}")
                        with source, target.open("xb") as out:
                            _copy_stream(
                                source,
                                out,
                                lease_path=archive,
                                cancel_event=cancel_event,
                            )
                        os.chmod(target, member.mode & 0o777)
                        continue
                    raise ValueError(f"unsupported archive member type: {member.name}")

        _raise_if_cancelled(cancel_event)
        with _path_lock(dst):
            exists = os.path.lexists(dst)
            if (
                exists
                and not overwrite
                and not (dst.is_dir() and not dst.is_symlink() and not any(dst.iterdir()))
            ):
                raise FileExistsError(f"destination already exists: {dst}")
            if exists:
                backup = dst.parent / f".{dst.name}.backup-{uuid.uuid4().hex}"
                os.replace(dst, backup)
            try:
                os.replace(staging, dst)
                committed = True
            except Exception:
                if backup is not None and os.path.lexists(backup):
                    os.replace(backup, dst)
                    backup = None
                raise

        cleanup_errors: list[str] = []
        backup_deleted = backup is None or not os.path.lexists(backup)
        if not backup_deleted and backup is not None:
            try:
                _remove_existing_path(backup)
            except OSError as exc:
                cleanup_errors.append(
                    f"could not remove replaced destination backup {backup}: {exc}"
                )
            else:
                backup = None
                backup_deleted = True

        archive_deleted = False
        if cleanup_archive:
            try:
                archive.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append(f"could not remove transfer archive {archive}: {exc}")
            else:
                archive_deleted = not archive.exists()
                if archive_deleted:
                    release_temp_file_lease(archive)
        return {
            "path": relative_display(dst),
            "archive_path": relative_display(archive),
            "entries": len(members),
            "completed": True,
            "archive_deleted": archive_deleted,
            "backup_deleted": backup_deleted,
            "cleanup_errors": cleanup_errors,
        }
    finally:
        if not committed and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if not committed and backup is not None and os.path.lexists(backup):
            if not os.path.lexists(dst):
                with contextlib.suppress(OSError):
                    os.replace(backup, dst)
            if os.path.lexists(backup):
                with contextlib.suppress(OSError):
                    _remove_existing_path(backup)


async def transfer_unpack_archive_async(
    archive_path: str,
    dst_path: str,
    overwrite: bool = True,
    cleanup_archive: bool = True,
) -> dict[str, Any]:
    return await _run_cancellable_transfer(
        transfer_unpack_archive,
        archive_path,
        dst_path,
        overwrite,
        cleanup_archive,
    )
