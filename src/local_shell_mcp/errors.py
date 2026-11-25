from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any


class PathNotFoundError(FileNotFoundError):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        super().__init__(str(self.path))


class ShellExecutableNotFoundError(FileNotFoundError):
    """Raised when a configured shell executable cannot be started."""

    def __init__(self, executable: str, command: str, cwd: str, original_error: str) -> None:
        self.executable = executable
        self.command = command
        self.cwd = cwd
        self.original_error = original_error
        super().__init__(f"Shell executable not found: {executable}")


def process_start_not_found_error(
    exc: FileNotFoundError,
    *,
    executable: str,
    command: str,
    cwd: str | Path,
) -> FileNotFoundError:
    cwd_path = Path(cwd)
    missing = Path(exc.filename) if exc.filename else None
    if missing is not None and os.path.normcase(os.path.abspath(missing)) == os.path.normcase(
        os.path.abspath(cwd_path)
    ):
        return PathNotFoundError(cwd_path)
    if not cwd_path.exists():
        return PathNotFoundError(cwd_path)
    return ShellExecutableNotFoundError(executable, command, str(cwd_path), str(exc))


def workspace_path_not_found_error(
    exc: FileNotFoundError,
    workspace_root: str | Path,
) -> PathNotFoundError | None:
    root = Path(os.path.abspath(workspace_root))
    candidates: list[Path] = []
    for value in (exc.filename, exc.filename2):
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            continue
        lexical = Path(os.path.abspath(candidate))
        try:
            lexical.relative_to(root)
        except ValueError:
            continue
        candidates.append(lexical)
    for candidate in candidates:
        if not candidate.exists():
            return PathNotFoundError(candidate)
    return None


def tool_exception_payload(exc: Exception) -> tuple[dict[str, Any], str]:
    """Shared error details for local MCP and remote Worker responses."""
    if isinstance(exc, ShellExecutableNotFoundError):
        return {
            "status": "executable_not_found",
            "error_type": "FileNotFoundError",
            "message": str(exc),
            "executable": exc.executable,
            "command": exc.command,
            "cwd": exc.cwd,
            "original_error": exc.original_error,
        }, str(exc)
    path_error = exc if isinstance(exc, PathNotFoundError) else None
    if isinstance(exc, FileNotFoundError) and path_error is None:
        from .settings import get_settings

        path_error = workspace_path_not_found_error(exc, get_settings().workspace_root)
    if path_error is not None:
        # fs_ops imports the exception classes above; defer the reverse import.
        from .fs_ops import missing_path_context

        with contextlib.suppress(Exception):
            context = missing_path_context(path_error.path)
            return {
                "status": "not_found",
                "error_type": "FileNotFoundError",
                "message": str(exc),
                **context,
            }, f"Path not found: {context['path']}"
    message = str(exc) or type(exc).__name__
    return {
        "status": "error",
        "error_type": type(exc).__name__,
        "message": message,
    }, message
