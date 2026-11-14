"""LibreChat Action OAuth2 code/refresh flow, protected by the LSM browser identity.

Based on api/server/routes/actions.js, ActionService.js and packages/api/src/oauth/tokens.ts
at LibreChat e8f3be08. Unlike the upstream in-memory flow cache, flow state and
sealed tokens persist in the controller SQLite database. No provider secret is
sent to the browser, model, checkpoints, or application log.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import weakref
from urllib.parse import urlencode, urlsplit

from .actions import ActionRepository

_FLOW_TTL = 600
_TOKEN_LIMIT = 32 * 1024
# One refresh at a time per OAuth Action per event loop; the SQLite record is
# checked again under this lock so concurrent model runs do not race rotating
# refresh tokens. Keyed by loop to avoid binding a lock to a retired loop.
_REFRESH_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _refresh_lock(owner: str, action_id: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _REFRESH_LOCKS.setdefault(loop, {})
    return locks.setdefault((owner, action_id), asyncio.Lock())


def cookie_name(action_id: str) -> str:
    return "lsm_action_oauth_" + hashlib.sha256(action_id.encode()).hexdigest()[:24]


def _action(repo: ActionRepository, owner: str, action_id: str):
    with repo.database.connect() as db:
        row = db.execute("SELECT * FROM action_records WHERE id=? AND owner=?", (action_id, owner)).fetchone()
    if row is None or json.loads(row["metadata"]).get("auth", {}).get("type") != "oauth":
        raise KeyError("OAuth Action not found")
    return row


def _base_url() -> str:
    from urllib.parse import urlsplit

    from ..settings import get_settings

    value = (get_settings().public_base_url or "").rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in
                                              {"localhost", "127.0.0.1", "::1"})) or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Configure LOCAL_SHELL_MCP_PUBLIC_BASE_URL for Action OAuth callbacks")
    return value


def bind_cookie(repo: ActionRepository, owner: str, action_id: str) -> str:
    _action(repo, owner, action_id)
    value = {"owner": owner, "action_id": action_id, "expires": int(time.time()) + _FLOW_TTL}
    return repo._cipher().encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()


def _check_cookie(repo: ActionRepository, value: str | None, owner: str, action_id: str) -> bool:
    if not value:
        return False
    try:
        payload = json.loads(repo._cipher().decrypt(value.encode(), ttl=_FLOW_TTL).decode())
    except (ValueError, UnicodeError, KeyError, TypeError):
        return False
    except Exception:
        # Includes cryptography InvalidToken, never display cookie/secret.
        return False
    return (payload.get("owner") == owner and payload.get("action_id") == action_id and
            type(payload.get("expires")) is int and payload["expires"] >= int(time.time()))


def begin_flow(repo: ActionRepository, owner: str, action_id: str, run_id: str, call_id: str,
               *, reissue: dict | None = None) -> tuple[str, str] | None:
    """Create one replay-proof authorization attempt, returning (auth URL, opaque state)."""
    from .action_runtime import _allowed_domain

    base = _base_url()
    row = _action(repo, owner, action_id)
    metadata = json.loads(row["metadata"])
    auth = metadata["auth"]
    target = urlsplit(auth["authorization_url"])
    token_target = urlsplit(auth["client_url"])
    if not (_allowed_domain(target.hostname) and _allowed_domain(token_target.hostname)):
        raise PermissionError("OAuth provider domain not allowed")
    creds = repo._credentials(row)
    state = secrets.token_urlsafe(32)
    redirect = f"{base}/api/actions/{action_id}/oauth/callback"
    now = int(time.time())
    params = urlencode({"client_id": creds["oauth_client_id"], "scope": auth["scope"],
                        "redirect_uri": redirect, "access_type": "offline", "response_type": "code",
                        "state": state})
    separator = "&" if target.query else "?"
    auth_url = auth["authorization_url"] + separator + params
    with repo.database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT version FROM action_records WHERE id=? AND owner=?", (action_id, owner)).fetchone()
        if current is None or current["version"] != row["version"]:
            raise ValueError("Action changed during OAuth initialization")
        if reissue is not None:
            run = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='requires_action'", (run_id, owner),
            ).fetchone()
            pending = json.loads(run["state"]).get("pendingAction") if run else None
            payload = pending.get("payload") if isinstance(pending, dict) else None
            if (not isinstance(payload, dict) or payload.get("type") != "action_oauth"
                    or payload.get("action_id") != action_id or payload.get("tool_call_id") != call_id
                    or payload.get("action_version") != row["version"]
                    or not isinstance(payload.get("step_id"), str)
                    or payload.get("tool_name") != reissue.get("tool_name")):
                raise PermissionError("Stale Action OAuth prompt cannot be reissued")
            existing = db.execute(
                "SELECT 1 FROM action_oauth_flows WHERE run_id=? AND owner=? AND action_id=? AND call_id=? "
                "AND expires_at>? AND used_at IS NULL LIMIT 1",
                (run_id, owner, action_id, call_id, now),
            ).fetchone()
            if existing:
                return None
        db.execute("DELETE FROM action_oauth_flows WHERE expires_at<?", (now,))
        # Reissuing a timed-out prompt invalidates the old callback state.
        db.execute("DELETE FROM action_oauth_flows WHERE run_id=? AND action_id=? AND call_id=?",
                   (run_id, action_id, call_id))
        db.execute(
            "INSERT INTO action_oauth_flows(state_hash,owner,action_id,action_version,run_id,call_id,redirect_uri,expires_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (hashlib.sha256(state.encode()).hexdigest(), owner, action_id, row["version"], run_id, call_id,
             redirect, now + _FLOW_TTL),
        )
        if reissue is not None:
            # The replacement link is committed with its one-use state. A
            # restart cannot lose the new URL while retaining an unusable flow.
            payload_event = {"event": "on_run_step_delta", "data": {
                "id": payload["step_id"], "delta": {"type": "tool_calls", "tool_calls": [
                    {"id": call_id, "name": payload["tool_name"], "args": ""}],
                    "auth": auth_url, "expires_at": (now + _FLOW_TTL) * 1000},
            }}
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                       (run_id, json.dumps(payload_event, ensure_ascii=False, separators=(",", ":"))))
    return auth_url, state


def claim_callback(repo: ActionRepository, action_id: str, state: str, cookie: str | None) -> tuple[str, dict, dict, str]:
    """One-time claim happens before token exchange; no callback can replay a code."""
    if not isinstance(state, str) or not 10 <= len(state) <= 256:
        raise PermissionError("Invalid OAuth state")
    key = hashlib.sha256(state.encode()).hexdigest()
    with repo.database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        flow = db.execute("SELECT * FROM action_oauth_flows WHERE state_hash=? AND action_id=?",
                          (key, action_id)).fetchone()
        if (flow is None or flow["used_at"] is not None or flow["expires_at"] < int(time.time()) or
                not _check_cookie(repo, cookie, flow["owner"], action_id)):
            raise PermissionError("Invalid or expired OAuth state/CSRF binding")
        row = db.execute("SELECT * FROM action_records WHERE id=? AND owner=?", (action_id, flow["owner"])).fetchone()
        if row is None or row["version"] != flow["action_version"]:
            raise PermissionError("OAuth Action was updated or removed")
        run = db.execute("SELECT r.status,r.state FROM runs r JOIN conversations c "
                         "ON c.id=r.conversation_id WHERE r.id=? AND c.owner=?",
                         (flow["run_id"], flow["owner"])).fetchone()
        if run is not None:
            payload = json.loads(run["state"]).get("pendingAction", {}).get("payload", {})
            if (run["status"] != "requires_action" or payload.get("type") != "action_oauth"
                    or payload.get("action_id") != action_id
                    or payload.get("tool_call_id") != flow["call_id"]
                    or payload.get("action_version") != row["version"]):
                raise PermissionError("OAuth generation was aborted or superseded")
        db.execute("UPDATE action_oauth_flows SET used_at=? WHERE state_hash=? AND used_at IS NULL",
                   (int(time.time()), key))
    return (flow["owner"], json.loads(row["metadata"]), repo._credentials(row), flow["redirect_uri"],
            flow["run_id"], flow["call_id"], row["version"])


async def _exchange(endpoint: str, body: dict[str, str], credentials: dict, method: str) -> dict:
    """POST form with pinned DNS, verified TLS SNI, no proxies and no redirects."""
    from urllib.parse import urlunsplit

    import httpx

    from .action_runtime import _resolve_address

    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Invalid OAuth token URL")
    address = await asyncio.to_thread(_resolve_address, parsed.hostname, parsed.port or 443)
    authority = ("[" + address + "]" if ":" in address else address)
    if parsed.port:
        authority += ":" + str(parsed.port)
    url = urlunsplit(("https", authority, parsed.path, parsed.query, ""))
    headers = {"Host": parsed.netloc, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    if method == "basic_auth_header":
        raw = (credentials["oauth_client_id"] + ":" + credentials["oauth_client_secret"]).encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    elif method == "default_post":
        body = {**body, "client_id": credentials["oauth_client_id"],
                "client_secret": credentials["oauth_client_secret"]}
    else:
        raise ValueError("Invalid OAuth token exchange method")
    try:
        async with (
            httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=20.0) as client,
            client.stream("POST", url, data=body, headers=headers,
                          extensions={"sni_hostname": parsed.hostname}) as response,
        ):
            if response.status_code != 200:
                raise PermissionError("OAuth token exchange rejected")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > _TOKEN_LIMIT:
                    raise ValueError("OAuth token response too large")
        result = json.loads(raw)
    except httpx.RequestError as exc:
        raise ConnectionError("OAuth token endpoint unreachable") from exc
    if not isinstance(result, dict) or not isinstance(result.get("access_token"), str) or not result["access_token"]:
        raise ValueError("Invalid OAuth access token response")
    if len(result["access_token"]) > 16_384:
        raise ValueError("OAuth token too large")
    refresh = result.get("refresh_token")
    if refresh is not None and (not isinstance(refresh, str) or len(refresh) > 16_384):
        raise ValueError("Invalid OAuth refresh token")
    for field in ("expires_in", "refresh_token_expires_in"):
        if field in result and result[field] is not None:
            try:
                seconds = int(result[field])
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid OAuth token expiry") from exc
            if seconds < 0 or seconds > 10 * 365 * 86400:
                raise ValueError("Invalid OAuth token expiry")
            result[field] = seconds
    return result


def _store_tokens(repo: ActionRepository, owner: str, action_id: str, token: dict, *, expected_version: int | None = None):
    now = int(time.time())
    with repo.database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT version FROM action_records WHERE id=? AND owner=?", (action_id, owner)).fetchone()
        if row is None or (expected_version is not None and row["version"] != expected_version):
            raise PermissionError("Action changed during OAuth token exchange")
        for kind, field, expires_field in (("access", "access_token", "expires_in"),
                                           ("refresh", "refresh_token", "refresh_token_expires_in")):
            if field not in token or not token[field]:
                continue
            sealed = repo._cipher().encrypt(token[field].encode())
            expires = now + int(token[expires_field]) if token.get(expires_field) is not None else None
            db.execute("INSERT INTO action_oauth_tokens(action_id,owner,kind,token,expires_at) VALUES(?,?,?,?,?) "
                       "ON CONFLICT(action_id,owner,kind) DO UPDATE SET token=excluded.token,expires_at=excluded.expires_at",
                       (action_id, owner, kind, sealed, expires))


async def exchange_code(repo: ActionRepository, owner: str, action_id: str,
                        metadata: dict, credentials: dict, redirect: str, code: str, *, expected_version: int):
    if not isinstance(code, str) or not 1 <= len(code) <= 2048:
        raise ValueError("Invalid OAuth code")
    auth = metadata["auth"]
    result = await _exchange(auth["client_url"], {"grant_type": "authorization_code", "code": code,
                                                   "redirect_uri": redirect}, credentials,
                             auth["token_exchange_method"])
    _store_tokens(repo, owner, action_id, result, expected_version=expected_version)
    return result


def _token(repo: ActionRepository, owner: str, action_id: str, kind: str) -> str | None:
    with repo.database.connect() as db:
        row = db.execute("SELECT token,expires_at FROM action_oauth_tokens WHERE action_id=? AND owner=? AND kind=?",
                         (action_id, owner, kind)).fetchone()
    if not row or (row["expires_at"] is not None and row["expires_at"] <= int(time.time()) + (5 if kind == "access" else 0)):
        return None
    return repo._cipher().decrypt(row["token"]).decode()


async def access_token(repo: ActionRepository, owner: str, action_id: str) -> str | None:
    """Reuse valid OAuth access token, serializing refreshes for rotating grants."""
    row = _action(repo, owner, action_id)
    token = _token(repo, owner, action_id, "access")
    if token:
        return token
    async with _refresh_lock(owner, action_id):
        # A different run may have refreshed while this invocation waited.
        token = _token(repo, owner, action_id, "access")
        if token:
            return token
        refresh = _token(repo, owner, action_id, "refresh")
        if not refresh:
            return None
        metadata, credentials = json.loads(row["metadata"]), repo._credentials(row)
        auth = metadata["auth"]
        try:
            result = await _exchange(auth["client_url"], {"grant_type": "refresh_token", "refresh_token": refresh},
                                     credentials, auth["token_exchange_method"])
            _store_tokens(repo, owner, action_id, result, expected_version=row["version"])
            return _token(repo, owner, action_id, "access")
        except (ValueError, PermissionError, ConnectionError, TimeoutError, OSError):
            # The original falls back to login after failed refresh. Do not
            # downgrade an OAuth request to unauthenticated API access.
            return None


async def await_login(repo: ActionRepository, owner: str, action_id: str, state: str) -> str:
    deadline = time.monotonic() + _FLOW_TTL
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    while time.monotonic() < deadline:
        with repo.database.connect() as db:
            flow = db.execute("SELECT expires_at FROM action_oauth_flows WHERE state_hash=? AND owner=? AND action_id=?",
                              (state_hash, owner, action_id)).fetchone()
        if flow is None or flow["expires_at"] < int(time.time()):
            raise PermissionError("OAuth authorization expired or revoked")
        token = _token(repo, owner, action_id, "access")
        if token:
            return token
        await asyncio.sleep(0.35)
    raise TimeoutError("OAuth sign-in timed out")
