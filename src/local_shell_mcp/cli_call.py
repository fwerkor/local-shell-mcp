from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .ui_security import (
    CLI_LOCAL_TOKEN_ENV,
    CLI_LOCAL_TOKEN_HEADER,
)

CLI_TOKEN_FILE_ENV = "LOCAL_SHELL_MCP_CLI_TOKEN_FILE"
CLI_DOTENV = ".env"
CLI_YAML_ENV_FIELDS = {
    "host": "LOCAL_SHELL_MCP_HOST",
    "port": "LOCAL_SHELL_MCP_PORT",
    "max_timeout_s": "LOCAL_SHELL_MCP_MAX_TIMEOUT_S",
    "auth_mode": "LOCAL_SHELL_MCP_AUTH_MODE",
    "workspace_root": "LOCAL_SHELL_MCP_WORKSPACE_ROOT",
    "state_dir": "LOCAL_SHELL_MCP_STATE_DIR",
}


@dataclass(frozen=True)
class _ControllerDefaults:
    host: str = "0.0.0.0"
    port: int = 8765
    max_timeout_s: float = 3600.0
    auth_mode: str = "oauth"


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


def _read_dotenv(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _parse_dotenv_value(value)
        values[key] = value
    return values


def _parse_dotenv_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        escaped = False
        chars: list[str] = []
        for char in value[1:]:
            if quote == '"' and escaped:
                escapes = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
                replacement = escapes.get(char)
                if replacement is None:
                    chars.extend(("\\", char))
                else:
                    chars.append(replacement)
                escaped = False
                continue
            if quote == '"' and char == "\\":
                escaped = True
                continue
            if char == quote:
                return "".join(chars)
            chars.append(char)
        return "".join(chars)
    for index, char in enumerate(value):
        if char == "#" and index > 0 and value[index - 1].isspace():
            return value[:index].rstrip()
    return value


def _cli_environment() -> dict[str, str]:
    values = _read_dotenv(Path.cwd() / CLI_DOTENV)
    for key, value in os.environ.items():
        if key.startswith("LOCAL_SHELL_MCP_"):
            values[key] = value
    return values


def _apply_yaml_controller_values(values: dict[str, str]) -> dict[str, str]:
    config = values.get("LOCAL_SHELL_MCP_CONFIG", "").strip()
    if not config:
        return dict(values)

    from .settings import _flatten_yaml

    path = Path(config).expanduser()
    try:
        flat = _flatten_yaml(path)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"unable to load LOCAL_SHELL_MCP_CONFIG {path}: {exc}") from exc

    merged: dict[str, str] = {}
    for field, env_name in CLI_YAML_ENV_FIELDS.items():
        if field in flat and flat[field] is not None:
            merged[env_name] = str(flat[field])
    merged.update(values)

    if "LOCAL_SHELL_MCP_STATE_DIR" not in values and "state_dir" not in flat:
        workspace = merged.get("LOCAL_SHELL_MCP_WORKSPACE_ROOT", "").strip()
        if workspace:
            merged["LOCAL_SHELL_MCP_STATE_DIR"] = str(
                Path(workspace).expanduser() / ".local-shell-mcp"
            )
    return merged


