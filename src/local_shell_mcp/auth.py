from __future__ import annotations

import asyncio
import ipaddress
import json
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .audit import audit
from .settings import Settings, get_settings
from .ui_security import has_valid_ui_local_token, is_loopback_connection

PUBLIC_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json", "/join", "/remote/worker-bundle.tgz", "/remote/register", "/remote/resume", "/remote/poll", "/remote/heartbeat", "/remote/result"}
HUMAN_UI_API_PREFIX = "/api/ui/"
_REQUEST_BODY_SCOPE_KEY = "local_shell_mcp.request_body"
_REMOTE_TRANSFER_PREFIX = "/remote/transfer/"


def _is_public_path(path: str) -> bool:
    ui_path = "/" + get_settings().ui_path.strip("/")
    return (
        path in PUBLIC_PATHS
        or path.startswith(_REMOTE_TRANSFER_PREFIX)
        or path.startswith("/.well-known/")
        or path.startswith("/oauth/")
        or path.startswith("/download/")
        or path in {ui_path, ui_path + "/", ui_path + "/callback", ui_path + "/wallpaper"}
        or path.startswith(ui_path + "/assets/")
    )


MCP_DISCOVERY_METHODS = {
    "initialize",
    "notifications/initialized",
    "ping",
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "prompts/list",
}


@dataclass
class Principal:
    email: str | None
    subject: str | None
    claims: dict[str, Any]


_CURRENT_PRINCIPAL: ContextVar[Principal | None] = ContextVar(
    "local_shell_mcp_current_principal", default=None
)


def current_principal() -> Principal | None:
    return _CURRENT_PRINCIPAL.get()


def principal_scopes(principal: Principal) -> set[str]:
    raw = principal.claims.get("scope", "")
    if isinstance(raw, str):
        return {item for item in raw.split() if item}
    if isinstance(raw, (list, tuple, set)):
        return {str(item) for item in raw if str(item)}
    return set()


def require_scopes(
    principal: Principal, required: list[str] | tuple[str, ...] | set[str]
) -> None:
    required_set = {str(scope) for scope in required if str(scope)}
    if not required_set:
        return
    if principal.claims.get("auth") in {"none", "native-tui", "localhost-bypass"}:
        return
    missing = sorted(required_set - principal_scopes(principal))
    if not missing:
        return
    required_value = " ".join(sorted(required_set))
    raise HTTPException(
        status_code=403,
        detail=f"OAuth token is missing required scope(s): {', '.join(missing)}",
        headers={
            "WWW-Authenticate": (
                f'Bearer error="insufficient_scope", scope="{required_value}"'
            )
        },
    )


def require_current_scopes(required: list[str] | tuple[str, ...] | set[str]) -> None:
    """Enforce scopes for an authenticated HTTP MCP call.

    Stdio and direct in-process calls have no HTTP principal. auth_mode=none and the
    explicit localhost/native bypasses are intentionally unrestricted.
    """

    principal = current_principal()
    if principal is not None:
        require_scopes(principal, required)


def required_scopes_for_http_tool(path: str) -> tuple[str, ...]:
    """Map the compatibility REST tool surface to the scopes declared by MCP tools."""

    read = ("shell:read",)
    write = ("shell:read", "shell:write")
    execute = ("shell:read", "shell:execute")
    git_write = ("shell:read", "git:write")
    browser = ("browser:use",)
    browser_write = ("browser:use", "shell:write")
    browser_execute = ("browser:use", "shell:execute")
    file_share = ("shell:read", "file:share")

    if path.startswith("/tools/download/"):
        return file_share
    if path in {
        "/tools/write_file",
        "/tools/edit_file",
        "/tools/multi_edit_file",
        "/tools/delete",
        "/tools/todo",
    }:
        return write
    if path in {
        "/tools/run_shell",
        "/tools/shell_start",
        "/tools/shell_send",
        "/tools/shell_kill",
    }:
        return execute
    if path.startswith("/tools/git/"):
        if path in {
            "/tools/git/status",
            "/tools/git/diff",
            "/tools/git/log",
            "/tools/git/show",
        }:
            return read
        return git_write
    if path in {"/tools/browser/text", "/tools/browser/eval"}:
        return browser
    if path in {
        "/tools/browser/screenshot",
        "/tools/browser/pdf",
        "/tools/playwright/install",
    }:
        return browser_write
    if path == "/tools/playwright/run_script":
        return browser_execute
    if path.startswith("/tools/"):
        return read
    return ()


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _is_localhost(request: Request) -> bool:
    host = _client_host(request)
    return host in {"127.0.0.1", "::1", "localhost"}


