#!/usr/bin/env python3
"""Render deployment-only LibreChat MCP settings without committing credentials."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def _internal_origin(value: str, *, allowed_hosts: set[str]) -> tuple[str, str]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Internal service URL must be an HTTP origin on an approved private host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid internal service port") from exc
    if not port:
        raise ValueError("Internal service URL must include a port")
    return f"http://{parsed.hostname}:{port}", f"{parsed.hostname}:{port}"


def render(source: Path, destination: Path, environment: Mapping[str, str]) -> None:
    secret = environment.get("LSM_LIBRECHAT_BRIDGE_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("LSM_LIBRECHAT_BRIDGE_SECRET requires at least 32 bytes")
    controller, host_port = _internal_origin(
        environment.get("LSM_CONTROLLER_INTERNAL_URL", "http://local-shell-mcp:8765"),
        allowed_hosts={"local-shell-mcp", "host.docker.internal"},
    )
    search, _ = _internal_origin(
        environment.get("SEARXNG_INSTANCE_URL", "http://searxng:8080"),
        allowed_hosts={"searxng"},
    )
    values = {
        'url: "${LSM_CONTROLLER_INTERNAL_URL}/mcp"': f"url: {json.dumps(controller + '/mcp')}",
        'Authorization: "Bearer ${LSM_LIBRECHAT_BRIDGE_SECRET}"': (
            f"Authorization: {json.dumps('Bearer ' + secret)}"
        ),
        '- "local-shell-mcp:8765"': f"- {json.dumps(host_port)}",
        'searxngInstanceUrl: "${SEARXNG_INSTANCE_URL}"': (
            f"searxngInstanceUrl: {json.dumps(search)}"
        ),
    }
    result = source.read_text(encoding="utf-8")
    for placeholder, replacement in values.items():
        if result.count(placeholder) != 1:
            raise ValueError(f"Unexpected LibreChat configuration template: {placeholder.split(':')[0]}")
        result = result.replace(placeholder, replacement)
    if "${" in result:
        raise ValueError("Unresolved environment placeholder in LibreChat configuration")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".librechat.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(result)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render protected LibreChat runtime YAML")
    parser.add_argument("--source", type=Path, default=ROOT / "librechat.yaml")
    parser.add_argument("--output", type=Path, default=ROOT / "librechat.runtime.yaml")
    args = parser.parse_args()
    render(args.source, args.output, os.environ)
    print(f"Rendered private LibreChat configuration: {args.output}")


if __name__ == "__main__":
    main()
