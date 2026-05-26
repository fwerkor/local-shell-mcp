from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path

from .settings import get_settings


def workspace_root() -> Path:
    return get_settings().workspace_root.resolve()


def resolve_path(path: str | Path, *, must_exist: bool = False, allow_missing_parent: bool = True) -> Path:
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

    if not settings.allow_full_container and not str(resolved).startswith(str(root)):
        raise ValueError(f"Path escapes workspace: {path}")

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
        for child in sorted(nearest.iterdir()):
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
    base = resolve_path(path, must_exist=True)
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    out: list[dict] = []
    iterator = base.rglob("*") if recursive else base.iterdir()
    for item in iterator:
        if len(out) >= max_entries:
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
    base = resolve_path(cwd, must_exist=True)
    results: list[str] = []
    for item in base.rglob("*"):
        rel = str(item.relative_to(base))
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(item.name, pattern):
            results.append(relative_display(item))
            if len(results) >= max_results:
                break
    return results


def read_text(path: str, start_line: int | None = None, end_line: int | None = None) -> dict:
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
    data = p.read_bytes()
    truncated = False
    if len(data) > settings.max_file_read_bytes:
        data = data[: settings.max_file_read_bytes]
        truncated = True
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)
    if start_line is not None or end_line is not None:
        start = max(1, start_line or 1)
        end = min(total_lines, end_line or total_lines)
        selected = lines[start - 1 : end]
        text = "\n".join(selected)
    return {
        "path": relative_display(p),
        "bytes": len(data),
        "total_lines": total_lines,
        "truncated": truncated,
        "content": text,
    }


def write_text(path: str, content: str, overwrite: bool = True) -> dict:
    settings = get_settings()
    data = content.encode("utf-8")
    if len(data) > settings.max_file_write_bytes:
        raise ValueError(f"Refusing to write {len(data)} bytes; max is {settings.max_file_write_bytes}")
    p = resolve_path(path)
    if p.exists() and not overwrite:
        raise FileExistsError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    before = p.read_text(errors="replace") if p.exists() else None
    p.write_text(content, encoding="utf-8")
    return {
        "path": relative_display(p),
        "bytes": len(data),
        "created": before is None,
    }


def edit_text(path: str, old: str, new: str, replace_all: bool = False) -> dict:
    p = resolve_path(path, must_exist=True)
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        raise ValueError("old text not found")
    if not replace_all and count > 1:
        raise ValueError(f"old text occurs {count} times; set replace_all=true or provide more context")
    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    p.write_text(updated, encoding="utf-8")
    return {"path": relative_display(p), "replacements": count if replace_all else 1}


def multi_edit_text(path: str, edits: list[dict]) -> dict:
    p = resolve_path(path, must_exist=True)
    text = p.read_text(encoding="utf-8", errors="replace")
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
