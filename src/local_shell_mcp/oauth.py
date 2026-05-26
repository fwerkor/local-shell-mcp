from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import jwt
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .audit import audit
from .settings import get_settings


@dataclass
class OAuthClient:
    client_id: str
    redirect_uris: list[str] = field(default_factory=list)
    client_name: str | None = None
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class AuthCode:
    code: str
    client_id: str
    redirect_uri: str
    scope: str
    resource: str
    code_challenge: str | None
    code_challenge_method: str | None
    created_at: int = field(default_factory=lambda: int(time.time()))
    used: bool = False


_CLIENTS: dict[str, OAuthClient] = {}
_CODES: dict[str, AuthCode] = {}


def public_base_url(request: Request | None = None) -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    if request is not None:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return f"{proto}://{host}".rstrip("/")
    return "http://127.0.0.1:8765"


def issuer_url(request: Request | None = None) -> str:
    settings = get_settings()
    return (settings.oauth_issuer or public_base_url(request)).rstrip("/")


def resource_url(request: Request | None = None) -> str:
    settings = get_settings()
    return (settings.oauth_resource or public_base_url(request)).rstrip("/")


def _scopes() -> list[str]:
    return ["shell:read", "shell:write", "shell:execute", "git:write", "browser:use"]


def protected_resource_metadata(request: Request) -> dict[str, Any]:
    return {
        "resource": resource_url(request),
        "authorization_servers": [issuer_url(request)],
        "scopes_supported": _scopes(),
        "resource_documentation": f"{public_base_url(request)}/docs",
    }


def authorization_server_metadata(request: Request) -> dict[str, Any]:
    issuer = issuer_url(request)
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": _scopes(),
        "authorization_response_iss_parameter_supported": True,
        "resource_parameter_supported": True,
    }


def _json(data: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code, headers={"Cache-Control": "no-store"})


async def oauth_protected_resource(request: Request) -> JSONResponse:
    return _json(protected_resource_metadata(request))


async def oauth_server_metadata(request: Request) -> JSONResponse:
    return _json(authorization_server_metadata(request))


