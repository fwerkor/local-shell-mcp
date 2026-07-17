from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import html as html_lib
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlencode, urlsplit

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
    approved: bool = False


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
MAX_OAUTH_CLIENTS = 1_024
MAX_OAUTH_CODES = 2_048
MAX_REDIRECT_URIS = 10
MAX_OAUTH_URI_LENGTH = 2_048
MAX_CLIENT_NAME_LENGTH = 200
OAUTH_PENDING_CLIENT_TTL_S = 24 * 60 * 60
OAUTH_CLIENT_STORE_VERSION = 1
OAUTH_CLIENT_STORE_FILE_NAME = "oauth-clients.json"
ALL_OAUTH_SCOPES = (
    "shell:read",
    "shell:write",
    "shell:execute",
    "browser:use",
    "file:share",
    "remote:use",
)
_LEGACY_CLIENT_ID_RE = re.compile(r"local-shell-mcp-[A-Za-z0-9_-]{16,128}\Z")
_CLIENT_STORE_LOCK = threading.RLock()
_LOADED_CLIENT_STORE_PATH: Path | None = None


def public_base_url(request: Request | None = None) -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    if request is not None:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        if proto == "ws":
            proto = "http"
        elif proto == "wss":
            proto = "https"
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc
        )
        return f"{proto}://{host}".rstrip("/")
    return "http://127.0.0.1:8765"


def issuer_url(request: Request | None = None) -> str:
    settings = get_settings()
    return (settings.oauth_issuer or public_base_url(request)).rstrip("/")


def resource_url(request: Request | None = None) -> str:
    settings = get_settings()
    return (settings.oauth_resource or public_base_url(request)).rstrip("/")


def _scopes() -> list[str]:
    return list(ALL_OAUTH_SCOPES)


def _scope_value() -> str:
    return " ".join(ALL_OAUTH_SCOPES)


