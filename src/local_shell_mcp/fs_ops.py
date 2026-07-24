from __future__ import annotations

import base64
import binascii
import contextlib
import fnmatch
import hashlib
import os
import shutil
import tempfile
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .errors import PathNotFoundError
from .settings import get_settings

BINARY_CHECK_BYTES = 8192
BINARY_CONTROL_RATIO = 0.30
BINARY_PREVIEW_BYTES = 256
BINARY_MESSAGE = "Refusing to read binary file as text"


class FileConflictError(RuntimeError):
    pass


_PATH_LOCKS_GUARD = threading.Lock()


@dataclass
class _ThreadPathLock:
    lock: threading.RLock
    users: int = 0


_PATH_LOCKS: dict[str, _ThreadPathLock] = {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _thread_lock_for(path: Path) -> tuple[str, _ThreadPathLock]:
    key = str(path)
    with _PATH_LOCKS_GUARD:
        entry = _PATH_LOCKS.get(key)
        if entry is None:
            entry = _ThreadPathLock(threading.RLock())
            _PATH_LOCKS[key] = entry
        entry.users += 1
        return key, entry


def _release_thread_lock(key: str, entry: _ThreadPathLock) -> None:
    with _PATH_LOCKS_GUARD:
        entry.users -= 1
        if entry.users <= 0 and _PATH_LOCKS.get(key) is entry:
            _PATH_LOCKS.pop(key, None)


def _lock_shard_path(path: Path) -> Path:
    lock_dir = get_settings().state_dir / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return lock_dir / f"shard-{digest[:2]}.lock"


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    with path.open("a+b") as handle:
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _path_locks(paths: list[Path]) -> Iterator[None]:
    unique = sorted({str(path): path for path in paths}.values(), key=str)
    entries: list[tuple[str, _ThreadPathLock]] = []
    try:
        for path in unique:
            entries.append(_thread_lock_for(path))
        with ExitStack() as stack:
            for _key, entry in entries:
                stack.enter_context(entry.lock)
            shards = sorted({_lock_shard_path(path) for path in unique}, key=str)
            for shard in shards:
                stack.enter_context(_file_lock(shard))
            yield
    finally:
        for key, entry in reversed(entries):
            _release_thread_lock(key, entry)


@contextmanager
def _path_lock(path: Path) -> Iterator[None]:
    """Serialize one mutation using the shared multi-path lock implementation."""

    with _path_locks([path]):
        yield


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
    path: str | Path,
    *,
    must_exist: bool = False,
    allow_missing_parent: bool = True,
    follow_final_symlink: bool = True,
) -> Path:
    """Resolve a path while optionally preserving the final symlink itself.

    Parent symlinks are always resolved before the workspace boundary check. Read operations
    normally follow the final symlink; mutations such as delete, rename, copy, and move pass
    follow_final_symlink=False so they operate on the directory entry the user selected.
    """

    settings = get_settings()
    root = settings.workspace_root.resolve()
    raw = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not raw.is_absolute():
        raw = root / raw
    if follow_final_symlink:
        resolved = raw.resolve(strict=False)
    else:
        resolved_parent = raw.parent.resolve(strict=False)
        resolved = resolved_parent / raw.name if raw.name else resolved_parent

    if not settings.allow_full_container:
        boundary_path = resolved if follow_final_symlink else resolved.parent
        try:
            boundary_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc

    candidates: list[tuple[str, ...]] = [tuple(part.casefold() for part in resolved.parts)]
    with contextlib.suppress(ValueError):
        relative = resolved.relative_to(root)
        candidates.insert(0, tuple(part.casefold() for part in relative.parts))
    for denied in settings.path_denylist:
        normalized = tuple(
            part.casefold()
            for part in str(denied).replace("\\", "/").strip("/").split("/")
            if part
        )
        if not normalized:
            continue
        matched = any(
            len(parts) >= len(normalized) and parts[-len(normalized) :] == normalized
            for parts in candidates
        )
        if len(normalized) == 1:
            matched = matched or any(normalized[0] in parts for parts in candidates)
        if matched:
            raise PermissionError(f"Path is denylisted: {path}")

    exists = resolved.exists() if follow_final_symlink else os.path.lexists(resolved)
    if must_exist and not exists:
        raise PathNotFoundError(resolved)
    if not allow_missing_parent and not resolved.parent.exists():
        raise PathNotFoundError(resolved.parent)
    return resolved


def relative_display(path: Path) -> str:
    root = workspace_root()
    candidate = path if path.is_absolute() else root / path
    lexical = Path(os.path.abspath(candidate))
    try:
        return str(lexical.relative_to(root))
    except ValueError:
        return str(lexical)


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
            stat = item.lstat()
            is_link = item.is_symlink()
        except OSError:
            continue
        item_type = (
            "link"
            if is_link
            else "dir"
            if item.is_dir()
            else "file"
            if item.is_file()
            else "other"
        )
        row = {
            "path": relative_display(item),
            "type": item_type,
            "size": stat.st_size if item_type in {"file", "link"} else None,
            "modified": stat.st_mtime,
        }
        if is_link:
            with contextlib.suppress(OSError):
                row["target"] = os.readlink(item)
        out.append(row)
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


