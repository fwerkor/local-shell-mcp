"""Explicitly scoped, read-only functions for the first Python Agent tool loop.

Neither shell execution nor dynamic MCP management is exposed here. Write and
external-network tools require a durable human approval flow before enablement.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .providers import ModelToolCall
from .routes import _repo

READ_ONLY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lsm_file_list",
            "description": "List files in a directory within the local-shell-mcp workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 25},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lsm_file_read",
            "description": "Read a short UTF-8 excerpt from a text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path"},
                },
                "required": ["path"],
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

    if call.name == "lsm_file_list":
        if set(args) - {"path", "limit"}:
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
    if call.name == "lsm_file_read":
        if set(args) != {"path"}:
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
    raise ValueError("Tool is not available without human approval")


async def run_readonly_tool(owner: str, conversation_id: str, call: ModelToolCall) -> str:
    """Recheck owner-scoped policy immediately before every actual operation."""
    from ..audit import audit
    from ..settings import get_settings

    settings = get_settings()
    prefs = _repo().setting(owner, "conversation.permissions." + conversation_id, {})
    if settings.disable_local or not isinstance(prefs, dict) or not prefs.get("lsm") or not prefs.get("web"):
        raise PermissionError("LSM file tools are disabled for this conversation")
    if call.name not in {"lsm_file_list", "lsm_file_read"}:
        raise PermissionError("The requested tool requires explicit human approval")
    try:
        result = await asyncio.to_thread(_execute, settings.workspace_root, call, settings.state_dir)
    except Exception as exc:
        audit("agent_native_tool", owner=owner, conversation_id=conversation_id,
              tool=call.name, argument_keys=sorted(call.arguments), ok=False,
              error_type=type(exc).__name__)
        raise
    audit("agent_native_tool", owner=owner, conversation_id=conversation_id,
          tool=call.name, argument_keys=sorted(call.arguments), ok=True)
    return result