def _client_store_path() -> Path:
    path = get_settings().state_dir / OAUTH_CLIENT_STORE_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_clients_locked() -> None:
    global _LOADED_CLIENT_STORE_PATH

    path = _client_store_path()
    if path == _LOADED_CLIENT_STORE_PATH and (_CLIENTS or not path.exists()):
        return

    _CLIENTS.clear()
    _LOADED_CLIENT_STORE_PATH = path
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != OAUTH_CLIENT_STORE_VERSION:
            raise ValueError("unsupported OAuth client store version")
        rows = data.get("clients")
        if not isinstance(rows, dict):
            raise ValueError("OAuth client store clients field is invalid")
        for client_id, row in rows.items():
            if not isinstance(client_id, str) or not isinstance(row, dict):
                continue
            redirect_uris = row.get("redirect_uris")
            if not isinstance(redirect_uris, list) or not all(
                isinstance(uri, str) for uri in redirect_uris
            ):
                continue
            client_name = row.get("client_name")
            if client_name is not None and not isinstance(client_name, str):
                client_name = None
            try:
                created_at = int(row.get("created_at") or 0)
            except (TypeError, ValueError):
                created_at = 0
            _CLIENTS[client_id] = OAuthClient(
                client_id=client_id,
                redirect_uris=redirect_uris,
                client_name=client_name,
                created_at=created_at or int(time.time()),
                approved=True,
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        audit("oauth_client_store_unreadable", path=str(path), error=repr(exc))
        _CLIENTS.clear()


def _save_clients_locked() -> None:
    path = _client_store_path()
    payload = {
        "version": OAUTH_CLIENT_STORE_VERSION,
        "clients": {
            client_id: {
                "redirect_uris": client.redirect_uris,
                "client_name": client.client_name,
                "created_at": client.created_at,
            }
            for client_id, client in sorted(_CLIENTS.items())
            if client.approved
        },
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _get_client(client_id: str) -> OAuthClient | None:
    with _CLIENT_STORE_LOCK:
        _load_clients_locked()
        return _CLIENTS.get(client_id)


def _prune_clients_locked(now: int, *, reserve_slot: bool = False) -> None:
    for client_id, client in list(_CLIENTS.items()):
        if not client.approved and now - client.created_at > OAUTH_PENDING_CLIENT_TTL_S:
            _CLIENTS.pop(client_id, None)

    while reserve_slot and len(_CLIENTS) >= MAX_OAUTH_CLIENTS:
        pending = [client for client in _CLIENTS.values() if not client.approved]
        if not pending:
            break
        oldest = min(pending, key=lambda client: client.created_at)
        _CLIENTS.pop(oldest.client_id, None)


def _approve_client(client_id: str) -> OAuthClient | None:
    with _CLIENT_STORE_LOCK:
        _load_clients_locked()
        client = _CLIENTS.get(client_id)
        if client is None:
            return None
        if not client.approved:
            client.approved = True
            _save_clients_locked()
            audit("oauth_client_approved", client_id=client_id)
        return client


def _persist_legacy_client(client_id: str, redirect_uri: str) -> OAuthClient | None:
    if not _LEGACY_CLIENT_ID_RE.fullmatch(client_id):
        return None
    with _CLIENT_STORE_LOCK:
        _load_clients_locked()
        existing = _CLIENTS.get(client_id)
        if existing is not None:
            return existing
        _prune_clients_locked(int(time.time()), reserve_slot=True)
        if len(_CLIENTS) >= MAX_OAUTH_CLIENTS:
            return None
        client = OAuthClient(
            client_id=client_id,
            redirect_uris=[redirect_uri],
            client_name="ChatGPT",
            approved=True,
        )
        _CLIENTS[client_id] = client
        _save_clients_locked()
    audit("oauth_client_migrated", client_id=client_id, redirect_uris=[redirect_uri])
    return client


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
        "code_challenge_methods_supported": ["S256"],
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


def _prune_oauth_state(now: int | None = None) -> None:
    now = int(time.time()) if now is None else now
    code_ttl = max(1, get_settings().oauth_code_ttl_s)
    for code, item in list(_CODES.items()):
        if item.used or now - item.created_at > code_ttl:
            _CODES.pop(code, None)
    while len(_CODES) > MAX_OAUTH_CODES:
        oldest = min(_CODES, key=lambda key: _CODES[key].created_at)
        _CODES.pop(oldest, None)
    with _CLIENT_STORE_LOCK:
        _load_clients_locked()
        _prune_clients_locked(now)


def _validate_redirect_uri(uri: str) -> str | None:
    if not uri or len(uri) > MAX_OAUTH_URI_LENGTH:
        return "redirect_uri is empty or too long"
    parsed = urlsplit(uri)
    if not parsed.scheme or parsed.fragment:
        return "redirect_uri must be absolute and must not contain a fragment"
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        return "HTTP redirect_uri must include a host"
    return None


async def oauth_register(request: Request) -> JSONResponse:
    _prune_oauth_state()
    try:
        body = await request.json()
    except Exception:
        return _json(
            {"error": "invalid_client_metadata", "error_description": "Request body must be JSON"},
            status_code=400,
        )
    raw_redirects = body.get("redirect_uris", [])
    if (
        not isinstance(raw_redirects, list)
        or not raw_redirects
        or len(raw_redirects) > MAX_REDIRECT_URIS
    ):
        return _json(
            {
                "error": "invalid_redirect_uri",
                "error_description": f"Provide 1 to {MAX_REDIRECT_URIS} redirect_uris",
            },
            status_code=400,
        )
    redirect_uris = [str(x) for x in raw_redirects if isinstance(x, str)]
    if len(redirect_uris) != len(raw_redirects):
        return _json(
            {
                "error": "invalid_redirect_uri",
                "error_description": "redirect_uris must contain strings",
            },
            status_code=400,
        )
    for uri in redirect_uris:
        error = _validate_redirect_uri(uri)
        if error:
            return _json(
                {"error": "invalid_redirect_uri", "error_description": error}, status_code=400
            )
    client_name = body.get("client_name") if isinstance(body.get("client_name"), str) else None
    if client_name and len(client_name) > MAX_CLIENT_NAME_LENGTH:
        return _json(
            {"error": "invalid_client_metadata", "error_description": "client_name is too long"},
            status_code=400,
        )
    client_id = "local-shell-mcp-" + secrets.token_urlsafe(24)
    client = OAuthClient(
        client_id=client_id,
        redirect_uris=redirect_uris,
        client_name=client_name,
    )
    with _CLIENT_STORE_LOCK:
        _load_clients_locked()
        _prune_clients_locked(int(time.time()), reserve_slot=True)
        if len(_CLIENTS) >= MAX_OAUTH_CLIENTS:
            return _json(
                {
                    "error": "temporarily_unavailable",
                    "error_description": "OAuth client registry is full",
                },
                status_code=503,
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
    _prune_oauth_state()
    client = _get_client(params["client_id"])
    if not client and not _LEGACY_CLIENT_ID_RE.fullmatch(params["client_id"]):
        return "Unknown client_id"
    if not client:
        redirect_error = _validate_redirect_uri(params["redirect_uri"])
        if redirect_error:
            return redirect_error
    elif params["redirect_uri"] not in client.redirect_uris:
        return "redirect_uri is not registered for this client"
    if not params.get("code_challenge"):
        return "Missing code_challenge"
    if params.get("code_challenge_method") != "S256":
        return "Only code_challenge_method=S256 is supported"
    return None


def _hidden_inputs(params: dict[str, str]) -> str:
    return "\n".join(
        f'<input type="hidden" name="{html_lib.escape(k, quote=True)}" value="{html_lib.escape(v, quote=True)}" />'
        for k, v in params.items()
    )


@lru_cache(maxsize=1)
def _authorize_template() -> Template:
    template = files("local_shell_mcp").joinpath("oauth_authorize.html").read_text(encoding="utf-8")
    return Template(template)


_SCOPE_DETAILS = {
    "shell:read": (
        "Read workspace",
        "Inspect files, directories, terminal output, and runtime state.",
    ),
    "shell:write": (
        "Change workspace",
        "Create, edit, move, or delete files in the configured workspace.",
    ),
    "shell:execute": ("Run commands", "Execute commands and manage persistent terminal sessions."),
    "browser:use": (
        "Use browser tools",
        "Open pages, automate browser actions, and capture page output.",
    ),
    "file:share": (
        "Share files",
        "Create temporary links for files from the configured workspace.",
    ),
    "remote:use": ("Use remote workers", "Access configured remote machines through this service."),
}


def _scope_items(scope: str) -> str:
    items: list[str] = []
    for name in dict.fromkeys(item for item in scope.split() if item):
        title, description = _SCOPE_DETAILS.get(
            name, (name, "Access requested by this OAuth client.")
        )
        escaped_title = html_lib.escape(title)
        escaped_description = html_lib.escape(description)
        items.append(
            f"""<li class="permission">
              <span class="permission-icon" aria-hidden="true">✓</span>
              <span><strong>{escaped_title}</strong><small>{escaped_description}</small></span>
            </li>"""
        )
    return "\n".join(items)


def _authorize_form(params: dict[str, str], error: str | None = None) -> HTMLResponse:
    settings = get_settings()
    scope = _scope_value()
    resource = params.get("resource") or resource_url()
    client = _get_client(params.get("client_id", ""))
    client_name = client.client_name if client and client.client_name else "ChatGPT"
    error_html = (
        f'<div class="notice notice-error" role="alert"><strong>Authorization failed</strong><span>{html_lib.escape(error)}</span></div>'
        if error
        else ""
    )
    if settings.oauth_admin_pin:
        pin_field = """<label class="field" for="pin">
          <span>Admin PIN</span>
          <input id="pin" type="password" name="pin" autocomplete="current-password" required
                 aria-describedby="pin-help" placeholder="Enter the configured admin PIN" />
        </label>
        <p class="field-help" id="pin-help">Use the value configured in <code>LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN</code>.</p>"""
        security_notice = "Only approve this request if you initiated it from a trusted client."
    else:
        pin_field = """<div class="notice notice-warning" role="status">
          <strong>No admin PIN is configured</strong>
          <span>This request can be approved without a PIN. Configure one before exposing this service publicly.</span>
        </div>"""
        security_notice = "This service currently allows approval without an admin PIN."
    normalized_params = {**params, "scope": scope}
    html = _authorize_template().substitute(
        client_name=html_lib.escape(client_name),
        scope_items=_scope_items(scope),
        resource_title=html_lib.escape(resource, quote=True),
        resource=html_lib.escape(resource),
        error_html=error_html,
        hidden_inputs=_hidden_inputs(normalized_params),
        pin_field=pin_field,
        security_notice=html_lib.escape(security_notice),
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


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

    client = _approve_client(params["client_id"])
    if client is None:
        client = _persist_legacy_client(params["client_id"], params["redirect_uri"])
        if client is None:
            return _authorize_form(params, error="OAuth client registry is full")

    code = secrets.token_urlsafe(32)
    auth_code = AuthCode(
        code=code,
        client_id=params["client_id"],
        redirect_uri=params["redirect_uri"],
        scope=_scope_value(),
        resource=params.get("resource") or resource_url(request),
        code_challenge=params.get("code_challenge"),
        code_challenge_method=params.get("code_challenge_method"),
    )
    _prune_oauth_state()
    if len(_CODES) >= MAX_OAUTH_CODES:
        return _authorize_form(
            params, error="Too many pending authorization requests; try again later"
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


def issue_access_token(
    *,
    client_id: str,
    scope: str,
    resource: str,
    subject: str = "local-user",
    issuer: str | None = None,
) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": (issuer or issuer_url()).rstrip("/"),
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
    _prune_oauth_state()
    code_obj = _CODES.get(code)
    if not code_obj or code_obj.used:
        return _json(
            {"error": "invalid_grant", "error_description": "Unknown or used code"}, status_code=400
        )
    if int(time.time()) - code_obj.created_at > get_settings().oauth_code_ttl_s:
        return _json(
            {"error": "invalid_grant", "error_description": "Expired code"}, status_code=400
        )
    if code_obj.client_id != client_id or code_obj.redirect_uri != redirect_uri:
        return _json(
            {"error": "invalid_grant", "error_description": "Client or redirect mismatch"},
            status_code=400,
        )
    if not _verify_pkce(code_obj, verifier):
        return _json(
            {"error": "invalid_grant", "error_description": "PKCE verification failed"},
            status_code=400,
        )
    code_obj.used = True
    _CODES.pop(code, None)
    token = issue_access_token(
        client_id=client_id,
        scope=code_obj.scope,
        resource=code_obj.resource,
        issuer=issuer_url(request),
    )
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
