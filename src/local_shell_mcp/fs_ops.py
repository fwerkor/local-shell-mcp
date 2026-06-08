from __future__ import annotations

import base64
import binascii
import fnmatch
import os
import shutil
from pathlib import Path

from .settings import get_settings

BINARY_CHECK_BYTES = 8192
BINARY_CONTROL_RATIO = 0.30
BINARY_PREVIEW_BYTES = 256
BINARY_MESSAGE = "Refusing to read binary file as text"


def workspace_root() -> Path:
    return get_settings().workspace_root.resolve()


def temp_dir() -> Path:
    path = get_settings().state_dir / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def prune_temp_dir() -> None:
    settings = get_settings()
    path = temp_dir()
    try:
        files = [item for item in path.iterdir() if item.is_file()]
    except OSError:
        return

    entries: list[tuple[float, int, Path]] = []
    for item in files:
        try:
            stat = item.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, item))

    entries.sort(reverse=True)
    total_bytes = 0
    for index, (_, size, item) in enumerate(entries):
        total_bytes += size
        if index < settings.max_tmp_files and total_bytes <= settings.max_tmp_bytes:
            continue
        try:
            item.unlink()
        except OSError:
            continue


def resolve_path(
    path: str | Path, *, must_exist: bool = False, allow_missing_parent: bool = True
) -> Path:
    """Resolve a path, optionally restricting it to workspace_root.

    In normal mode, absolute paths outside workspace are rejected. In full-container mode,
    any absolute path inside the container is allowed.
    """
    settings = get_settings()
    root = settings.workspace_root.resolve()
    raw = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not raw.is_absolute():
        raw = root / raw
    resolved = raw.resolve(strict=False)

    if not settings.allow_full_container:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc

    lower = str(resolved).lower()
    for denied in settings.path_denylist:
        if denied and denied.lower() in lower:
            raise PermissionError(f"Path is denylisted: {path}")

    if must_exist and not resolved.exists():
        raise FileNotFoundError(str(resolved))
    if not allow_missing_parent and not resolved.parent.exists():
        raise FileNotFoundError(str(resolved.parent))
    return resolved


def relative_display(path: Path) -> str:
    root = workspace_root()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def missing_path_context(path: str | Path, *, max_entries: int = 50) -> dict:
    resolved = resolve_path(path)
    nearest = next((parent for parent in [resolved, *resolved.parents] if parent.exists()), None)
    entries: list[str] = []
    truncated = False

    if nearest and nearest.is_dir():
        limit = max(0, max_entries)
        for child in nearest.iterdir():
            if child.name == ".git":
                continue
            if len(entries) >= limit:
                truncated = True
                break
            entries.append(f"{child.name}/" if child.is_dir() else child.name)

    return {
        "path": str(resolved),
        "exists": resolved.exists(),
        "nearest_existing_parent": str(nearest) if nearest else None,
        "nearest_parent_entries": entries,
        "truncated": truncated,
    }


def list_dir(path: str = ".", recursive: bool = False, max_entries: int = 500) -> list[dict]:
    settings = get_settings()
    base = resolve_path(path, must_exist=True)
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    out: list[dict] = []
    limit = max(1, min(max_entries, settings.max_directory_entries))
    iterator = base.rglob("*") if recursive else base.iterdir()
    for item in iterator:
        if len(out) >= limit:
            break
        try:
            stat = item.stat()
        except OSError:
            continue
        out.append(
            {
                "path": relative_display(item),
                "type": "dir" if item.is_dir() else "file" if item.is_file() else "other",
                "size": stat.st_size if item.is_file() else None,
                "modified": stat.st_mtime,
            }
        )
    return out


def glob_paths(pattern: str, cwd: str = ".", max_results: int = 500) -> list[str]:
    settings = get_settings()
    base = resolve_path(cwd, must_exist=True)
    results: list[str] = []
    limit = max(1, min(max_results, settings.max_glob_results))
    for item in base.rglob("*"):
        rel = str(item.relative_to(base))
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(item.name, pattern):
            results.append(relative_display(item))
            if len(results) >= limit:
                break
    return results


def _is_probably_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True

    control_bytes = 0
    for byte in sample:
        if byte in (9, 10, 12, 13):
            continue
        if byte < 32 or byte == 127:
            control_bytes += 1
    return (control_bytes / len(sample)) > BINARY_CONTROL_RATIO


