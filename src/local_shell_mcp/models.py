"""Define shared response shapes returned by command, filesystem, shell-session, grep, and tool handlers."""

from __future__ import annotations

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Generic tool response envelope used for success, failure, and diagnostic payloads."""

    ok: bool = True
    message: str = ""
    data: dict | list | str | int | float | bool | None = None


class CommandResult(BaseModel):
    """Completed subprocess result including bounded stdout, stderr, timing, and timeout state."""

    ok: bool
    exit_code: int | None
    timed_out: bool = False
    duration_ms: int
    cwd: str
    command: str
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False


class FileEntry(BaseModel):
    """Directory listing entry with workspace display path and basic file metadata."""

    path: str
    type: str
    size: int | None = None
    modified: float | None = None


class ShellSession(BaseModel):
    """Persistent shell session descriptor returned by tmux session-management operations."""

    session_id: str
    name: str
    cwd: str
    created_at: float
    alive: bool = True


class GrepMatch(BaseModel):
    """One ripgrep match with display path, line number, text, and optional submatch spans."""

    path: str
    line: int
    column: int | None = None
    text: str