def _host_header_is_loopback(request: Request) -> bool:
    value = request.headers.get("host", "").strip()
    if not value:
        return False
    if value.startswith("["):
        end = value.find("]")
        host = value[1:end] if end >= 0 else value.strip("[]")
    else:
        host = value.split(":", 1)[0]
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_direct_localhost_request(request: Request) -> bool:
    """Return whether an HTTP request came directly from a loopback client.

    Reverse proxies commonly connect to the service over loopback. Requiring a loopback
    Host header and rejecting forwarding metadata prevents that proxy hop from inheriting
    the local development bypass for a public client.
    """

    forwarded_headers = (
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-real-ip",
    )
    return (
        _is_localhost(request)
        and _host_header_is_loopback(request)
        and not any(request.headers.get(name) for name in forwarded_headers)
    )


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _verify_oauth(request: Request, settings: Settings) -> Principal:
    from .oauth import protected_resource_metadata, validate_bearer_token

    token = _extract_token(request)
    if not token:
        metadata_url = protected_resource_metadata(request)["resource"].rstrip("/") + "/.well-known/oauth-protected-resource"
        raise HTTPException(
            status_code=401,
            detail="Missing OAuth bearer token",
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}", scope="shell:execute"'},
        )
    try:
        claims = validate_bearer_token(token, request)
    except jwt.PyJWTError as exc:
        audit("oauth_auth_failed", error=str(exc), path=str(request.url.path), ip=_client_host(request))
        raise HTTPException(status_code=401, detail=f"Invalid OAuth bearer token: {exc}") from exc
    return Principal(email=None, subject=claims.get("sub"), claims=claims)


def verify_request(request: Request) -> Principal:
    settings = get_settings()
    path = str(request.url.path)
    if settings.auth_mode == "none":
        return Principal(email=None, subject="anonymous", claims={"auth": "none"})
    if (
        path.startswith(HUMAN_UI_API_PREFIX)
        and is_loopback_connection(request)
        and has_valid_ui_local_token(request)
    ):
        return Principal(email="localhost", subject="native-tui", claims={"auth": "native-tui"})
    if (
        settings.auth_bypass_localhost
        and settings.mode == "http"
        and _is_direct_localhost_request(request)
    ):
        return Principal(email="localhost", subject="localhost", claims={"auth": "localhost-bypass"})
    if settings.auth_mode == "oauth":
        principal = _verify_oauth(request, settings)
    else:
        raise HTTPException(status_code=500, detail=f"Unsupported auth_mode: {settings.auth_mode}")
    if not path.startswith(HUMAN_UI_API_PREFIX):
        audit("auth_ok", subject=principal.subject, path=path, ip=_client_host(request))
    return principal


class RequestBodyTooLarge(RuntimeError):
    pass


async def _read_body(receive: Receive, max_bytes: int | None = None) -> bytes:
    chunks = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise RequestBodyTooLarge(
                f"Request body exceeds the configured {max_bytes} byte limit"
            )
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _body_receive(body: bytes, original_receive: Receive) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return await original_receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _mcp_methods_from_body(body: bytes) -> set[str]:
    if not body:
        return set()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return set()

    messages = payload if isinstance(payload, list) else [payload]
    methods = set()
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("method"), str):
            methods.add(message["method"])
    return methods


def _is_mcp_discovery_request(scope: Scope, body: bytes | None) -> bool:
    if scope.get("path") != "/mcp":
        return False

    method = scope.get("method", "").upper()
    if method == "OPTIONS":
        return True
    if method != "POST" or body is None:
        return False

    methods = _mcp_methods_from_body(body)
    return bool(methods) and methods <= MCP_DISCOVERY_METHODS


