#!/usr/bin/env python3
"""Generate config.example.yaml and .env.example from the settings registry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from local_shell_mcp.config.registry import (
    SECTION_ORDER,
    SETTING_SPECS,
    SettingSpec,
    default_to_string,
    default_value,
    validate_setting_specs,
    yaml_default,
)

ROOT = Path(__file__).resolve().parents[1]

DOCKER_ENTRYPOINT_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "DOCKER_RUN_AS_ROOT",
        "false",
        "Run the Dockerized MCP server itself as root. Prefer explicit sudo inside commands instead.",
    ),
    (
        "DOCKER_PERSISTENT_CREDENTIALS",
        "true",
        "Persist GitHub CLI, Git HTTPS credentials, GitCode credentials, SSH keys, .netrc, and GPG state across container rebuilds.",
    ),
    (
        "DOCKER_CREDENTIALS_DIR",
        "/persist/credentials",
        "Root directory for persisted credentials. The Docker Compose example stores it in the local-shell-mcp-credentials volume.",
    ),
    (
        "DOCKER_CHOWN_WORKSPACE",
        "true",
        "chown the mounted workspace to the agent user before starting the server.",
    ),
)

SIDECAR_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "CLOUDFLARE_TUNNEL_TOKEN",
        "",
        "Optional token for the cloudflared tunnel sidecar profile. This uses Cloudflare Tunnel only, not Cloudflare Access.",
    ),
)


def _wrap_comment(text: str, *, width: int = 100) -> list[str]:
    """Wrap a comment into shell/YAML comment lines."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _env_line(name: str, value: Any) -> str:
    return f"{name}={default_to_string(value)}"


def generate_env_example() -> str:
    """Generate .env.example content."""
    validate_setting_specs()
    lines: list[str] = [
        "# Docker Compose uses this file as the main container environment via `env_file: .env`.",
        "# Copy it with: cp .env.example .env",
    ]
    specs_by_section: dict[str, list[SettingSpec]] = {
        section: [] for section in SECTION_ORDER
    }
    for spec in SETTING_SPECS:
        specs_by_section[spec.section].append(spec)

    for section in SECTION_ORDER:
        lines.extend(["", f"# {section}."])
        for spec in specs_by_section[section]:
            for comment in _wrap_comment(spec.help):
                lines.append(f"# {comment}")
            lines.append(_env_line(spec.env_var, default_value(spec.name)))

    lines.extend(
        [
            "",
            "# Docker entrypoint settings. These are read before local-shell-mcp starts.",
        ]
    )
    for name, default, help_text in DOCKER_ENTRYPOINT_SPECS:
        for comment in _wrap_comment(help_text):
            lines.append(f"# {comment}")
        lines.append(f"{name}={default}")

    lines.extend(["", "# Optional sidecar settings."])
    for name, default, help_text in SIDECAR_SPECS:
        for comment in _wrap_comment(help_text):
            lines.append(f"# {comment}")
        lines.append(f"{name}={default}")

    return "\n".join(lines) + "\n"


def _yaml_string(value: str) -> str:
    """Render a string as a quoted YAML scalar, preserving spaces exactly."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_scalar(value: Any) -> str:
    """Render a scalar/list default as simple YAML while preserving string details."""
    value = yaml_default(value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        rendered = "\n"
        for item in value:
            rendered += f"  - {_yaml_string(str(item))}\n"
        return rendered.rstrip()
    return _yaml_string(str(value))


def generate_yaml_example() -> str:
    """Generate config.example.yaml content."""
    validate_setting_specs()
    lines: list[str] = [
        "# Full YAML config example.",
        "# Effective precedence: defaults < config file < LOCAL_SHELL_MCP_* environment variables < CLI arguments.",
    ]
    specs_by_section = {section: [] for section in SECTION_ORDER}
    for spec in SETTING_SPECS:
        specs_by_section[spec.section].append(spec)

    for section in SECTION_ORDER:
        lines.extend(["", f"# {section}."])
        for spec in specs_by_section[section]:
            for comment in _wrap_comment(spec.help):
                lines.append(f"# {comment}")
            value = _yaml_scalar(default_value(spec.name))
            if "\n" in value:
                lines.append(f"{spec.name}:{value}")
            else:
                lines.append(f"{spec.name}: {value}")

    return "\n".join(lines) + "\n"


def write_examples(*, check: bool) -> int:
    """Write generated files or check they are up to date."""
    outputs = {
        ROOT / ".env.example": generate_env_example(),
        ROOT / "config.example.yaml": generate_yaml_example(),
    }
    stale: list[Path] = []
    for path, content in outputs.items():
        if check:
            if path.read_text() != content:
                stale.append(path)
        else:
            path.write_text(content)
    if stale:
        for path in stale:
            print(f"out of date: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated examples are stale",
    )
    args = parser.parse_args()
    return write_examples(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
