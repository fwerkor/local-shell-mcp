"""Authenticate HTTP and MCP requests while keeping OAuth bootstrap routes public."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..audit import audit
from ..config.settings import Settings, get_settings

PUBLIC_PATHS = {
    "/healthz",
    "/readyz",
    "/docs",
    "/openapi.json",
    "/join",
    "/remote/worker-bundle.tgz",
    "/remote/register",
    "/remote/poll",
    "/remote/result",
}


@dataclass
class Principal:
    """Authenticated caller identity attached to requests after local bypass or OAuth verification."""

    email: str | None
    subject: str | None
    claims: dict[str, Any]


def _client_host(request: Request) -> str:
    """Extract the peer host from a FastAPI request without failing when client metadata is absent."""
    return request.client.host if request.client else ""


def _is_localhost(request: Request) -> bool:
    """Detect requests eligible for localhost auth bypass in HTTP mode."""
    host = _client_host(request)
    return host in {"127.0.0.1", "::1", "localhost"}


def _extract_token(request: Request) -> str | None:
    """Parse a bearer token from the Authorization header without accepting other auth schemes."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _bearer_challenge(request: Request, *, error: str | None = None) -> str:
    """Build the OAuth challenge advertised to MCP clients when auth is missing or invalid."""
    from .oauth import protected_resource_metadata

    metadata_url = (
        protected_resource_metadata(request)["resource"].rstrip("/")
        + "/.well-known/oauth-protected-resource"
    )
    parts = [f'resource_metadata="{metadata_url}"']
    if error:
        parts.append(f'error="{error}"')
    return "Bearer " + ", ".join(parts)


def _verify_oauth(request: Request, settings: Settings) -> Principal:
    """Validate an OAuth bearer token and return the subject claims used by downstream handlers."""
    from .oauth import validate_bearer_token

    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing OAuth bearer token",
            headers={"WWW-Authenticate": _bearer_challenge(request)},
        )
    try:
        claims = validate_bearer_token(token, request)
    except jwt.PyJWTError as exc:
        audit(
            "oauth_auth_failed",
            error=str(exc),
            path=str(request.url.path),
            ip=_client_host(request),
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid OAuth bearer token",
            headers={
                "WWW-Authenticate": _bearer_challenge(
                    request, error="invalid_token"
                )
            },
        ) from exc
    return Principal(email=None, subject=claims.get("sub"), claims=claims)


def verify_request(request: Request) -> Principal:
    """Resolve the effective principal for a request according to configured auth mode and local bypass rules."""
    settings = get_settings()
    if settings.auth_mode == "none":
        return Principal(
            email=None, subject="anonymous", claims={"auth": "none"}
        )
    if (
        settings.auth_bypass_localhost
        and _is_localhost(request)
        and settings.mode == "http"
    ):
        return Principal(
            email="localhost",
            subject="localhost",
            claims={"auth": "localhost-bypass"},
        )
    if settings.auth_mode == "oauth":
        principal = _verify_oauth(request, settings)
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Unsupported auth_mode: {settings.auth_mode}",
        )
    audit(
        "auth_ok",
        subject=principal.subject,
        path=str(request.url.path),
        ip=_client_host(request),
    )
    return principal


class AuthMiddleware:
    """ASGI middleware for OAuth bearer verification."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Apply public-route bypasses and principal injection for protected HTTP requests."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if (
            path in PUBLIC_PATHS
            or path.startswith("/.well-known/")
            or path.startswith("/oauth/")
        ):
            await self.app(scope, receive, send)
            return

        try:
            request = Request(scope, receive)
            principal = verify_request(request)
            scope.setdefault("state", {})["principal"] = principal
        except HTTPException as exc:
            headers = getattr(exc, "headers", None) or {}
            response = JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=headers,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# Backwards-compatible alias.
type CloudflareAccessMiddleware = AuthMiddleware
