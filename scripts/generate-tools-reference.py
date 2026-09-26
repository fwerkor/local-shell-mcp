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
    ("Interactive workspace", ("workspace_open",)),
    (
        "Environment, skills, and task state",
        (
            "environment_get",
            "skill_list",
            "skill_load",
            "skill_read",
            "secret_scan",
            "session_manage",
            "plan_manage",
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
        "Dynamic MCP gateway",
        (
            "mcp_manage",
            "mcp_tool_search",
            "mcp_tool_inspect",
            "mcp_tool_call",
        ),
    ),
    (
        "Browser automation",
        (
            "browser_session",
            "browser_snapshot",
            "browser_act",
            "browser_run_script",
        ),
    ),
    (
        "Desktop GUI automation",
        (
            "gui_list",
            "gui_state",
            "gui_action",
        ),
    ),
    ("Remote worker administration", ("remote_manage",)),
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
    tools = {
        tool.name: tool
        for tool in await build_mcp().list_tools()
        if "model" in ((tool.meta or {}).get("ui", {}).get("visibility") or ["model", "app"])
    }
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
        "Most tools return a structured `ToolResult` containing `ok`, `message`, and `data`. `workspace_open` returns the model-visible state used to render the MCP App. Most execution and file tools accept an optional `machine`; omit it for the controller workspace and provide it for a connected worker. Git operations intentionally use `run_shell` or another shell tool rather than dedicated Git wrappers.",
        "",
        "## Selection guide",
        "",
        "| Need | Preferred tools |",
        "|---|---|",
        "| Monitor or collaborate with execution in ChatGPT | `workspace_open` |",
        "| Inspect an environment | `environment_get`, `file_tree`, `file_read` |",
        "| Run a short command or Git operation | `run_shell` |",
        "| Run an interactive or long task | `shell_start` or `job_start` |",
        "| Make exact file changes | `file_edit` or `file_patch` |",
        "| Transfer a file or directory | `remote_transfer` |",
        "| Discover an external MCP capability | `mcp_tool_search`, then `mcp_tool_inspect` |",
        "| Interact with a page | `browser_session`, `browser_snapshot`, then `browser_act` |",
        "| Run custom browser logic | `browser_run_script` |",
        "| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |",
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
