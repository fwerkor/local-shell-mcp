from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shlex
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .fs_ops import resolve_path
from .settings import get_settings
from .shell_ops import check_command_policy
from .state_store import get_state_store

_REGISTRY_VERSION = 1
_MAX_TOOLS_PER_SERVER = 512
_MAX_TOOL_DESCRIPTOR_BYTES = 256 * 1024
_MAX_TOOL_CACHE_BYTES_PER_SERVER = 4 * 1024 * 1024
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SENSITIVE_CONFIG_KEY_RE = re.compile(
    r"(?:^|[_-])(?:auth(?:orization)?|api[_-]?key|access[_-]?key|credential|cookie|"
    r"password|passwd|private[_-]?key|secret|session|token)(?:$|[_-])|"
    r"(?:password|passwd)$|(?:^|[_-])pat$|"
    r"(?:^|[_-])(?:connection[_-]?string|dsn)(?:$|[_-])|"
    r"(?:^|[_-])(?:database|db|postgres(?:ql)?|mysql|mariadb|mongo(?:db)?|redis|amqp|rabbitmq)"
    r"[_-]?url(?:$|[_-])",
    re.IGNORECASE,
)
_MIN_SECRET_SUBSTRING_CHARS = 8
_INHERITED_ENV_KEYS = {
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SHELL",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USER",
    "USERNAME",
    "WINDIR",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _string_dict(value: dict[str, Any] | None, *, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in (value or {}).items():
        name = str(key).strip()
        if not name:
            raise ValueError(f"{label} keys must not be empty")
        if not isinstance(item, str):
            raise ValueError(f"{label} values must be strings")
        result[name] = item
    return result


def _tool_json(tool: Any) -> dict[str, Any]:
    if hasattr(tool, "model_dump"):
        return tool.model_dump(mode="json", by_alias=True, exclude_none=True)
    raise TypeError(f"unsupported MCP tool descriptor: {type(tool).__name__}")


def _config_key(server: DynamicMCPServer) -> tuple[Any, ...]:
    return (
        server.transport,
        server.command,
        tuple(server.args),
        server.cwd,
        server.url,
        tuple(sorted(server.env.items())),
        tuple(sorted(server.headers.items())),
    )


def _configured_secrets(server: DynamicMCPServer) -> list[str]:
    secrets: set[str] = set()
    for key, value in (*server.env.items(), *server.headers.items()):
        normalized_key = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_")
        if value and _SENSITIVE_CONFIG_KEY_RE.search(normalized_key):
            secrets.add(value)
    return sorted(secrets, key=len, reverse=True)


def _redact_config_secrets(message: str, server: DynamicMCPServer) -> str:
    redacted = message
    for secret in _configured_secrets(server):
        if redacted == secret:
            return "<redacted>"
        if len(secret) >= _MIN_SECRET_SUBSTRING_CHARS:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _is_protocol_content_path(path: tuple[str | int, ...]) -> bool:
    return len(path) == 2 and path[0] == "content" and isinstance(path[1], int)


def _is_protocol_result_key(path: tuple[str | int, ...], key: str) -> bool:
    return not path and key in {"content", "structuredContent", "isError", "_meta"}


def _is_protocol_type_path(path: tuple[str | int, ...]) -> bool:
    return (
        _is_protocol_content_path(path[:2])
        and len(path) == 3
        and path[2] == "type"
    )


def _redact_config_value(
    value: Any,
    server: DynamicMCPServer,
    *,
    path: tuple[str | int, ...] = (),
) -> Any:
    if isinstance(value, str):
        if _is_protocol_type_path(path):
            return value
        return _redact_config_secrets(value, server)
    if isinstance(value, list):
        return [
            _redact_config_value(item, server, path=(*path, index))
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for child_key, item in value.items():
            key = str(child_key)
            output_key = (
                key
                if _is_protocol_result_key(path, key) or _is_protocol_content_path(path)
                else _redact_config_secrets(key, server)
            )
            redacted[output_key] = _redact_config_value(
                item, server, path=(*path, key)
            )
        return redacted
    return value


def _serialized_json_bytes(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


@dataclass(slots=True)
class DynamicMCPServer:
    name: str
    transport: str
    enabled: bool = True
    command: str | None = None
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    refreshed_at: str | None = None
    updated_at: str = field(default_factory=_now_iso)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DynamicMCPServer:
        return cls(
            name=str(data["name"]),
            transport=str(data["transport"]),
            enabled=bool(data.get("enabled", True)),
            command=data.get("command"),
            args=[str(item) for item in data.get("args", [])],
            cwd=data.get("cwd"),
            url=data.get("url"),
            env=_string_dict(data.get("env"), label="env"),
            headers=_string_dict(data.get("headers"), label="headers"),
            tools=[dict(item) for item in data.get("tools", []) if isinstance(item, dict)],
            refreshed_at=data.get("refreshed_at"),
            updated_at=str(data.get("updated_at") or _now_iso()),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "command": self.command,
            "args": self.args,
            "cwd": self.cwd,
            "url": self.url,
            "env": self.env,
            "headers": self.headers,
            "tools": self.tools,
            "refreshed_at": self.refreshed_at,
            "updated_at": self.updated_at,
        }

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "command": self.command if self.transport == "stdio" else None,
            "args": list(self.args) if self.transport == "stdio" else [],
            "cwd": self.cwd if self.transport == "stdio" else None,
            "url": self.url if self.transport in {"streamable_http", "sse"} else None,
            "env_keys": sorted(self.env),
            "header_keys": sorted(self.headers),
            "tool_count": len(self.tools),
            "refreshed_at": self.refreshed_at,
            "updated_at": self.updated_at,
        }


class DynamicMCPManager:
    """Persistent registry and progressive-disclosure gateway for external MCP servers.

    Configurations and cached tool schemas are persisted. External stdio/HTTP connections are
    opened only for refresh and tool calls, so dynamic servers never expand this MCP server's
    own tools/list surface and do not require long-lived child processes.
    """

    def __init__(self, state_dir: Path, *, max_timeout_s: int = 3600) -> None:
        self._path = Path(state_dir) / "dynamic-mcp.json"
        self._max_timeout_s = max(1, int(max_timeout_s))
        self._lock = asyncio.Lock()

    def _load(self) -> dict[str, DynamicMCPServer]:
        try:
            if get_settings().state_backend == "file":
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            else:
                encoded = get_state_store().read_bytes("dynamic-mcp.json")
                if encoded is None:
                    return {}
                raw = json.loads(encoded.decode("utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read dynamic MCP registry: {exc}") from exc
        if raw.get("version") != _REGISTRY_VERSION:
            raise RuntimeError("unsupported dynamic MCP registry version")
        servers: dict[str, DynamicMCPServer] = {}
        for item in raw.get("servers", []):
            if not isinstance(item, dict):
                continue
            server = DynamicMCPServer.from_json(item)
            if server.transport == "stdio" and not server.cwd:
                server.cwd = str(resolve_path("."))
            servers[server.name] = server
        return servers

    def _save(self, servers: dict[str, DynamicMCPServer]) -> None:
        payload = json.dumps(
            {
                "version": _REGISTRY_VERSION,
                "servers": [servers[name].to_json() for name in sorted(servers)],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if get_settings().state_backend != "file":
            get_state_store().write_bytes("dynamic-mcp.json", (payload + "\n").encode("utf-8"))
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            with contextlib.suppress(OSError):
                temporary.chmod(0o600)
            os.replace(temporary, self._path)
            with contextlib.suppress(OSError):
                self._path.chmod(0o600)
        except Exception:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_config(server: DynamicMCPServer) -> None:
        if not _SERVER_NAME_RE.fullmatch(server.name):
            raise ValueError("name must match [A-Za-z0-9._-] and be at most 64 characters")
        if server.transport not in {"stdio", "streamable_http", "sse"}:
            raise ValueError("transport must be stdio, streamable_http or sse")
        if server.transport == "stdio":
            if not server.command or not server.command.strip():
                raise ValueError("command is required for stdio MCP servers")
            if server.url:
                raise ValueError("url is only valid for HTTP(S) MCP servers")
        else:
            if not server.url or not server.url.startswith(("http://", "https://")):
                raise ValueError("an absolute HTTP(S) url is required for network MCP servers")
            if server.command:
                raise ValueError("command is only valid for stdio MCP servers")

    @asynccontextmanager
    async def _session(self, server: DynamicMCPServer) -> AsyncIterator[ClientSession]:
        if server.transport == "stdio":
            env = {key: value for key, value in os.environ.items() if key.upper() in _INHERITED_ENV_KEYS}
            env.update(server.env)
            params = StdioServerParameters(
                command=server.command or "",
                args=list(server.args),
                cwd=server.cwd,
                env=env,
            )
            async with (
                stdio_client(params) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                yield session
            return

        if server.transport == "sse":
            # SSE client is an optional transport; import it only for servers
            # explicitly configured to use that protocol.
            from mcp.client.sse import sse_client

            async with sse_client(server.url or "", headers=dict(server.headers)) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
            return

        async with streamablehttp_client(server.url or "", headers=dict(server.headers)) as streams:
            read_stream, write_stream, _ = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    async def _fetch_tools(self, server: DynamicMCPServer) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cached_bytes = 0
        cursor: str | None = None
        async with asyncio.timeout(min(30, self._max_timeout_s)):
            async with self._session(server) as session:
                while True:
                    response = await session.list_tools(cursor=cursor)
                    for tool in response.tools:
                        if len(tools) >= _MAX_TOOLS_PER_SERVER:
                            raise ValueError(
                                f"dynamic MCP server exposes more than {_MAX_TOOLS_PER_SERVER} tools"
                            )
                        descriptor = _tool_json(tool)
                        descriptor_bytes = _serialized_json_bytes(descriptor)
                        if descriptor_bytes > _MAX_TOOL_DESCRIPTOR_BYTES:
                            raise ValueError(
                                "dynamic MCP tool descriptor exceeds "
                                f"{_MAX_TOOL_DESCRIPTOR_BYTES} bytes"
                            )
                        cached_bytes += descriptor_bytes
                        if cached_bytes > _MAX_TOOL_CACHE_BYTES_PER_SERVER:
                            raise ValueError(
                                "dynamic MCP tool cache exceeds "
                                f"{_MAX_TOOL_CACHE_BYTES_PER_SERVER} bytes per server"
                            )
                        tools.append(descriptor)
                    cursor = response.nextCursor
                    if not cursor:
                        break
        return tools

    async def manage(
        self,
        *,
        action: str,
        name: str | None = None,
        transport: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        cwd: str | None = None,
        url: str | None = None,
        env: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        enabled: bool = True,
        overwrite: bool = False,
        refresh: bool = True,
        key: str | None = None,
        value: str | None = None,
    ) -> dict[str, Any]:
        action = action.strip().lower()
        if action == "list":
            async with self._lock:
                servers = self._load()
            return {"servers": [servers[item].public() for item in sorted(servers)]}

        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")

        if action == "register":
            normalized_transport = (transport or "stdio").strip().lower()
            if normalized_transport == "stdio" and get_settings().disable_local:
                raise ValueError(
                    "stdio dynamic MCP servers are unavailable when local access is disabled; "
                    "use streamable_http"
                )
            normalized_args = [str(item) for item in (args or [])]
            normalized_command = command.strip() if command else None
            if normalized_transport == "stdio" and normalized_command:
                check_command_policy(shlex.join([normalized_command, *normalized_args]))
            server = DynamicMCPServer(
                name=clean_name,
                transport=normalized_transport,
                enabled=enabled,
                command=normalized_command,
                args=normalized_args,
                cwd=(
                    str(resolve_path(cwd.strip() if cwd else "."))
                    if normalized_transport == "stdio"
                    else None
                ),
                url=url.strip() if url else None,
                env=_string_dict(env, label="env"),
                headers=_string_dict(headers, label="headers"),
            )
            self._validate_config(server)
            async with self._lock:
                servers = self._load()
                if server.name in servers and not overwrite:
                    raise ValueError(f"dynamic MCP server already exists: {server.name}")
                servers[server.name] = server
                self._save(servers)
            if not refresh:
                return {"action": action, "server": server.public(), "refreshed": False}
            try:
                refreshed = await self.refresh(clean_name)
            except Exception as exc:
                return {
                    "action": action,
                    "server": server.public(),
                    "refreshed": False,
                    "refresh_error": _redact_config_secrets(
                        str(exc) or type(exc).__name__, server
                    ),
                }
            return {"action": action, **refreshed}

        if action == "refresh":
            return {"action": action, **(await self.refresh(clean_name))}

        async with self._lock:
            servers = self._load()
            server = servers.get(clean_name)
            if server is None:
                raise ValueError(f"unknown dynamic MCP server: {clean_name}")

            if action == "get":
                return {"action": action, "server": server.public()}
            if action == "update":
                updated = DynamicMCPServer.from_json(server.to_json())
                if transport is not None:
                    updated.transport = transport.strip().lower()
                if updated.transport == "stdio":
                    if get_settings().disable_local:
                        raise ValueError("stdio dynamic MCP servers are disabled")
                    if command is not None:
                        updated.command = command.strip()
                    if args is not None:
                        updated.args = [str(item) for item in args]
                    if cwd is not None:
                        updated.cwd = str(resolve_path(cwd.strip() or "."))
                    updated.url = None
                    if updated.command:
                        check_command_policy(shlex.join([updated.command, *updated.args]))
                elif updated.transport == "streamable_http":
                    if url is not None:
                        updated.url = url.strip()
                    updated.command = None
                    updated.args = []
                    updated.cwd = None
                if env is not None:
                    updated.env = _string_dict(env, label="env")
                if headers is not None:
                    updated.headers = _string_dict(headers, label="headers")
                self._validate_config(updated)
                updated.tools = []
                updated.refreshed_at = None
                updated.updated_at = _now_iso()
                servers[clean_name] = updated
                self._save(servers)
                return {"action": action, "server": updated.public(), "refreshed": False}
            if action in {"enable", "disable"}:
                server.enabled = action == "enable"
            elif action == "remove":
                del servers[clean_name]
                self._save(servers)
                return {"action": action, "name": clean_name, "removed": True}
            elif action in {"env_set", "env_unset", "header_set", "header_unset"}:
                clean_key = (key or "").strip()
                if not clean_key:
                    raise ValueError("key is required")
                target = server.env if action.startswith("env_") else server.headers
                if action.endswith("_set"):
                    if value is None:
                        raise ValueError("value is required")
                    target[clean_key] = value
                else:
                    target.pop(clean_key, None)
                server.tools = []
                server.refreshed_at = None
            else:
                raise ValueError(
                    "action must be register, list, get, update, enable, disable, remove, refresh, "
                    "env_set, env_unset, header_set, or header_unset"
                )
            server.updated_at = _now_iso()
            self._save(servers)
            return {"action": action, "server": server.public()}

    async def refresh(self, name: str) -> dict[str, Any]:
        async with self._lock:
            servers = self._load()
            server = servers.get(name)
            if server is None:
                raise ValueError(f"unknown dynamic MCP server: {name}")
            config = DynamicMCPServer.from_json(server.to_json())
            config_key = _config_key(config)
        if config.transport == "stdio" and get_settings().disable_local:
            raise ValueError(
                "stdio dynamic MCP servers are unavailable when local access is disabled; "
                "use streamable_http"
            )
        tools = await self._fetch_tools(config)
        async with self._lock:
            servers = self._load()
            current = servers.get(name)
            if current is None:
                raise ValueError(f"dynamic MCP server was removed while refreshing: {name}")
            if _config_key(current) != config_key:
                raise RuntimeError(
                    f"dynamic MCP server configuration changed while refreshing: {name}"
                )
            current.tools = tools
            current.refreshed_at = _now_iso()
            current.updated_at = current.refreshed_at
            self._save(servers)
            return {"server": current.public(), "refreshed": True}

    async def search(
        self, query: str = "", *, server: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        tokens = [token for token in query.lower().split() if token]
        async with self._lock:
            servers = self._load()
        selected = [servers[server]] if server and server in servers else []
        if server and not selected:
            raise ValueError(f"unknown dynamic MCP server: {server}")
        if not server:
            selected = [item for item in servers.values() if item.enabled]

        matches: list[tuple[int, dict[str, Any]]] = []
        unrefreshed: list[str] = []
        for item in selected:
            if not item.enabled:
                continue
            if not item.tools:
                unrefreshed.append(item.name)
            for tool in item.tools:
                name = str(tool.get("name") or "")
                title = str(tool.get("title") or "")
                description = str(tool.get("description") or "")
                haystack = f"{item.name}:{name} {title} {description}".lower()
                if tokens and not all(token in haystack for token in tokens):
                    continue
                score = 0
                qualified = f"{item.name}:{name}".lower()
                for token in tokens:
                    if token in qualified:
                        score += 4
                    elif token in title.lower():
                        score += 2
                    else:
                        score += 1
                matches.append(
                    (
                        score,
                        {
                            "name": f"{item.name}:{name}",
                            "server": item.name,
                            "tool": name,
                            "title": title or None,
                            "description": description or None,
                        },
                    )
                )
        matches.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        return {
            "tools": [item for _, item in matches[:limit]],
            "count": min(len(matches), limit),
            "total_matches": len(matches),
            "unrefreshed_servers": sorted(unrefreshed),
        }

    async def inspect(self, qualified_name: str) -> dict[str, Any]:
        server_name, tool_name = self._split_qualified_name(qualified_name)
        async with self._lock:
            servers = self._load()
            server = servers.get(server_name)
        if server is None:
            raise ValueError(f"unknown dynamic MCP server: {server_name}")
        for tool in server.tools:
            if tool.get("name") == tool_name:
                return {"name": qualified_name, "server": server.public(), "tool": tool}
        raise ValueError(
            f"unknown cached tool {qualified_name}; refresh the server before inspecting it"
        )

    async def call(
        self,
        qualified_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        server_name, tool_name = self._split_qualified_name(qualified_name)
        async with self._lock:
            servers = self._load()
            server = servers.get(server_name)
            if server is None:
                raise ValueError(f"unknown dynamic MCP server: {server_name}")
            config = DynamicMCPServer.from_json(server.to_json())
        if not config.enabled:
            raise ValueError(f"dynamic MCP server is disabled: {server_name}")
        if config.transport == "stdio" and get_settings().disable_local:
            raise ValueError(
                "stdio dynamic MCP servers are unavailable when local access is disabled; "
                "use streamable_http"
            )
        if not any(tool.get("name") == tool_name for tool in config.tools):
            raise ValueError(
                f"unknown cached tool {qualified_name}; refresh the server before calling it"
            )
        requested_timeout = 60 if timeout_s is None else int(timeout_s)
        bounded_timeout = max(1, min(requested_timeout, self._max_timeout_s))
        async with asyncio.timeout(bounded_timeout):
            async with self._session(config) as session:
                result = await session.call_tool(tool_name, arguments or {})
        result_payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        return {
            "name": qualified_name,
            "result": _redact_config_value(result_payload, config),
        }

    @staticmethod
    def _split_qualified_name(value: str) -> tuple[str, str]:
        server_name, separator, tool_name = value.strip().partition(":")
        if not separator or not server_name or not tool_name:
            raise ValueError("dynamic MCP tool names must use <server>:<tool>")
        return server_name, tool_name
