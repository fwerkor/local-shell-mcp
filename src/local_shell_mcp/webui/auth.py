"""Single-login WebUI sessions backed by the Controller's SQLite database.

LSM OAuth owns identity and scopes; the React client receives a short-lived
OAuth bearer minted from the same issuer, never a second identity database.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from ..settings import get_settings

COOKIE = "lsm_workspace"
TICKET_TTL = 60
SESSION_TTL = 3600


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    from urllib.parse import urlsplit

    parsed = urlsplit(origin)
    settings = get_settings()
    configured_origin = getattr(settings, "public_base_url", None)
    if configured_origin:
        expected = urlsplit(configured_origin)
        allowed = (parsed.scheme == expected.scheme and parsed.netloc == expected.netloc)
        if not allowed:
            # A directly connected local browser may use loopback while the
            # Controller advertises a public URL. Forwarded proxy connections
            # must never inherit this local-origin exception.
            from ..auth import _is_direct_localhost_request

            allowed = (_is_direct_localhost_request(request)
                       and parsed.scheme == request.url.scheme
                       and parsed.netloc == request.headers.get("host"))
    else:
        allowed = parsed.scheme == request.url.scheme and parsed.netloc == request.headers.get("host")
    if not allowed:
        raise HTTPException(403, detail="Cross-origin authentication operation blocked")


@dataclass(frozen=True)
class WebSession:
    owner: str
    scopes: str
    grant_until: int


class WebAuthStore:
    def __init__(self, directory: Path):
        from ..sqlite_store import shared_database

        self.database = shared_database(directory.resolve())

    def issue_ticket(self, owner: str, scopes: str, grant_until: int) -> str:
        now = int(time.time())
        if not owner or grant_until <= now:
            raise ValueError("An active authenticated identity is required")
        secret = secrets.token_urlsafe(32)
        with self.database.connect() as db:
            db.execute("DELETE FROM web_login_tickets WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO web_login_tickets(hash,owner,scopes,grant_until,expires_at) VALUES(?,?,?,?,?)",
                       (_hash(secret), owner, scopes, grant_until, now + TICKET_TTL))
        return secret

    def redeem(self, ticket: str) -> tuple[str, WebSession]:
        if len(ticket) > 256 or len(ticket) < 32:
            raise ValueError("Invalid login ticket")
        now = int(time.time())
        with self.database.connect() as db:
            db.execute("DELETE FROM web_sessions WHERE expires_at<=?", (now,))
            row = db.execute("DELETE FROM web_login_tickets WHERE hash=? RETURNING owner,scopes,grant_until,expires_at",
                             (_hash(ticket),)).fetchone()
            if not row or row["expires_at"] < now or row["grant_until"] < now:
                raise ValueError("Invalid or expired login ticket")
            raw = secrets.token_urlsafe(48)
            expiry = min(row["grant_until"], now + SESSION_TTL)
            db.execute("INSERT INTO web_sessions(hash,owner,scopes,grant_until,expires_at) VALUES(?,?,?,?,?)",
                       (_hash(raw), row["owner"], row["scopes"], row["grant_until"], expiry))
            return raw, WebSession(row["owner"], row["scopes"], row["grant_until"])

    def session(self, cookie: str) -> WebSession | None:
        if not cookie or len(cookie) > 256:
            return None
        now = int(time.time())
        with self.database.connect() as db:
            row = db.execute("SELECT owner,scopes,grant_until,expires_at FROM web_sessions WHERE hash=?",
                             (_hash(cookie),)).fetchone()
            if not row or row["expires_at"] <= now or row["grant_until"] <= now:
                return None
            return WebSession(row["owner"], row["scopes"], row["grant_until"])

    def revoke(self, cookie: str) -> None:
        with self.database.connect() as db:
            db.execute("DELETE FROM web_sessions WHERE hash=?", (_hash(cookie),))


def _store() -> WebAuthStore:
    return WebAuthStore(get_settings().state_dir)


def _owner(request: Request) -> tuple[str, str, int]:
    from ..auth import principal_scopes

    principal = getattr(request.state, "principal", None)
    if principal and principal.subject:
        from ..oauth import ALL_OAUTH_SCOPES

        scopes = " ".join(sorted(principal_scopes(principal)))
        if principal.claims.get("auth") in {"none", "local-cli", "localhost-bypass"}:
            scopes = " ".join(sorted(ALL_OAUTH_SCOPES))
        expiry = principal.claims.get("exp")
        return principal.subject, scopes, min(int(expiry), int(time.time()) + SESSION_TTL) if isinstance(expiry, int) else int(time.time()) + SESSION_TTL
    if get_settings().auth_mode == "none":
        from ..oauth import ALL_OAUTH_SCOPES

        return "local", " ".join(sorted(ALL_OAUTH_SCOPES)), int(time.time()) + SESSION_TTL
    raise HTTPException(401, detail="LSM login is required")


def _frontend_user(session: WebSession) -> dict:
    owner_id = hashlib.sha256(session.owner.encode("utf-8")).hexdigest()[:24]
    return {
        "id": owner_id, "_id": owner_id, "username": "workspace", "name": "local-shell-mcp",
        "email": "workspace@local-shell-mcp.invalid",
        "role": "ADMIN" if (get_settings().auth_mode == "none" and session.owner == "local")
        or "admin:config" in session.scopes.split() else "USER",
        "provider": "local-shell-mcp",
        "emailVerified": True, "avatar": "", "personalization": {},
    }


# This is an OAuth client bootstrap, not another identity or login service.
# The existing Controller authorize endpoint owns PIN verification and grants.
_LOGIN_HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>local-shell-mcp</title>
<style>html{color-scheme:light dark}body{font:16px system-ui;max-width:32rem;margin:20vh auto;padding:1.5rem}a{color:inherit}</style>
</head><body><p role="status" id="status">Opening authentication…</p>
<a href="/auth/login" id="retry" hidden>Try again</a><script type="module">
const key = 'lsm.workspace.oauth';
const status = document.getElementById('status');
const b64 = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const random = () => b64(crypto.getRandomValues(new Uint8Array(48)));
async function checked(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error_description || data.error || data.detail || `Authentication failed (${response.status})`);
  return data;
}
try {
  const url = new URL(location.href);
  const callback = `${location.origin}/auth/login`;
  if (url.searchParams.has('error')) throw new Error('Authorization was declined. Start authentication again.');
  if (url.searchParams.has('code')) {
    const pending = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (!pending || url.searchParams.get('state') !== pending.state) throw new Error('OAuth state verification failed. Start authentication again.');
    sessionStorage.removeItem(key);
    history.replaceState(null, '', '/auth/login');
    const token = await checked(await fetch('/oauth/token', {
      method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({grant_type:'authorization_code', code:url.searchParams.get('code'),
        client_id:pending.client_id, redirect_uri:callback, code_verifier:pending.verifier})
    }));
    if (!token.access_token) throw new Error('The Controller did not return an OAuth token.');
    const ticket = await checked(await fetch('/api/ui/webui-ticket', {
      method:'POST', headers:{Authorization:`Bearer ${token.access_token}`}
    }));
    const form = document.createElement('form');
    form.method = 'POST'; form.action = '/api/auth/lsm';
    const input = document.createElement('input');
    input.type = 'hidden'; input.name = 'ticket'; input.value = ticket.ticket;
    form.append(input); document.body.append(form); form.submit();
  } else {
    const metadata = await checked(await fetch('/.well-known/oauth-protected-resource'));
    if (typeof metadata.resource !== 'string' || !metadata.resource) throw new Error('The Controller did not advertise an OAuth resource.');
    const client = await checked(await fetch('/oauth/register', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({client_name:'WebUI', redirect_uris:[callback]})
    }));
    const verifier = random(), state = random();
    const challenge = b64(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
    sessionStorage.setItem(key, JSON.stringify({client_id:client.client_id, verifier, state}));
    const authorize = new URL('/oauth/authorize', location.origin);
    authorize.search = new URLSearchParams({response_type:'code', client_id:client.client_id,
      redirect_uri:callback, scope:'shell:read shell:write shell:execute browser:use file:share remote:use admin:config',
      resource:metadata.resource, code_challenge:challenge, code_challenge_method:'S256', state});
    location.replace(authorize);
  }
} catch (error) {
  status.textContent = error instanceof Error ? error.message : String(error);
  document.getElementById('retry').hidden = false;
}
</script></body></html>'''


async def login_page(request: Request) -> Response:
    if get_settings().auth_mode == "none" or _store().session(request.cookies.get(COOKIE, "")):
        return RedirectResponse("/c/new", status_code=303)
    return HTMLResponse(_LOGIN_HTML, headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin"})


async def login_ticket(request: Request) -> Response:
    # This exchange represents the OAuth grant just approved in the browser.
    # The Controller's optional local bypass must not replace an explicitly
    # supplied bearer identity or its scopes with the ambient localhost user.
    settings = get_settings()
    if settings.auth_mode == "oauth" and request.headers.get("authorization"):
        from ..auth import _verify_oauth

        request.state.principal = _verify_oauth(request, settings)
    owner, scopes, expiry = _owner(request)
    token = _store().issue_ticket(owner, scopes, expiry)
    origin = get_settings().public_base_url or str(request.base_url).rstrip("/")
    return JSONResponse({"ticket": token, "url": origin})


async def authenticate(request: Request) -> Response:
    _same_origin(request)
    form = await request.form()
    raw = form.get("ticket")
    if not isinstance(raw, str):
        raise HTTPException(400, detail="Login ticket is required")
    try:
        cookie, _ = _store().redeem(raw)
    except ValueError as exc:
        raise HTTPException(401, detail=str(exc)) from exc
    response = RedirectResponse(url="/c/new", status_code=303)
    response.set_cookie(COOKIE, cookie, max_age=SESSION_TTL, path="/", httponly=True,
                        secure=request.url.scheme == "https", samesite="lax")
    return response


async def refresh(request: Request) -> Response:
    _same_origin(request)
    session = _store().session(request.cookies.get(COOKIE, ""))
    if session is None and get_settings().auth_mode == "none":
        # The Controller itself is explicitly unauthenticated. Make the
        # first-party React frontend usable directly without an extra login
        # page, cookie, or redundant LibreChat identity database.
        from ..oauth import ALL_OAUTH_SCOPES

        session = WebSession("local", " ".join(sorted(ALL_OAUTH_SCOPES)),
                             int(time.time()) + SESSION_TTL)
    if session is None:
        raise HTTPException(401, detail="WebUI login expired")
    # JWT is already an LSM OAuth dependency but is not needed merely to serve
    # the React shell or existing Controller endpoints.
    import jwt

    from ..oauth import issue_access_token, issuer_url, resource_url

    token = issue_access_token(client_id="lsm-webui", scope=session.scopes,
                               resource=resource_url(request), subject=session.owner,
                               issuer=issuer_url(request))
    claims = jwt.decode(token, options={"verify_signature": False})
    # The bearer cannot extend the identity grant recorded at initial LSM login.
    if claims.get("exp") is None or int(claims["exp"]) > session.grant_until:
        claims["exp"] = session.grant_until
        token = jwt.encode(claims, get_settings().oauth_jwt_secret, algorithm="HS256")
    return JSONResponse({"token": token, "user": _frontend_user(session)})


async def logout(request: Request) -> Response:
    _same_origin(request)
    cookie = request.cookies.get(COOKIE, "")
    if cookie:
        _store().revoke(cookie)
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(COOKIE, path="/")
    return response


async def current_user(request: Request) -> Response:
    owner, scopes, grant = _owner(request)
    return JSONResponse(_frontend_user(WebSession(owner, scopes, grant)))


def auth_routes() -> list[Route]:
    return [
        Route("/auth/login", login_page, methods=["GET"]),
        Route("/api/ui/webui-ticket", login_ticket, methods=["POST"]),
        Route("/api/auth/lsm", authenticate, methods=["POST"]),
        Route("/api/auth/refresh", refresh, methods=["POST"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/user", current_user, methods=["GET"]),
    ]
