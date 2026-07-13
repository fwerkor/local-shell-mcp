from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .audit import audit
from .settings import Settings, get_settings

PUBLIC_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json", "/join", "/remote/worker-bundle.tgz", "/remote/register", "/remote/resume", "/remote/poll", "/remote/result"}
HUMAN_UI_API_PREFIX = "/api/ui/"


def _is_public_path(path: str) -> bool:
    return (
        path in PUBLIC_PATHS
        or path.startswith("/.well-known/")
        or path.startswith("/oauth/")
        or path.startswith("/download/")
        or path in {"/ui", "/ui/", "/ui/callback"}
        or path.startswith("/ui/assets/")
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


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _is_localhost(request: Request) -> bool:
    host = _client_host(request)
    return host in {"127.0.0.1", "::1", "localhost"}


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
    if settings.auth_bypass_localhost and _is_localhost(request) and (
        settings.mode == "http" or path.startswith(HUMAN_UI_API_PREFIX)
    ):
        return Principal(email="localhost", subject="localhost", claims={"auth": "localhost-bypass"})
    if settings.auth_mode == "oauth":
        principal = _verify_oauth(request, settings)
    else:
        raise HTTPException(status_code=500, detail=f"Unsupported auth_mode: {settings.auth_mode}")
    if not path.startswith(HUMAN_UI_API_PREFIX):
        audit("auth_ok", subject=principal.subject, path=path, ip=_client_host(request))
    return principal


async def _read_body(receive: Receive) -> bytes:
    chunks = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunks.append(message.get("body", b""))
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
    if method in {"GET", "DELETE", "OPTIONS"}:
        return True
    if method != "POST" or body is None:
        return False

    methods = _mcp_methods_from_body(body)
    return bool(methods) and methods <= MCP_DISCOVERY_METHODS


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

        body = None
        downstream_receive = receive
        if path == "/mcp" and scope.get("method", "").upper() == "POST":
            body = await _read_body(receive)
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

        await self.app(scope, downstream_receive, send)


# Backwards-compatible alias.
CloudflareAccessMiddleware = AuthMiddleware
