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
    ("Connector and discovery", ("search", "fetch")),
    (
        "Environment, skills, and task state",
        (
            "environment_info",
            "skills_list",
            "skill_load",
            "skill_read_file",
            "secret_scan",
            "todo_read_tool",
            "todo_write_tool",
            "audit_tail",
        ),
    ),
    (
        "Shells and jobs",
        (
            "run_shell_tool",
            "run_python_tool",
            "shell_start",
            "shell_send",
            "shell_read",
            "shell_kill",
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
            "list_files",
            "tree_view",
            "glob_search",
            "grep_search",
            "read_file",
            "view_image",
            "write_file",
            "edit_file",
            "delete_file_or_dir",
            "apply_patch",
            "transfer_path",
            "create_file_link",
            "list_file_links",
            "revoke_file_link",
        ),
    ),
    (
        "Browser automation",
        (
            "browser_capture_tool",
            "browser_get_text_tool",
            "playwright_run_script_tool",
        ),
    ),
    (
        "Remote worker administration",
        (
            "remote_invite",
            "remote_list_machines",
            "remote_revoke_machine",
            "remote_rename_machine",
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
        "All tools except connector-style `search` and `fetch` return a structured `ToolResult` containing `ok`, `message`, and `data`. Most execution and file tools accept an optional `machine`; omit it for the controller workspace and provide it for a connected worker. Git operations intentionally use `run_shell_tool` or another shell tool rather than dedicated Git wrappers.",
        "",
        "## Selection guide",
        "",
        "| Need | Preferred tools |",
        "|---|---|",
        "| Inspect an environment | `environment_info`, `tree_view`, `read_file` |",
        "| Run a short command or Git operation | `run_shell_tool` |",
        "| Run an interactive or long task | `shell_start` or `job_start` |",
        "| Make exact file changes | `edit_file` or `apply_patch` |",
        "| Transfer a file or directory | `transfer_path` |",
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
            if name == "transfer_path":
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
