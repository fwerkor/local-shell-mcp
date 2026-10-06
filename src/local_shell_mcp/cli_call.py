from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .settings import get_settings
from .ui_security import UI_LOCAL_TOKEN_ENV, UI_LOCAL_TOKEN_HEADER, get_ui_local_token

CLI_TOKEN_FILE_ENV = "LOCAL_SHELL_MCP_CLI_TOKEN_FILE"


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if raw is None:
        if sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    if not raw or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON arguments: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")
    return value


def _validate_loopback_mcp_url(value: str) -> str:
    normalized = str(value).rstrip("/")
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    loopback = host.lower() == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
        except ValueError:
            loopback = False
    if parsed.scheme not in {"http", "https"} or not loopback:
        raise ValueError("--url must use a loopback HTTP(S) URL")
    if parsed.path not in {"", "/mcp"}:
        raise ValueError("--url must point to the local MCP endpoint (/mcp)")
    return normalized if parsed.path else normalized + "/mcp"


def _default_controller_url(settings: Any) -> str:
    host = str(getattr(settings, "host", "") or "").strip()
    candidate = host.strip("[]").split("%", 1)[0]
    is_loopback = host.lower() == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(candidate).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        host = "127.0.0.1"
    elif ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings.port}/mcp"


def _read_token_file(path: Path) -> str:
    try:
        value = path.expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"unable to read local credential file: {path}") from exc
    if len(value) < 32:
        raise ValueError(f"local credential file is invalid: {path}")
    return value


def _resolve_local_token(settings: Any, token_file: str | None) -> str:
    configured_file = token_file or os.getenv(CLI_TOKEN_FILE_ENV, "").strip() or None
    if configured_file:
        return _read_token_file(Path(configured_file))

    token = get_ui_local_token()
    if token:
        return token

    # The documented Docker Compose runtime bind-mounts ./workspaces/default to
    # /workspace, so the controller-created token is visible at this host path.
    compose_token = Path.cwd() / "workspaces" / "default" / ".local-shell-mcp" / "ui" / "local-token"
    if compose_token.is_file():
        return _read_token_file(compose_token)

    raise ValueError(
        "no controller local credential is available; use --token-file, set "
        f"{CLI_TOKEN_FILE_ENV}, or share {UI_LOCAL_TOKEN_ENV} with the controller"
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _tool_result_failed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is False:
        return True
    data = payload.get("data")
    return isinstance(data, dict) and data.get("ok") is False


def _normalize_direct_result(result: Any) -> tuple[Any, bool]:
    if isinstance(result, tuple) and len(result) == 2:
        content, structured = result
        payload = _jsonable(structured) if structured is not None else _jsonable(content)
    else:
        payload = _jsonable(result)
        if isinstance(payload, dict) and "structuredContent" in payload:
            payload = payload["structuredContent"]
    failed = _tool_result_failed(payload)
    return payload, failed


def _normalize_mcp_result(result: Any) -> tuple[Any, bool]:
    envelope = _jsonable(result)
    failed = bool(isinstance(envelope, dict) and envelope.get("isError") is True)
    payload = envelope
    if isinstance(envelope, dict) and envelope.get("structuredContent") is not None:
        payload = envelope["structuredContent"]
        if _tool_result_failed(payload):
            failed = True
    return payload, failed


async def _call_controller(
    url: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    local_token: str,
    sse_read_timeout: float,
) -> tuple[Any, bool]:
    headers = {UI_LOCAL_TOKEN_HEADER: local_token}
    async with streamablehttp_client(
        url,
        headers=headers,
        sse_read_timeout=sse_read_timeout,
    ) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
    return _normalize_mcp_result(result)


async def _call_direct(tool: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
    from .tools import build_mcp

    result = await build_mcp().call_tool(tool, arguments)
    return _normalize_direct_result(result)


def run_call_cli(argv: list[str] | None = None) -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="local-shell-mcp call",
        description="Invoke one local-shell-mcp tool from the command line.",
    )
    parser.add_argument("tool", help="Registered LSM tool name")
    parser.add_argument(
        "--json",
        dest="json_arguments",
        help="Tool arguments as a JSON object. If omitted, JSON is read from stdin; a TTY means {}.",
    )
    parser.add_argument(
        "--session",
        dest="logical_session_id",
        help="Set logical_session_id for ordinary tools.",
    )
    parser.add_argument(
        "--url",
        default=_default_controller_url(settings),
        help="Running local controller MCP URL (loopback only).",
    )
    parser.add_argument(
        "--token-file",
        help=(
            "Read the controller local credential from this file. Useful when the "
            "CLI and controller use different runtime filesystems, such as Docker Compose."
        ),
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=max(300.0, float(getattr(settings, "max_timeout_s", 3600)) + 60.0),
        help="Maximum quiet SSE read interval in seconds for controller calls.",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Invoke the tool in this process instead of the running controller. Remote workers are not available in direct mode.",
    )
    args = parser.parse_args(argv)

    try:
        arguments = _parse_arguments(args.json_arguments)
    except ValueError as exc:
        parser.error(str(exc))

    if args.logical_session_id is not None:
        arguments["logical_session_id"] = args.logical_session_id

    try:
        if args.direct:
            payload, failed = asyncio.run(_call_direct(args.tool, arguments))
        else:
            try:
                url = _validate_loopback_mcp_url(args.url)
                local_token = _resolve_local_token(settings, args.token_file)
            except ValueError as exc:
                parser.error(str(exc))
            if args.read_timeout <= 0:
                parser.error("--read-timeout must be greater than zero")
            payload, failed = asyncio.run(
                _call_controller(
                    url,
                    args.tool,
                    arguments,
                    local_token=local_token,
                    sse_read_timeout=args.read_timeout,
                )
            )
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"local-shell-mcp call failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    if failed:
        raise SystemExit(1)
