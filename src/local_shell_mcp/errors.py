from __future__ import annotations

import os
from pathlib import Path


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