class McpSessionLimitMiddleware:
    """Bound stateful Streamable HTTP sessions created by the MCP SDK."""

    def __init__(self, app: ASGIApp, session_manager: Any):
        self.app = app
        self.session_manager = session_manager
        self._creation_lock = asyncio.Lock()

    @staticmethod
    def _is_new_session(scope: Scope) -> bool:
        if scope.get("type") != "http":
            return False
        if scope.get("path") != "/mcp" or scope.get("method", "").upper() != "POST":
            return False
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        return b"mcp-session-id" not in headers

    def _active_session_count(self) -> int:
        instances = getattr(self.session_manager, "_server_instances", None)
        if not isinstance(instances, dict):
            return 0
        owners = getattr(self.session_manager, "_session_owners", None)
        for session_id, transport in list(instances.items()):
            if not bool(getattr(transport, "is_terminated", False)):
                continue
            instances.pop(session_id, None)
            if isinstance(owners, dict):
                owners.pop(session_id, None)
        return len(instances)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_new_session(scope):
            await self.app(scope, receive, send)
            return

        async with self._creation_lock:
            limit = max(1, get_settings().mcp_max_sessions)
            if self._active_session_count() >= limit:
                response = JSONResponse(
                    {
                        "ok": False,
                        "error": "mcp_session_limit",
                        "message": f"MCP session limit reached: {limit}",
                    },
                    status_code=429,
                )
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)


class AuthMiddleware:
    """ASGI middleware for OAuth bearer verification."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if _is_public_path(path):
            await self.app(scope, receive, send)
            return

        body = scope.get(_REQUEST_BODY_SCOPE_KEY)
        downstream_receive = receive
        if path == "/mcp" and scope.get("method", "").upper() == "POST":
            if body is None:
                try:
                    body = await _read_body(
                        receive, max(1, get_settings().max_http_request_bytes)
                    )
                except RequestBodyTooLarge as exc:
                    response = JSONResponse(
                        {
                            "ok": False,
                            "error": "request_too_large",
                            "message": str(exc),
                        },
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return
            downstream_receive = _body_receive(body, receive)

        settings = get_settings()
        if (
            settings.auth_mode == "oauth"
            and not settings.require_auth_for_mcp_discovery
            and _is_mcp_discovery_request(scope, body)
        ):
            await self.app(scope, downstream_receive, send)
            return

        try:
            request = Request(scope, downstream_receive)
            request.state.principal = verify_request(request)
        except HTTPException as exc:
            headers = getattr(exc, "headers", None) or {}
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)
            await response(scope, downstream_receive, send)
            return

        token = _CURRENT_PRINCIPAL.set(request.state.principal)
        try:
            await self.app(scope, downstream_receive, send)
        finally:
            _CURRENT_PRINCIPAL.reset(token)


class RequestBodyLimitMiddleware:
    """Bound HTTP request buffering before auth, routing, or JSON parsing."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "").upper() in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            await self.app(scope, receive, send)
            return

        if scope.get("path", "").startswith("/remote/transfer/upload/"):
            # Upload tickets validate an exact byte count and SHA-256 while streaming.
            # Buffering here would turn the transfer back into a memory-bound request.
            await self.app(scope, receive, send)
            return

        limit = max(1, get_settings().max_http_request_bytes)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_content_length = headers.get(b"content-length")
        if raw_content_length:
            try:
                content_length = int(raw_content_length)
            except ValueError:
                content_length = None
            if content_length is not None and content_length > limit:
                response = JSONResponse(
                    {
                        "ok": False,
                        "error": "request_too_large",
                        "message": (
                            f"Request body exceeds the configured {limit} byte limit"
                        ),
                    },
                    status_code=413,
                )
                await response(scope, receive, send)
                return

        try:
            body = await _read_body(receive, limit)
        except RequestBodyTooLarge as exc:
            response = JSONResponse(
                {
                    "ok": False,
                    "error": "request_too_large",
                    "message": str(exc),
                },
                status_code=413,
            )
            await response(scope, receive, send)
            return

        scope[_REQUEST_BODY_SCOPE_KEY] = body
        await self.app(scope, _body_receive(body, receive), send)


# Backwards-compatible alias.
CloudflareAccessMiddleware = AuthMiddleware
