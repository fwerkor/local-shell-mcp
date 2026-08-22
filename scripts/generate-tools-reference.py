#!/usr/bin/env python3
"""Generate docs/reference/tools.md from the live MCP tool schema."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "docs" / "reference" / "tools.md"

GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Environment, skills, and task state",
        (
            "environment_get",
            "skill_list",
            "skill_load",
            "skill_read",
            "secret_scan",
            "todo_read_tool",
            "todo_write_tool",
            "audit_tail",
        ),
    ),
    (
        "Shells and jobs",
        (
            "run_shell",
            "run_python",
            "shell_start",
            "shell_send",
            "shell_read",
            "shell_stop",
            "shell_list",
            "job_start",
            "job_list",
            "job_tail",
            "job_stop",
            "job_retry",
        ),
    ),
    (
        "Files and transfer",
        (
            "file_list",
            "file_tree",
            "file_glob",
            "file_grep",
            "file_read",
            "image_view",
            "file_write",
            "file_edit",
            "file_delete",
            "file_patch",
            "remote_transfer",
            "link_create",
            "link_list",
            "link_revoke",
        ),
    ),
    (
        "Browser automation",
        (
            "browser_capture_tool",
            "browser_get_text_tool",
            "browser_run_script",
        ),
    ),
    (
        "Remote worker administration",
        (
            "remote_manage",
        ),
    ),
)


def _type_name(schema: dict[str, Any]) -> str:
    if "anyOf" in schema:
        return " | ".join(_type_name(item) for item in schema["anyOf"])
    if "oneOf" in schema:
        return " | ".join(_type_name(item) for item in schema["oneOf"])
    kind = schema.get("type")
    if kind == "array":
        return f"array[{_type_name(schema.get('items', {}))}]"
    if kind == "object":
        return "object"
    if kind:
        return str(kind)
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    return "any"


def _default(schema: dict[str, Any], required: bool) -> str:
    if required:
        return "required"
    if "default" in schema:
        return f"`{json.dumps(schema['default'], ensure_ascii=False)}`"
    return "optional"


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


async def generate() -> str:
    get_settings.cache_clear()
    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    expected = {name for _title, names in GROUPS for name in names}
    if set(tools) != expected:
        missing = sorted(expected - set(tools))
        extra = sorted(set(tools) - expected)
        raise RuntimeError(f"Tool groups are stale; missing={missing}, extra={extra}")

    lines = [
        "# Tools reference",
        "",
        "This page is generated from the actual MCP tool schemas. Run `python scripts/generate-tools-reference.py` after changing the public tool surface.",
        "",
        "All tools return a structured `ToolResult` containing `ok`, `message`, and `data`. Most execution and file tools accept an optional `machine`; omit it for the controller workspace and provide it for a connected worker. Git operations intentionally use `run_shell` or another shell tool rather than dedicated Git wrappers.",
        "",
        "## Selection guide",
        "",
        "| Need | Preferred tools |",
        "|---|---|",
        "| Inspect an environment | `environment_get`, `file_tree`, `file_read` |",
        "| Run a short command or Git operation | `run_shell` |",
        "| Run an interactive or long task | `shell_start` or `job_start` |",
        "| Make exact file changes | `file_edit` or `file_patch` |",
        "| Transfer a file or directory | `remote_transfer` |",
        "| Capture a page | `browser_get_text_tool` or `browser_capture_tool` |",
        "| Work on a remote machine | use the same tool with `machine`; use `remote_*` only for worker administration |",
        "",
    ]

    for title, names in GROUPS:
        lines.extend([f"## {title}", ""])
        for name in names:
            tool = tools[name]
            schema = tool.inputSchema or {}
            properties = schema.get("properties", {})
            required = set(schema.get("required", []))
            lines.extend([f"### `{name}`", "", tool.description or "", ""])
            if properties:
                lines.extend(
                    [
                        "| Parameter | Type | Required/default | Description |",
                        "|---|---|---|---|",
                    ]
                )
                for parameter, spec in properties.items():
                    lines.append(
                        "| `{}` | `{}` | {} | {} |".format(
                            _escape(parameter),
                            _escape(_type_name(spec)),
                            _default(spec, parameter in required),
                            _escape(spec.get("description", "")),
                        )
                    )
                lines.append("")
            scopes = []
            for scheme in (tool.meta or {}).get("securitySchemes", []):
                if scheme.get("type") == "oauth2":
                    scopes = list(scheme.get("scopes", []))
                    break
            if scopes:
                lines.extend([f"OAuth scopes: `{', '.join(scopes)}`.", ""])
            if "machine" in properties:
                lines.extend(
                    [
                        "When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.",
                        "",
                    ]
                )
            if name == "remote_transfer":
                lines.extend(
                    [
                        "At least one of `source_machine` and `destination_machine` must be supplied. Omitted endpoints refer to the controller workspace; the source may be either a file or a directory.",
                        "",
                    ]
                )
    return "\n".join(lines).rstrip() + "\n"


async def main() -> None:
    OUTPUT.write_text(await generate(), encoding="utf-8")
    print(f"Generated {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    asyncio.run(main())
