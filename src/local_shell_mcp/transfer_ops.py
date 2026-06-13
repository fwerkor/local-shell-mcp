from __future__ import annotations

import base64
import binascii
import hashlib
import os
import shutil
import tarfile
import uuid
from pathlib import Path
from typing import Any

from .fs_ops import relative_display, resolve_path, temp_dir

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


def transfer_read_chunk(path: str, offset: int = 0, chunk_size: int | None = None) -> dict[str, Any]:
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
    if not safe_id:
        raise ValueError("transfer_id is empty")
    return dst.parent / f".{dst.name}.{_TRANSFER_TMP_MARKER}-{safe_id}.tmp"


def transfer_begin_write(path: str, overwrite: bool = True, expected_bytes: int | None = None) -> dict[str, Any]:
    dst = resolve_path(path)
    if dst.exists() and dst.is_dir():
        raise IsADirectoryError(str(dst))
    if dst.exists() and not overwrite:
        raise FileExistsError(str(dst))
    if expected_bytes is not None and int(expected_bytes) < 0:
        raise ValueError("expected_bytes must be >= 0")
    dst.parent.mkdir(parents=True, exist_ok=True)
    transfer_id = uuid.uuid4().hex
    tmp = _transfer_temp_path(dst, transfer_id)
    with tmp.open("wb"):
        pass
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "transfer_id": transfer_id,
        "created": not dst.exists(),
        "expected_bytes": expected_bytes,
    }


def transfer_write_chunk(
    path: str,
    transfer_id: str,
    offset: int,
    data_b64: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    dst = resolve_path(path)
    tmp = _transfer_temp_path(dst, transfer_id)
    if not tmp.exists():
        raise FileNotFoundError(str(tmp))
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
    with tmp.open("r+b") as fh:
        fh.seek(start)
        fh.write(data)
    return {
        "path": relative_display(dst),
        "temp_path": relative_display(tmp),
        "offset": start,
        "bytes": len(data),
        "sha256": digest,
    }


def transfer_finish_write(
    path: str,
    transfer_id: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    dst = resolve_path(path)
    tmp = _transfer_temp_path(dst, transfer_id)
    if not tmp.exists():
        raise FileNotFoundError(str(tmp))
    size = tmp.stat().st_size
    if expected_bytes is not None and size != int(expected_bytes):
        raise ValueError(f"size mismatch: expected {expected_bytes}, got {size}")
    digest = _sha256_file(tmp) if expected_sha256 else None
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("file sha256 mismatch")
    os.replace(tmp, dst)
    return {
        "path": relative_display(dst),
        "bytes": size,
        "sha256": digest,
        "completed": True,
    }


def transfer_abort_write(path: str, transfer_id: str) -> dict[str, Any]:
    dst = resolve_path(path)
    tmp = _transfer_temp_path(dst, transfer_id)
    deleted = False
    if tmp.exists():
        tmp.unlink()
        deleted = True
    return {"path": relative_display(dst), "temp_path": relative_display(tmp), "deleted": deleted}


def transfer_alloc_temp_path(suffix: str = ".bin") -> dict[str, Any]:
    safe_suffix = suffix if suffix.startswith(".") and "/" not in suffix and "\\" not in suffix else ".bin"
    path = temp_dir() / f"remote-transfer-{uuid.uuid4().hex}{safe_suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return {"path": relative_display(path)}


def transfer_pack_dir(path: str, compression: str = "gz") -> dict[str, Any]:
    src = resolve_path(path, must_exist=True)
    if not src.is_dir():
        raise NotADirectoryError(str(src))
    suffix = ".tar.gz" if compression == "gz" else ".tar"
    mode = "w:gz" if compression == "gz" else "w"
    archive = temp_dir() / f"transfer-pack-{uuid.uuid4().hex}{suffix}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode) as tar:
        for child in src.iterdir():
            tar.add(child, arcname=child.name, recursive=True)
    size = archive.stat().st_size
    return {
        "path": relative_display(src),
        "archive_path": relative_display(archive),
        "bytes": size,
        "sha256": _sha256_file(archive),
        "compression": compression,
    }


def _safe_members(tar: tarfile.TarFile, dst: Path) -> list[tarfile.TarInfo]:
    base = dst.resolve(strict=False)
    members: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"unsafe archive member path: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError(f"unsupported archive member type: {member.name}")
        target = (dst / member.name).resolve(strict=False)
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"archive member escapes destination: {member.name}") from exc
        members.append(member)
    return members


def transfer_unpack_archive(
    archive_path: str,
    dst_path: str,
    overwrite: bool = True,
    cleanup_archive: bool = True,
) -> dict[str, Any]:
    archive = resolve_path(archive_path, must_exist=True)
    if not archive.is_file():
        raise FileNotFoundError(str(archive))
    dst = resolve_path(dst_path)
    if dst.exists():
        if dst.is_file():
            if not overwrite:
                raise FileExistsError(str(dst))
            dst.unlink()
        elif dst.is_dir():
            if not overwrite and any(dst.iterdir()):
                raise FileExistsError(f"destination directory is not empty: {dst}")
            if overwrite:
                shutil.rmtree(dst)
        else:
            raise FileExistsError(str(dst))
    dst.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tar:
        members = _safe_members(tar, dst)
        for member in members:
            target = dst / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError(f"archive member has no file data: {member.name}")
                with source, target.open("wb") as out:
                    shutil.copyfileobj(source, out)
                os.chmod(target, member.mode & 0o777)
                continue
            raise ValueError(f"unsupported archive member type: {member.name}")
    if cleanup_archive:
        archive.unlink(missing_ok=True)
    return {
        "path": relative_display(dst),
        "archive_path": relative_display(archive),
        "entries": len(members),
        "completed": True,
        "archive_deleted": cleanup_archive,
    }
