"""Filesystem helpers for the standalone external browser runtime.

The controller validates user-supplied paths with fs_ops before forwarding them.
This module avoids importing the controller and its dependencies into the
external Python process, which only needs Playwright and the standard library.
"""

from __future__ import annotations

import os
from pathlib import Path


def _workspace_root() -> Path:
    return Path(os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"]).resolve()


def resolve_path(path: str | Path, *, must_exist: bool = False) -> Path:
    root = _workspace_root()
    candidate = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if must_exist and not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def relative_display(path: Path) -> str:
    root = _workspace_root()
    candidate = path if path.is_absolute() else root / path
    lexical = Path(os.path.abspath(candidate))
    try:
        return str(lexical.relative_to(root))
    except ValueError:
        return str(lexical)