def _is_probably_binary(sample: bytes, *, continuation: bytes = b"") -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason != "unexpected end of data" or exc.end != len(sample):
            return True

        lead = sample[exc.start]
        width = 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4
        missing = width - (len(sample) - exc.start)
        sequence = sample[exc.start:] + continuation[:missing]
        try:
            sequence.decode("utf-8")
        except UnicodeDecodeError:
            return True

    control_bytes = 0
    for byte in sample:
        if byte in (9, 10, 12, 13):
            continue
        if byte < 32 or byte == 127:
            control_bytes += 1
    return (control_bytes / len(sample)) > BINARY_CONTROL_RATIO


def _binary_metadata(p: Path, size: int, preview: str | None = None, preview_bytes: int = BINARY_PREVIEW_BYTES) -> dict:
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
        probe = fh.read(BINARY_CHECK_BYTES + 3)
    sample = probe[:BINARY_CHECK_BYTES]
    continuation = probe[BINARY_CHECK_BYTES:]
    if _is_probably_binary(sample, continuation=continuation):
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
        probe = fh.read(BINARY_CHECK_BYTES + 3)
        sample = probe[:BINARY_CHECK_BYTES]
        continuation = probe[BINARY_CHECK_BYTES:]
        if _is_probably_binary(sample, continuation=continuation):
            return _binary_metadata(p, size, binary_preview, binary_preview_bytes)
        fh.seek(0)
        data = fh.read(settings.max_file_read_bytes + 1)

    truncated = False
    if len(data) > settings.max_file_read_bytes:
        data = data[: settings.max_file_read_bytes]
        truncated = True
    truncated_bytes = max(0, size - len(data))
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
        "bytes": size,
        "bytes_read": len(data),
        "truncated_bytes": truncated_bytes,
        "binary": False,
        "total_lines": total_lines,
        "truncated": truncated,
        "sha256": hashlib.sha256(data).hexdigest() if not truncated else None,
        "content": text,
    }


def read_texts(
    paths: str | list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = BINARY_PREVIEW_BYTES,
) -> dict:
    """Read one or more files while enforcing the aggregate read limits."""

    many = isinstance(paths, list)
    normalized = paths if many else [paths]
    settings = get_settings()
    if not normalized:
        raise ValueError("paths must not be empty")
    if len(normalized) > settings.max_read_many_files:
        raise ValueError(
            f"Refusing to read {len(normalized)} files; max is {settings.max_read_many_files}"
        )

    files: list[dict] = []
    total_content_bytes = 0
    for path in normalized:
        item = read_text(
            path,
            start_line,
            end_line,
            binary_preview,
            binary_preview_bytes,
        )
        for field in ("content", "preview"):
            value = item.get(field)
            if isinstance(value, str):
                total_content_bytes += len(value.encode("utf-8"))
        if total_content_bytes > settings.max_read_many_total_bytes:
            raise ValueError(
                f"Refusing to return {total_content_bytes} bytes from read_file; "
                f"max is {settings.max_read_many_total_bytes}"
            )
        files.append(item)

    if not many:
        return files[0]
    return {"files": files, "total_content_bytes": total_content_bytes}