def _controller_endpoint_defaults(values: dict[str, str]) -> tuple[str, int]:
    host = values.get("LOCAL_SHELL_MCP_HOST", "0.0.0.0").strip() or "0.0.0.0"
    try:
        port = int(values.get("LOCAL_SHELL_MCP_PORT", "8765"))
    except ValueError as exc:
        raise ValueError("LOCAL_SHELL_MCP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("LOCAL_SHELL_MCP_PORT must be between 1 and 65535")
    return host, port


def _controller_max_timeout(values: dict[str, str]) -> float:
    try:
        max_timeout_s = float(values.get("LOCAL_SHELL_MCP_MAX_TIMEOUT_S", "3600"))
    except ValueError as exc:
        raise ValueError("LOCAL_SHELL_MCP_MAX_TIMEOUT_S must be a number") from exc
    if max_timeout_s <= 0:
        raise ValueError("LOCAL_SHELL_MCP_MAX_TIMEOUT_S must be greater than zero")
    return max_timeout_s


def _controller_defaults(values: dict[str, str]) -> _ControllerDefaults:
    host, port = _controller_endpoint_defaults(values)
    max_timeout_s = _controller_max_timeout(values)
    auth_mode = values.get("LOCAL_SHELL_MCP_AUTH_MODE", "oauth").strip().lower() or "oauth"
    return _ControllerDefaults(
        host=host,
        port=port,
        max_timeout_s=max_timeout_s,
        auth_mode=auth_mode,
    )


def _default_controller_url(settings: _ControllerDefaults) -> str:
    host = str(settings.host or "").strip()
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


def _resolve_local_token(values: dict[str, str], token_file: str | None) -> str | None:
    configured_file = token_file or values.get(CLI_TOKEN_FILE_ENV, "").strip() or None
    if configured_file:
        return _read_token_file(Path(configured_file))

    token = values.get(CLI_LOCAL_TOKEN_ENV, "").strip()
    if token:
        if len(token) < 32:
            raise ValueError(f"{CLI_LOCAL_TOKEN_ENV} must contain at least 32 characters")
        return token

    return None


@contextmanager
def _direct_environment(values: dict[str, str]) -> Iterator[None]:
    """Temporarily apply CLI dotenv settings for one direct-mode tool call."""

    from . import settings as settings_module

    # Keep the host-only CLI bearer outside the direct tool process environment.
    excluded = {CLI_LOCAL_TOKEN_ENV, CLI_TOKEN_FILE_ENV}
    updates = {
        key: value
        for key, value in values.items()
        if key.startswith("LOCAL_SHELL_MCP_") and key not in excluded
    }
    previous = {key: os.environ.get(key) for key in updates}
    sensitive_previous = {key: os.environ.get(key) for key in excluded}
    try:
        for key in excluded:
            os.environ.pop(key, None)
        os.environ.update(updates)
        settings_module.get_settings.cache_clear()
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in sensitive_previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        settings_module.get_settings.cache_clear()


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
    local_token: str | None,
    sse_read_timeout: float,
) -> tuple[Any, bool]:
    headers = (
        {CLI_LOCAL_TOKEN_HEADER: local_token}
        if local_token
        else None
    )
    async with streamablehttp_client(
        url,
        headers=headers,
        sse_read_timeout=sse_read_timeout,
        httpx_client_factory=_loopback_http_client_factory,
    ) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
    return _normalize_mcp_result(result)


async def _call_direct(
    tool: str,
    arguments: dict[str, Any],
    *,
    environment: dict[str, str] | None = None,
) -> tuple[Any, bool]:
    from .auth import _CURRENT_PRINCIPAL, Principal
    from .tools import build_mcp

    with _direct_environment(environment or {}):
        principal_token = _CURRENT_PRINCIPAL.set(
            Principal(email=None, subject="native-tui", claims={"auth": "native-tui"})
        )
        try:
            result = await build_mcp().call_tool(tool, arguments)
        finally:
            _CURRENT_PRINCIPAL.reset(principal_token)
    return _normalize_direct_result(result)


def _loopback_http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
        trust_env=False,
    )


def run_call_cli(argv: list[str] | None = None) -> None:
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
        default=None,
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
        default=None,
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
            payload, failed = asyncio.run(
                _call_direct(
                    args.tool,
                    arguments,
                    environment=_cli_environment(),
                )
            )
        else:
            try:
                raw_values = _cli_environment()
                values = (
                    _apply_yaml_controller_values(raw_values)
                    if args.url is None or args.read_timeout is None
                    else raw_values
                )
                if args.url is None:
                    host, port = _controller_endpoint_defaults(values)
                    url = _validate_loopback_mcp_url(
                        _default_controller_url(_ControllerDefaults(host=host, port=port))
                    )
                else:
                    url = _validate_loopback_mcp_url(args.url)
                local_token = _resolve_local_token(raw_values, args.token_file)
            except ValueError as exc:
                parser.error(str(exc))
            read_timeout = (
                args.read_timeout
                if args.read_timeout is not None
                else max(300.0, _controller_max_timeout(values) + 60.0)
            )
            if read_timeout <= 0:
                parser.error("--read-timeout must be greater than zero")
            payload, failed = asyncio.run(
                _call_controller(
                    url,
                    args.tool,
                    arguments,
                    local_token=local_token,
                    sse_read_timeout=read_timeout,
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