def _binary_metadata(
    p: Path, size: int, preview: str | None = None, preview_bytes: int = BINARY_PREVIEW_BYTES
) -> dict:
    result = {
        "path": relative_display(p),
        "bytes": size,
        "binary": True,
        "content": None,
        "message": BINARY_MESSAGE,
    }
    if preview:
        limit = max(0, min(preview_bytes, BINARY_PREVIEW_BYTES))
        with p.open("rb") as fh:
            data = fh.read(limit)
        if preview == "hex":
            result["preview"] = binascii.hexlify(data).decode("ascii")
            result["preview_encoding"] = "hex"
            result["preview_bytes"] = len(data)
        elif preview == "base64":
            result["preview"] = base64.b64encode(data).decode("ascii")
            result["preview_encoding"] = "base64"
            result["preview_bytes"] = len(data)
        else:
            raise ValueError("binary_preview must be 'hex' or 'base64'")
    return result


def _assert_text_file(p: Path) -> None:
    with p.open("rb") as fh:
        sample = fh.read(BINARY_CHECK_BYTES)
    if _is_probably_binary(sample):
        raise ValueError(BINARY_MESSAGE)


def read_text(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = BINARY_PREVIEW_BYTES,
) -> dict:
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
    size = p.stat().st_size
    with p.open("rb") as fh:
        sample = fh.read(BINARY_CHECK_BYTES)
        if _is_probably_binary(sample):
            return _binary_metadata(p, size, binary_preview, binary_preview_bytes)
        fh.seek(0)
        data = fh.read(settings.max_file_read_bytes + 1)

    truncated = False
    if len(data) > settings.max_file_read_bytes:
        data = data[: settings.max_file_read_bytes]
        truncated = True
    truncated_bytes = max(0, size - len(data))
    text = data.decode("utf-8")
    lines = text.splitlines()
    total_lines = len(lines)
    if start_line is not None or end_line is not None:
        start = max(1, start_line or 1)
        end = min(total_lines, end_line or total_lines)
        selected = lines[start - 1 : end]
        text = "\n".join(selected)
    return {
        "path": relative_display(p),
        "bytes": size,
        "bytes_read": len(data),
        "truncated_bytes": truncated_bytes,
        "binary": False,
        "total_lines": total_lines,
        "truncated": truncated,
        "content": text,
    }


def write_text(path: str, content: str, overwrite: bool = True) -> dict:
    settings = get_settings()
    data = content.encode("utf-8")
    if len(data) > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {len(data)} bytes; max is {settings.max_file_write_bytes}"
        )
    p = resolve_path(path)
    if p.exists() and not overwrite:
        raise FileExistsError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    created = not p.exists()
    p.write_text(content, encoding="utf-8")
    return {
        "path": relative_display(p),
        "bytes": len(data),
        "created": created,
    }


def edit_text(path: str, old: str, new: str, replace_all: bool = False) -> dict:
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
    if p.stat().st_size > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to edit {p.stat().st_size} bytes; max is {settings.max_file_write_bytes}"
        )
    _assert_text_file(p)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ValueError("old text not found")
    if not replace_all and count > 1:
        raise ValueError(
            f"old text occurs {count} times; set replace_all=true or provide more context"
        )
    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    updated_bytes = len(updated.encode("utf-8"))
    if updated_bytes > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {updated_bytes} bytes; max is {settings.max_file_write_bytes}"
        )
    p.write_text(updated, encoding="utf-8")
    return {"path": relative_display(p), "replacements": count if replace_all else 1}


def multi_edit_text(path: str, edits: list[dict]) -> dict:
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
    if p.stat().st_size > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to edit {p.stat().st_size} bytes; max is {settings.max_file_write_bytes}"
        )
    _assert_text_file(p)
    text = p.read_text(encoding="utf-8")
    total = 0
    for edit in edits:
        old = str(edit["old"])
        new = str(edit["new"])
        replace_all = bool(edit.get("replace_all", False))
        count = text.count(old)
        if count == 0:
            raise ValueError(f"old text not found: {old[:80]!r}")
        if not replace_all and count > 1:
            raise ValueError(f"old text occurs {count} times: {old[:80]!r}")
        text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        total += count if replace_all else 1
    updated_bytes = len(text.encode("utf-8"))
    if updated_bytes > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {updated_bytes} bytes; max is {settings.max_file_write_bytes}"
        )
    p.write_text(text, encoding="utf-8")
    return {"path": relative_display(p), "replacements": total}


def delete_path(path: str, recursive: bool = False) -> dict:
    p = resolve_path(path, must_exist=True)
    if p.is_dir():
        if not recursive:
            raise IsADirectoryError("Set recursive=true to delete a directory")
        shutil.rmtree(p)
        return {"path": relative_display(p), "deleted": "directory"}
    p.unlink()
    return {"path": relative_display(p), "deleted": "file"}
