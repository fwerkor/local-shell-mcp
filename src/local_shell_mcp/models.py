from __future__ import annotations

from typing import Any


def ok_result(data: Any = None, message: str = "") -> dict[str, Any]:
    return {"ok": True, "message": message, "data": data}


try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - exercised in dependency-light worker bootstraps.
    from dataclasses import asdict, dataclass, field
    class _ModelMixin:
        def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002
            return asdict(self)

    @dataclass
    class ToolResult(_ModelMixin):
        ok: bool = True
        message: str = ""
        data: dict | list | str | int | float | bool | None = None

    @dataclass
    class CommandResult(_ModelMixin):
        ok: bool = False
        exit_code: int | None = None
        timed_out: bool = False
        duration_ms: int = 0
        cwd: str = ""
        command: str = ""
        stdout: str = ""
        stderr: str = ""
        truncated: bool = False

    @dataclass
    class FileEntry(_ModelMixin):
        path: str = ""
        type: str = ""
        size: int | None = None
        modified: float | None = None

    @dataclass
    class ShellSession(_ModelMixin):
        session_id: str = ""
        name: str = ""
        cwd: str = ""
        created_at: float = 0.0
        alive: bool = True

    @dataclass
    class GrepMatch(_ModelMixin):
        path: str = ""
        line: int = 0
        column: int | None = None
        text: str = ""

    @dataclass
    class BrowserResult(_ModelMixin):
        ok: bool = False
        url: str | None = None
        title: str | None = None
        text: str | None = None
        screenshot_path: str | None = None
        pdf_path: str | None = None
        html_path: str | None = None
        console: list[str] = field(default_factory=list)
else:

    class ToolResult(BaseModel):
        ok: bool = True
        message: str = ""
        data: dict | list | str | int | float | bool | None = None


    class CommandResult(BaseModel):
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
        path: str
        type: str
        size: int | None = None
        modified: float | None = None


    class ShellSession(BaseModel):
        session_id: str
        name: str
        cwd: str
        created_at: float
        alive: bool = True


    class GrepMatch(BaseModel):
        path: str
        line: int
        column: int | None = None
        text: str


    class BrowserResult(BaseModel):
        ok: bool
        url: str | None = None
        title: str | None = None
        text: str | None = None
        screenshot_path: str | None = None
        pdf_path: str | None = None
        html_path: str | None = None
        console: list[str] = Field(default_factory=list)
