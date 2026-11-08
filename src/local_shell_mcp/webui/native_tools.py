"""Explicitly scoped, read-only functions for the first Python Agent tool loop.

Neither shell execution nor dynamic MCP management is exposed here. Write and
external-network tools require a durable human approval flow before enablement.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..audit import audit
from .providers import ModelToolCall
from .routes import _repo

READ_ONLY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "List files in a directory within the local-shell-mcp workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 25},
                    "machine": {"type": "string", "description": "Target machine, defaults to local", "default": "local"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read a short UTF-8 excerpt from a text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path"},
                    "machine": {"type": "string", "description": "Target machine, defaults to local", "default": "local"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]


ASK_USER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Pause the Agent and ask the user a question before continuing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "description": {"type": "string"},
                    "options": {"type": "array", "items": {
                        "type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                        "required": ["label", "value"], "additionalProperties": False,
                    }},
                    "multiSelect": {"type": "boolean"},
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    },
]


WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write a short UTF-8 text file on a machine with explicit read/write permission.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path"},
                    "content": {"type": "string", "description": "UTF-8 file contents (max 16 KiB)"},
                    "overwrite": {"type": "boolean", "description": "Replace an existing file", "default": False},
                    "machine": {"type": "string", "description": "Machine name", "default": "local"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
]


def _path(root: Path, provided: object) -> Path:
    if not isinstance(provided, str) or not 0 < len(provided) <= 2048:
        raise ValueError("Invalid workspace-relative path")
    path = Path(provided)
    if path.is_absolute() or "\x00" in provided:
        raise ValueError("Only workspace-relative paths are allowed")
    home = root.resolve()
    resolved = (home / path).resolve(strict=True)
    if not resolved.is_relative_to(home):
        raise PermissionError("Path escapes the configured workspace")
    if any(part.startswith(".") for part in resolved.relative_to(home).parts):
        raise PermissionError("Hidden configuration and private state are not exposed to models")
    return resolved


def _execute(root: Path, call: ModelToolCall, private_state: Path | None = None) -> str:
    args = call.arguments

    def safe_path(value: object) -> Path:
        candidate = _path(root, value)
        if private_state is not None and candidate.is_relative_to(private_state.resolve()):
            raise PermissionError("Controller private state is not available to models")
        return candidate

    if call.name == "file_list":
        if set(args) - {"path", "limit", "machine"}:
            raise ValueError("Unsupported file-list argument")
        limit = args.get("limit", 25)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid directory entry limit")
        folder = safe_path(args.get("path", "."))
        if not folder.is_dir():
            raise ValueError("Expected a directory")
        entries = []
        for child in sorted(folder.iterdir(), key=lambda entry: entry.name):
            if len(entries) == limit:
                break
            if (child.is_symlink() or child.name.startswith(".") or
                (private_state is not None and child.resolve() == private_state.resolve())):
                continue
            entries.append({"name": child.name[:256], "type": "directory" if child.is_dir() else "file"})
        return json.dumps({"path": str(folder.relative_to(root.resolve())), "entries": entries}, ensure_ascii=False)
    if call.name == "file_read":
        if set(args) - {"path", "machine"} or "path" not in args:
            raise ValueError("Exactly one file path is required")
        path = safe_path(args["path"])
        if not path.is_file() or path.is_symlink():
            raise ValueError("Expected a regular file")
        with path.open("rb") as source:
            data = source.read(8193)
        if b"\x00" in data:
            raise ValueError("Binary files cannot be read as text")
        return json.dumps({
            "path": str(path.relative_to(root.resolve())),
            "text": data[:8192].decode("utf-8", errors="replace"),
            "truncated": len(data) > 8192,
        }, ensure_ascii=False)
    if call.name == "file_write":
        if set(args) - {"path", "content", "overwrite", "machine"} or not {"path", "content"} <= set(args):
            raise ValueError("A file path and content are required")
        text = args["content"]
        overwrite = args.get("overwrite", False)
        if not isinstance(text, str) or len(text.encode("utf-8")) > 16384 or type(overwrite) is not bool:
            raise ValueError("Invalid file contents or overwrite flag")
        raw = args["path"]
        if not isinstance(raw, str) or not raw or len(raw) > 2048:
            raise ValueError("Invalid file path")
        if Path(raw).is_absolute() or any(part.startswith(".") for part in Path(raw).parts):
            raise PermissionError("File must be workspace-relative and non-hidden")
        folder = _path(root, str(Path(raw).parent))
        target = (folder / Path(raw).name).resolve(strict=False)
        if not target.is_relative_to(root.resolve()) or target.name.startswith("."):
            raise PermissionError("Unsafe file write target")
        if private_state is not None and target.is_relative_to(private_state.resolve()):
            raise PermissionError("Controller private state is not available to models")
        from ..fs_ops import write_text

        output = write_text(str(target.relative_to(root.resolve())), text, overwrite=overwrite)
        return json.dumps({"path": str(target.relative_to(root.resolve())),
                           "bytes": output.get("bytes"), "created": output.get("created")})
    raise ValueError("Tool is not available without human approval")


async def run_machine_tool(
    owner: str, conversation_id: str, call: ModelToolCall, *,
    granted_scopes: set[str] | None = None, grant_expires: int | None = None,
) -> str:
    """Recheck inherited policy, OAuth scopes and expiration before execution."""
    from ..settings import get_settings
    from .machine_permissions import access_level, require_machine_scope

    settings = get_settings()
    machine = call.arguments.get("machine", "local")
    if not isinstance(machine, str) or not machine:
        raise ValueError("Invalid tool machine")
    level = access_level(owner, conversation_id, machine, repo=_repo())
    if level not in {"read", "write"}:
        raise PermissionError("File access is not granted for this machine")
    if machine == "local" and settings.disable_local:
        raise PermissionError("Local machine access is disabled")
    if machine != "local" and not settings.remote_enabled:
        raise PermissionError("Remote machine access is disabled")
    scopes = granted_scopes if granted_scopes is not None else (
        {"shell:read", "shell:write", "remote:use"} if settings.auth_mode == "none" else set()
    )
    require_machine_scope(scopes, machine, "read", expires=grant_expires)
    if call.name not in {"file_list", "file_read", "file_write"}:
        raise PermissionError("The requested tool is not approved")
    if call.name == "file_write":
        if level != "write":
            raise PermissionError("This machine has only read permission")
        require_machine_scope(scopes, machine, "write", expires=grant_expires)
    try:
        if machine == "local":
            result = await asyncio.to_thread(_execute, settings.workspace_root, call, settings.state_dir)
        else:
            result = await _remote_read(machine, call)
    except Exception as exc:
        audit("agent_native_tool", owner=owner, conversation_id=conversation_id,
              machine=machine, tool=call.name, argument_keys=sorted(call.arguments), ok=False,
              error_type=type(exc).__name__)
        raise
    audit("agent_native_tool", owner=owner, conversation_id=conversation_id,
          machine=machine, tool=call.name, argument_keys=sorted(call.arguments), ok=True)
    return result


def _remote_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Invalid remote path")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or any(part in {".."} or part.startswith(".") and part != "."
                                         for part in normalized.split("/")) or ":" in normalized:
        raise PermissionError("Remote tool paths must be workspace-relative and cannot contain hidden files")
    return normalized


async def _remote_read(machine: str, call: ModelToolCall) -> str:
    from ..human_ui import _remote_call

    path = _remote_path(call.arguments.get("path", "."))
    if call.name == "file_list":
        limit = call.arguments.get("limit", 25)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid directory entry limit")
        entries = await _remote_call(machine, "list_files", {"path": path, "recursive": False,
                                                              "max_entries": limit})
        if not isinstance(entries, list):
            raise ValueError("Remote worker returned invalid listing")
        return json.dumps({"path": path, "entries": [
            {"name": str(row.get("name", ""))[:256], "type": str(row.get("type", "file"))[:16]}
            for row in entries[:limit] if isinstance(row, dict)
            and not str(row.get("name", "")).startswith(".")
        ]}, ensure_ascii=False)
    if call.name == "file_read":
        reply = await _remote_call(machine, "read_file", {"path": path, "start_line": 1,
                                                           "end_line": 120})
        if not isinstance(reply, dict) or reply.get("binary"):
            raise ValueError("Remote worker returned non-text data")
        content = str(reply.get("content", ""))
        return json.dumps({"path": path, "text": content[:8192], "truncated": len(content) > 8192
                           or bool(reply.get("truncated"))}, ensure_ascii=False)
    if call.name == "file_write":
        if set(call.arguments) - {"path", "content", "overwrite", "machine"} or "content" not in call.arguments:
            raise ValueError("Invalid remote write arguments")
        content = call.arguments["content"]
        overwrite = call.arguments.get("overwrite", False)
        if not isinstance(content, str) or len(content.encode("utf-8")) > 16384 or type(overwrite) is not bool:
            raise ValueError("Invalid remote file contents")
        result = await _remote_call(machine, "write_file", {"path": path, "content": content,
                                                            "overwrite": overwrite, "encoding": "utf-8"})
        if not isinstance(result, dict):
            raise ValueError("Remote worker returned invalid write result")
        return json.dumps({"path": path, "bytes": result.get("bytes"), "created": result.get("created")})
    raise ValueError("Unknown machine file tool")
