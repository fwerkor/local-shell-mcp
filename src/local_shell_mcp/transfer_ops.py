from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .fs_ops import (
    _path_lock,
    _path_locks,
    prune_temp_dir,
    relative_display,
    resolve_path,
    temp_dir,
)
from .settings import get_settings

DEFAULT_TRANSFER_CHUNK_BYTES = 1024 * 1024
MAX_TRANSFER_CHUNK_BYTES = 4 * 1024 * 1024
_TRANSFER_TMP_MARKER = "local-shell-mcp-transfer"


def normalize_chunk_size(chunk_size: int | None = None) -> int:
    requested = DEFAULT_TRANSFER_CHUNK_BYTES if chunk_size is None else int(chunk_size)
    if requested <= 0:
        raise ValueError("chunk_size must be greater than zero")
    return min(requested, MAX_TRANSFER_CHUNK_BYTES)


def _sha256_file(path: Path, chunk_size: int = DEFAULT_TRANSFER_CHUNK_BYTES) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def transfer_stat(path: str, sha256: bool = True) -> dict[str, Any]:
    p = resolve_path(path, must_exist=True)
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
    try:
        temporary.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        with contextlib.suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_transfer_metadata(tmp: Path) -> dict[str, Any]:
    path = _transfer_metadata_path(tmp)
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"transfer metadata is missing or invalid: {path}") from exc
    if not isinstance(metadata, dict):
        raise ValueError(f"transfer metadata is invalid: {path}")
    return metadata


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
        try:
            _write_transfer_metadata(
                tmp,
                {
                    "destination": str(dst),
                    "overwrite": bool(overwrite),
                    "expected_bytes": expected,
                },
            )
        except Exception:
            tmp.unlink(missing_ok=True)
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
    with _path_lock(tmp):
        if not tmp.exists():
            raise FileNotFoundError(str(tmp))
        metadata = _read_transfer_metadata(tmp)
        expected = metadata.get("expected_bytes")
        if expected is not None and start + len(data) > int(expected):
            raise ValueError("chunk exceeds expected transfer size")
        with tmp.open("r+b") as fh:
            fh.seek(start)
            fh.write(data)
            fh.flush()
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "offset": start,
        "bytes": len(data),
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
    with _path_lock(tmp):
        if not tmp.exists():
            raise FileNotFoundError(str(tmp))
        metadata = _read_transfer_metadata(tmp)
        expected = metadata.get("expected_bytes")
        if expected is not None and start + len(payload) > int(expected):
            raise ValueError("chunk exceeds expected transfer size")
        with tmp.open("r+b") as fh:
            fh.seek(start)
            fh.write(payload)
            fh.flush()
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "offset": start,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def transfer_finish_write(
    path: str,
    transfer_id: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    dst = resolve_path(path, follow_final_symlink=False)
    tmp = _transfer_temp_path(dst, transfer_id)
    metadata_path = _transfer_metadata_path(tmp)
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
        digest = _sha256_file(tmp) if expected_sha256 else None
        if expected_sha256 and digest != expected_sha256:
            raise ValueError("file sha256 mismatch")
        if not bool(metadata.get("overwrite", True)) and os.path.lexists(dst):
            raise FileExistsError(str(dst))
        os.replace(tmp, dst)
        metadata_path.unlink(missing_ok=True)
    return {
        "path": relative_display(dst),
        "bytes": size,
        "sha256": digest,
        "completed": True,
    }


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


def _assert_no_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"directory transfer does not support symlinks: {relative_display(path)}")
    for child in path.rglob("*"):
        if child.is_symlink():
            raise ValueError(
                f"directory transfer does not support symlinks: {relative_display(child)}"
            )


def transfer_pack_dir(path: str, compression: str = "gz") -> dict[str, Any]:
    prune_temp_dir()
    src = resolve_path(path, must_exist=True)
    if not src.is_dir():
        raise NotADirectoryError(str(src))
    _assert_no_symlinks(src)
    suffix = ".tar.gz" if compression == "gz" else ".tar"
    mode = "w:gz" if compression == "gz" else "w"
    archive = temp_dir() / f"transfer-pack-{uuid.uuid4().hex}{suffix}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, mode) as tar:
            for child in src.iterdir():
                tar.add(child, arcname=child.name, recursive=True)
        size = archive.stat().st_size
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    return {
        "path": relative_display(src),
        "archive_path": relative_display(archive),
        "bytes": size,
        "sha256": _sha256_file(archive),
        "compression": compression,
    }


def _safe_members(tar: tarfile.TarFile, dst: Path) -> list[tarfile.TarInfo]:
    settings = get_settings()
    base = dst.resolve(strict=False)
    members = tar.getmembers()
    max_entries = max(1, settings.max_transfer_archive_entries)
    if len(members) > max_entries:
        raise ValueError(f"archive contains {len(members)} entries; max is {max_entries}")
    total_bytes = 0
    seen_paths: set[str] = set()
    safe: list[tarfile.TarInfo] = []
    for member in members:
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
) -> dict[str, Any]:
    archive = resolve_path(archive_path, must_exist=True)
    if not archive.is_file():
        raise FileNotFoundError(str(archive))
    dst = resolve_path(dst_path, follow_final_symlink=False)
    dst.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{dst.name}.unpack-", dir=str(dst.parent)))
    backup: Path | None = None
    members: list[tarfile.TarInfo] = []
    committed = False
    try:
        with tarfile.open(archive, "r:*") as tar:
            members = _safe_members(tar, staging)
            for member in members:
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
                        shutil.copyfileobj(source, out)
                    os.chmod(target, member.mode & 0o777)
                    continue
                raise ValueError(f"unsupported archive member type: {member.name}")

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