def write_text(
    path: str,
    content: str,
    overwrite: bool = True,
    expected_sha256: str | None = None,
) -> dict:
    settings = get_settings()
    data = content.encode("utf-8")
    if len(data) > settings.max_file_write_bytes:
        raise ValueError(f"Refusing to write {len(data)} bytes; max is {settings.max_file_write_bytes}")
    p = resolve_path(path)
    with _path_lock(p):
        exists = p.exists()
        if exists and not overwrite:
            raise FileExistsError(str(p))
        if expected_sha256 is not None:
            if not exists:
                raise FileConflictError("File was deleted after it was opened; reload before saving")
            if _sha256_file(p) != expected_sha256:
                raise FileConflictError("File changed after it was opened; reload before saving")
        p.parent.mkdir(parents=True, exist_ok=True)
        created = not exists
        previous_mode = p.stat().st_mode & 0o777 if exists else None
        fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if previous_mode is not None:
                tmp.chmod(previous_mode)
            if expected_sha256 is not None and (
                not p.exists() or _sha256_file(p) != expected_sha256
            ):
                raise FileConflictError("File changed while it was being saved; reload before saving")
            tmp.replace(p)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
    return {
        "path": relative_display(p),
        "bytes": len(data),
        "created": created,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def perform_file_action(
    action: str,
    path: str,
    destination: str | None = None,
    *,
    exist_ok: bool = False,
) -> dict:
    """Perform a bounded file-manager mutation under the configured path policy."""

    if action not in {"mkdir", "touch", "rename", "copy", "move"}:
        raise ValueError(f"Unsupported file action: {action}")

    source = resolve_path(
        path,
        must_exist=action in {"rename", "copy", "move"},
        follow_final_symlink=False,
    )
    if action in {"mkdir", "touch"}:
        with _path_lock(source):
            if os.path.lexists(source):
                if not exist_ok:
                    raise FileExistsError(str(source))
                if action == "mkdir" and not (source.is_dir() and not source.is_symlink()):
                    raise FileExistsError(f"mkdir target exists and is not a directory: {source}")
                if action == "touch" and (source.is_dir() or source.is_symlink()):
                    raise FileExistsError(f"touch target exists and is not a regular file: {source}")
                return {"action": action, "path": relative_display(source)}
            if action == "mkdir":
                source.mkdir(parents=True)
            else:
                source.parent.mkdir(parents=True, exist_ok=True)
                source.touch(exist_ok=False)
        return {"action": action, "path": relative_display(source)}

    if not destination:
        raise ValueError("destination is required")
    target = resolve_path(
        destination,
        allow_missing_parent=False,
        follow_final_symlink=False,
    )
    with _path_locks([source, target]):
        if not os.path.lexists(source):
            raise PathNotFoundError(source)
        if os.path.lexists(target):
            raise FileExistsError(str(target))
        if source == target:
            raise ValueError("Source and destination are the same path")
        source_is_directory = source.is_dir() and not source.is_symlink()
        if source_is_directory:
            try:
                target.relative_to(source)
            except ValueError:
                pass
            else:
                raise ValueError("Destination cannot be inside the source directory")

        if action == "rename":
            source.rename(target)
        elif action == "copy":
            if source.is_symlink():
                os.symlink(
                    os.readlink(source),
                    target,
                    target_is_directory=source.is_dir(),
                )
            elif source_is_directory:
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)
        else:
            shutil.move(str(source), str(target))
    return {
        "action": action,
        "path": relative_display(source),
        "destination": relative_display(target),
    }


def _validated_text_edits(edits: list[dict]) -> list[dict[str, str | bool]]:
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits must not be empty")
    validated: list[dict[str, str | bool]] = []
    allowed = {"old", "new", "replace_all"}
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise ValueError(f"edits[{index}] must be an object")
        unexpected = sorted(set(edit) - allowed)
        if unexpected:
            raise ValueError(
                f"edits[{index}] contains unsupported field(s): {', '.join(unexpected)}"
            )
        missing = sorted({"old", "new"} - set(edit))
        if missing:
            raise ValueError(f"edits[{index}] is missing field(s): {', '.join(missing)}")
        old = edit["old"]
        new = edit["new"]
        replace_all = edit.get("replace_all", False)
        if not isinstance(old, str):
            raise ValueError(f"edits[{index}].old must be a string")
        if not isinstance(new, str):
            raise ValueError(f"edits[{index}].new must be a string")
        if not isinstance(replace_all, bool):
            raise ValueError(f"edits[{index}].replace_all must be a boolean")
        if not old:
            raise ValueError(f"edits[{index}].old must not be empty")
        validated.append({"old": old, "new": new, "replace_all": replace_all})
    return validated


def edit_text(path: str, edits: list[dict]) -> dict:
    validated_edits = _validated_text_edits(edits)
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
    if p.stat().st_size > settings.max_file_write_bytes:
        raise ValueError(f"Refusing to edit {p.stat().st_size} bytes; max is {settings.max_file_write_bytes}")
    _assert_text_file(p)
    expected_sha256 = _sha256_file(p)
    text = p.read_text(encoding="utf-8")
    total = 0
    for edit in validated_edits:
        old = str(edit["old"])
        new = str(edit["new"])
        replace_all = bool(edit["replace_all"])
        count = text.count(old)
        if count == 0:
            raise ValueError(f"old text not found: {old[:80]!r}")
        if not replace_all and count > 1:
            raise ValueError(f"old text occurs {count} times: {old[:80]!r}")
        text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        total += count if replace_all else 1
    updated_bytes = len(text.encode("utf-8"))
    if updated_bytes > settings.max_file_write_bytes:
        raise ValueError(f"Refusing to write {updated_bytes} bytes; max is {settings.max_file_write_bytes}")
    write_text(path, text, overwrite=True, expected_sha256=expected_sha256)
    return {"path": relative_display(p), "replacements": total}


def delete_path(path: str, recursive: bool = False) -> dict:
    p = resolve_path(path, must_exist=True, follow_final_symlink=False)
    with _path_lock(p):
        if not os.path.lexists(p):
            raise PathNotFoundError(p)
        if p.is_symlink():
            p.unlink()
            return {"path": relative_display(p), "deleted": "link"}
        if p.is_dir():
            if not recursive:
                raise IsADirectoryError("Set recursive=true to delete a directory")
            shutil.rmtree(p)
            return {"path": relative_display(p), "deleted": "directory"}
        p.unlink()
        return {"path": relative_display(p), "deleted": "file"}