async def oauth_register(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    client_id = "local-shell-mcp-" + secrets.token_urlsafe(24)
    redirect_uris = [str(x) for x in body.get("redirect_uris", []) if isinstance(x, str)]
    client = OAuthClient(
        client_id=client_id,
        redirect_uris=redirect_uris,
        client_name=body.get("client_name") if isinstance(body.get("client_name"), str) else None,
    )
    _CLIENTS[client_id] = client
    audit("oauth_client_registered", client_id=client_id, redirect_uris=redirect_uris)
    return _json(
        {
            "client_id": client_id,
            "client_id_issued_at": client.created_at,
            "client_name": client.client_name or "ChatGPT",
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


def _validate_authorize_params(params: dict[str, str]) -> str | None:
    if params.get("response_type") != "code":
        return "Only response_type=code is supported"
    if not params.get("client_id"):
        return "Missing client_id"
    if not params.get("redirect_uri"):
        return "Missing redirect_uri"
    client = _CLIENTS.get(params["client_id"])
    if client and client.redirect_uris and params["redirect_uri"] not in client.redirect_uris:
        return "redirect_uri is not registered for this client"
    if params.get("code_challenge_method") and params.get("code_challenge_method") not in {"S256", "plain"}:
        return "Unsupported code_challenge_method"
    return None


def _hidden_inputs(params: dict[str, str]) -> str:
    def esc(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    return "\n".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}" />' for k, v in params.items())


def _authorize_form(params: dict[str, str], error: str | None = None) -> HTMLResponse:
    settings = get_settings()
    scope = params.get("scope") or " ".join(_scopes())
    resource = params.get("resource") or resource_url()
    error_html = f'<p style="color:#b00020">{error}</p>' if error else ""
    pin_hint = "Enter LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN to approve this ChatGPT connector."
    if not settings.oauth_admin_pin:
        pin_hint = "No admin PIN is configured. Click Approve to continue. Set LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN before exposing this publicly."
    html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Authorize local-shell-mcp</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 720px; margin: 48px auto; line-height: 1.45;">
  <h1>Authorize local-shell-mcp</h1>
  <p>This grants ChatGPT access to tools that can execute shell commands inside the configured container workspace.</p>
  <p><strong>Resource:</strong> {resource}</p>
  <p><strong>Scopes:</strong> {scope}</p>
  {error_html}
  <form method="post" action="/oauth/authorize">
    {_hidden_inputs(params)}
    <label>Admin PIN<br><input type="password" name="pin" autofocus style="width: 320px; padding: 8px;" /></label>
    <p style="color:#555">{pin_hint}</p>
    <button type="submit" style="padding: 8px 14px;">Approve</button>
  </form>
</body>
</html>"""
    return HTMLResponse(html)


def _make_redirect(redirect_uri: str, query: dict[str, str]) -> RedirectResponse:
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(query)}", status_code=302)


async def oauth_authorize_get(request: Request) -> Response:
    params = {k: v for k, v in request.query_params.items()}
    error = _validate_authorize_params(params)
    if error:
        return _authorize_form(params, error=error)
    return _authorize_form(params)


async def oauth_authorize_post(request: Request) -> Response:
    form = await request.form()
    params = {k: str(v) for k, v in form.items() if k != "pin"}
    error = _validate_authorize_params(params)
    if error:
        return _authorize_form(params, error=error)

    settings = get_settings()
    expected_pin = settings.oauth_admin_pin
    submitted_pin = str(form.get("pin") or "")
    if expected_pin and not hmac.compare_digest(submitted_pin, expected_pin):
        audit("oauth_pin_failed", client_id=params.get("client_id"))
        return _authorize_form(params, error="Invalid admin PIN")

    code = secrets.token_urlsafe(32)
    auth_code = AuthCode(
        code=code,
        client_id=params["client_id"],
        redirect_uri=params["redirect_uri"],
        scope=params.get("scope") or " ".join(_scopes()),
        resource=params.get("resource") or resource_url(request),
        code_challenge=params.get("code_challenge"),
        code_challenge_method=params.get("code_challenge_method"),
    )
    _CODES[code] = auth_code
    audit("oauth_code_issued", client_id=auth_code.client_id, resource=auth_code.resource)
    query = {"code": code, "iss": issuer_url(request)}
    if params.get("state"):
        query["state"] = params["state"]
    return _make_redirect(params["redirect_uri"], query)


def _verify_pkce(code_obj: AuthCode, verifier: str | None) -> bool:
    if not code_obj.code_challenge:
        return True
    if not verifier:
        return False
    if code_obj.code_challenge_method == "S256":
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return hmac.compare_digest(challenge, code_obj.code_challenge)
    return hmac.compare_digest(verifier, code_obj.code_challenge)


def issue_access_token(*, client_id: str, scope: str, resource: str, subject: str = "local-user") -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": issuer_url(),
        "sub": subject,
        "aud": resource,
        "iat": now,
        "client_id": client_id,
        "scope": scope,
    }
    if settings.oauth_access_token_ttl_s > 0:
        payload["exp"] = now + settings.oauth_access_token_ttl_s
    return jwt.encode(payload, settings.oauth_jwt_secret, algorithm="HS256")


async def oauth_token(request: Request) -> JSONResponse:
    form = await request.form()
    grant_type = str(form.get("grant_type") or "")
    if grant_type != "authorization_code":
        return _json({"error": "unsupported_grant_type"}, status_code=400)
    code = str(form.get("code") or "")
    client_id = str(form.get("client_id") or "")
    redirect_uri = str(form.get("redirect_uri") or "")
    verifier = str(form.get("code_verifier") or "") or None
    code_obj = _CODES.get(code)
    if not code_obj or code_obj.used:
        return _json({"error": "invalid_grant", "error_description": "Unknown or used code"}, status_code=400)
    if int(time.time()) - code_obj.created_at > get_settings().oauth_code_ttl_s:
        return _json({"error": "invalid_grant", "error_description": "Expired code"}, status_code=400)
    if code_obj.client_id != client_id or code_obj.redirect_uri != redirect_uri:
        return _json({"error": "invalid_grant", "error_description": "Client or redirect mismatch"}, status_code=400)
    if not _verify_pkce(code_obj, verifier):
        return _json({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)
    code_obj.used = True
    token = issue_access_token(client_id=client_id, scope=code_obj.scope, resource=code_obj.resource)
    audit("oauth_token_issued", client_id=client_id, resource=code_obj.resource)
    body = {
        "access_token": token,
        "token_type": "Bearer",
        "scope": code_obj.scope,
    }
    if get_settings().oauth_access_token_ttl_s > 0:
        body["expires_in"] = get_settings().oauth_access_token_ttl_s
    return _json(body)


def validate_bearer_token(token: str, request: Request | None = None) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.oauth_jwt_secret,
        algorithms=["HS256"],
        audience=resource_url(request),
        issuer=issuer_url(request),
        options={"require": ["iat", "aud", "iss"]},
    )
