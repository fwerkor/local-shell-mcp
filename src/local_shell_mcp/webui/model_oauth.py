"""Account authorization adapters for ordinary named model channels.

OAuth state and credentials never enter chat history or the browser's storage.
ChatGPT's OSS flow uses a loopback callback, not a hosted OAuth redirect.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .provider_profiles import _CHANNEL_PREFIX, _OWNER, _access, _validate, profile
from .routes import _body, _owner, _repo

TTL = 600
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
AUTH_URL = ISSUER + "/api/accounts/authorize"
JWKS_URL = ISSUER + "/.well-known/jwks.json"


class ReauthorizationRequired(ValueError):
    pass


async def _token(data: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(TOKEN_URL, data=data)
            if response.status_code in (400, 401):
                try:
                    error = response.json().get("error")
                except (ValueError, AttributeError):
                    error = None
                if error in {"invalid_grant", "invalid_client", "invalid_refresh_token", "token_expired", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}:
                    raise ReauthorizationRequired("ChatGPT authorization expired; sign in again")
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid token response")
            return result
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, ReauthorizationRequired):
            raise
        raise ValueError("ChatGPT token exchange failed") from None


def _credentials(result: dict, previous: dict) -> dict:
    scopes = result.get("scope", previous.get("scope", ""))
    if not isinstance(scopes, str) or not {"chatgpt.tokens.use.direct", "resource.invoke"} <= set(scopes.split()):
        raise ReauthorizationRequired("ChatGPT plan usage was not authorized")
    expires = result.get("expires_in")
    if type(expires) is not int or not 0 < expires <= 86400:
        raise ValueError("Invalid OAuth token expiry")
    if str(result.get("token_type", "")).lower() != "bearer":
        raise ValueError("Invalid OAuth token type")
    for key in ("access_token", "refresh_token"):
        token = result.get(key)
        if not isinstance(token, str) or not token or len(token) > 65536 or any(ord(c) <= 32 for c in token):
            raise ValueError("Invalid OAuth token response")
    earliest = result.get("earliest_refresh_at", 0)
    if type(earliest) not in (int, float):
        earliest = 0
    return {**previous, "scope": scopes, "earliest_refresh_at": earliest,
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"], "expires_at": time.time() + expires,
            **({"id_token": result["id_token"]} if isinstance(result.get("id_token"), str) else {})}


def _verify_id(token: str, client_id: str, nonce: str | None) -> dict:
    try:
        key = jwt.PyJWKClient(JWKS_URL, timeout=10).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id,
                            issuer=ISSUER, options={"require": ["exp", "sub", "iss", "aud"]})
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("Missing identity")
        if nonce is not None and claims.get("nonce") != nonce:
            raise ValueError("Invalid nonce")
        if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id:
            raise ValueError("Invalid authorized party")
        return claims
    except (jwt.PyJWTError, ValueError, TypeError):
        raise ValueError("Could not verify ChatGPT identity") from None


@dataclass(frozen=True)
class ChatGPTAuthorization:
    id: str = "chatgpt"
    label: str = "ChatGPT"
    protocol: str = "openai-responses"
    base_url: str = RESOURCE

    def authorize(self, redirect: str, host: str, state: str, nonce: str, verifier: str,
                  previous: dict) -> str:
        params = {"client_id": previous.get("client_id", "dynamic_agent_client"),
                  "ext_agent_host_id": host, "response_type": "code", "redirect_uri": redirect,
                  "scope": SCOPE, "resource": RESOURCE, "state": state, "nonce": nonce,
                  "code_challenge_method": "S256", "code_challenge":
                  base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
        if not previous:
            params["agent_name_hint"] = "Local Shell MCP"
        # Do not expose retained ID tokens in browser-facing authorization URLs.
        return AUTH_URL + "?" + urlencode(params)

    async def exchange(self, query: dict, redirect: str, nonce: str, verifier: str,
                       previous: dict) -> dict:
        if query.get("error"):
            raise ValueError("ChatGPT authorization was declined or failed")
        client_id = query.get("client_id") or previous.get("client_id")
        if not isinstance(client_id, str) or not client_id.startswith("oaiapp_") or (
                previous and client_id != previous["client_id"]):
            raise ValueError("Invalid ChatGPT client registration")
        code = query.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError("Missing authorization code")
        result = await _token({"grant_type": "authorization_code", "client_id": client_id,
                               "code": code, "code_verifier": verifier, "redirect_uri": redirect,
                               "resource": RESOURCE})
        credentials = _credentials(result, {"client_id": client_id})
        claims = await asyncio.to_thread(_verify_id, credentials.get("id_token", ""), client_id, nonce)
        if previous and previous.get("subject") and previous["subject"] != claims["sub"]:
            raise ValueError("Select the original ChatGPT account to reauthorize this channel")
        return {**credentials, "subject": claims["sub"]}

    async def refresh(self, credentials: dict) -> dict:
        result = await _token({"grant_type": "refresh_token", "client_id": credentials["client_id"],
                               "refresh_token": credentials["refresh_token"], "resource": RESOURCE})
        updated = _credentials(result, credentials)
        if "id_token" in result:
            claims = await asyncio.to_thread(_verify_id, updated["id_token"], credentials["client_id"], None)
            if claims["sub"] != credentials["subject"]:
                raise ReauthorizationRequired("ChatGPT authorization identity changed")
        return updated

    async def catalog(self, token: str) -> dict:
        from .model_discovery import _fetch_models
        return await _fetch_models(self.protocol, self.base_url, token, allow_empty=True, account=True)


# New account providers register an adapter, not a new inference protocol.
ADAPTERS = {"chatgpt": ChatGPTAuthorization()}


def adapter(method: str):
    if not isinstance(method, str) or method not in ADAPTERS:
        raise ValueError("Unsupported account authorization")
    return ADAPTERS[method]


def _cipher(database):
    from .actions import ActionRepository
    return ActionRepository(database)._cipher()


def seal(database, value: dict) -> str:
    return _cipher(database).encrypt(json.dumps(value).encode()).decode()


def unseal(database, value: dict) -> dict:
    from cryptography.fernet import InvalidToken
    try:
        return json.loads(_cipher(database).decrypt(value["oauth_credentials"].encode()))
    except (KeyError, ValueError, InvalidToken, TypeError):
        raise ReauthorizationRequired("Account credentials are unavailable; sign in again") from None


def check_binding(value: dict):
    auth = adapter(value["auth_method"])
    if (value["provider"], value["base_url"]) != (auth.protocol, auth.base_url):
        raise ValueError("Account credentials are bound to the original API endpoint")
    return auth


def host_id(database) -> str:
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM settings WHERE owner=? AND key='model.oauth.host'", (_OWNER,)).fetchone()
        if row:
            return json.loads(row[0])
        value = "urn:uuid:" + str(uuid.uuid4())
        db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?)",
                   (_OWNER, "model.oauth.host", json.dumps(value)))
        return value


async def access_token(database, name: str, identity: str, *, rejected: str | None = None) -> str:
    """Serialize rotating refreshes across Controller processes via SQLite lease."""
    lease = "model.oauth.refresh." + identity
    lock_id = secrets.token_hex(16)
    until = time.monotonic() + 45
    while True:
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT key,value FROM settings WHERE owner=? AND key LIKE ? AND json_extract(value,'$.oauth_id')=?",
                             (_OWNER, _CHANNEL_PREFIX + "%", identity)).fetchone()
            value = json.loads(row["value"]) if row else {}
            if value.get("oauth_id") != identity or value.get("oauth_error"):
                raise ReauthorizationRequired("Account authorization changed or expired; sign in again")
            auth = check_binding(value)
            credentials = unseal(database, value)
            token = credentials["access_token"]
            now = time.time()
            if credentials["expires_at"] > now + 120 and token != rejected:
                return token
            if credentials.get("earliest_refresh_at", 0) > now:
                if token != rejected and credentials["expires_at"] > now:
                    return token
                raise ValueError("Account credential cannot be refreshed yet; retry later")
            row = db.execute("SELECT value FROM settings WHERE owner=? AND key=?", (_OWNER, lease)).fetchone()
            if not row or json.loads(row[0])["until"] < time.time():
                db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                           "DO UPDATE SET value=excluded.value",
                           (_OWNER, lease, json.dumps({"owner": lock_id, "until": time.time() + 90})))
                break
        if time.monotonic() >= until:
            raise ValueError("Account credential refresh is busy; retry")
        await asyncio.sleep(.15)
    try:
        error = None
        try:
            updated = await auth.refresh(credentials)
            encrypted = seal(database, updated)
        except ReauthorizationRequired as exc:
            error = str(exc)
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT key,value FROM settings WHERE owner=? AND key LIKE ? AND json_extract(value,'$.oauth_id')=?",
                             (_OWNER, _CHANNEL_PREFIX + "%", identity)).fetchone()
            current = json.loads(row["value"]) if row else {}
            if current.get("oauth_id") != identity or current.get("oauth_credentials") != value["oauth_credentials"]:
                raise ValueError("Account channel changed during credential refresh")
            if error:
                current["oauth_error"] = error
            else:
                current["oauth_credentials"] = encrypted
            db.execute("UPDATE settings SET value=? WHERE owner=? AND key=?", (json.dumps(current), _OWNER, row["key"]))
        if error:
            raise ReauthorizationRequired(error)
        return updated["access_token"]
    finally:
        with database.connect() as db:
            db.execute("DELETE FROM settings WHERE owner=? AND key=? AND json_extract(value,'$.owner')=?",
                       (_OWNER, lease, lock_id))


async def catalog_for(database, value: dict, *, rejected: str | None = None) -> dict:
    auth = check_binding(value)
    token = await access_token(database, value["name"], value["oauth_id"], rejected=rejected)
    try:
        return await auth.catalog(token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise
    token = await access_token(database, value["name"], value["oauth_id"], rejected=token)
    return await auth.catalog(token)


async def save_account(database, method: str, name: str, credentials: dict, *, original: dict | None = None):
    from .model_discovery import _apply_catalog
    auth = adapter(method)
    if not isinstance(name, str) or not name:
        raise ValueError("Channel name is required")
    value = _validate({"name": name, "provider": auth.protocol, "base_url": auth.base_url,
                       "models": [], "auto_discover": True})
    catalog = await auth.catalog(credentials["access_token"])
    if not catalog["models"]:
        raise ValueError("No eligible models available for this account")
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT value FROM settings WHERE owner=? AND key LIKE ?",
                          (_OWNER, _CHANNEL_PREFIX + "%")).fetchall()
        existing = [json.loads(row[0]) for row in rows]
        current = next((v for v in existing if v["name"].lower() == name.lower()), None)
        if original:
            if not current or current.get("oauth_id") != original.get("oauth_id") or current["name"] != name:
                raise ValueError("Account channel changed during authorization")
            prior = unseal(database, current)
            if prior["client_id"] != credentials["client_id"] or prior["subject"] != credentials["subject"]:
                raise ValueError("Reauthorization must use the original account")
            value = current.copy()
        elif current or len(existing) >= 64:
            raise ValueError("Channel name already exists or channel limit reached")
        # Prevent duplicate rotating sessions for the same issued registration.
        for other in existing:
            if (other.get("auth_method") == method and other["name"] != name
                    and unseal(database, other)["client_id"] == credentials["client_id"]):
                raise ValueError("This account registration is already connected")
        value.update(auth_method=method, oauth_id=uuid.uuid4().hex,
                     oauth_credentials=seal(database, credentials), oauth_error=None, api_key="")
        if value["auto_discover"]:
            _apply_catalog(value, catalog, value.get("model_context_overrides") or {})
        db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                   "DO UPDATE SET value=excluded.value", (_OWNER, _CHANNEL_PREFIX + name, json.dumps(value)))


def callback_query(raw: str, redirect: str, state: str) -> dict:
    """Accept only the exact redirect for this one-time authorization attempt."""
    if not isinstance(raw, str) or not raw or len(raw) > 32768:
        raise ValueError("Invalid authorization callback")
    target, expected = urlsplit(raw.strip()), urlsplit(redirect)
    if (target.scheme, target.netloc, target.path) != (expected.scheme, expected.netloc, expected.path) or target.fragment:
        raise ValueError("Callback address does not match this authorization attempt")
    query = parse_qs(target.query, keep_blank_values=True, max_num_fields=20)
    if any(len(values) != 1 for values in query.values()) or not hmac.compare_digest(query.get("state", [""])[0].encode(), state.encode()):
        raise ValueError("Invalid callback state")
    if not query.get("error", [""])[0] and not query.get("code", [""])[0]:
        raise ValueError("Missing authorization code")
    return {key: values[0] for key, values in query.items()}


async def loopback(auth, host: str, previous: dict):
    """Return a URL, one-shot result future, and loopback listener, never raw tokens."""
    state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    future = asyncio.get_running_loop().create_future()

    async def callback(reader, writer):
        accepted = False
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            parts = line.decode("ascii").split()
            if len(parts) != 3 or parts[0] != "GET":
                raise ValueError("Invalid callback")
            if not parts[1].startswith("/") or parts[1].startswith("//"):
                raise ValueError("Invalid callback path")
            query = callback_query(redirect.removesuffix("/auth/callback") + parts[1], redirect, state)
            if future.done():
                raise ValueError("Duplicate callback")
            future.set_result(query)
            accepted = True
        except (ValueError, UnicodeError, TimeoutError, OSError):
            pass
        finally:
            body = b"Authorization received. Return to Local Shell MCP." if accepted else b"Invalid authorization callback."
            writer.write(b"HTTP/1.1 " + (b"200 OK" if accepted else b"400 Bad Request") +
                         b"\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nConnection: close\r\nContent-Length: " +
                         str(len(body)).encode() + b"\r\n\r\n" + body)
            try:
                await writer.drain()
            finally:
                writer.close()
    listener = await asyncio.start_server(callback, "127.0.0.1", 0, limit=32768)
    redirect = f"http://127.0.0.1:{listener.sockets[0].getsockname()[1]}/auth/callback"
    url = auth.authorize(redirect, host, state, nonce, verifier, previous)

    async def complete():
        try:
            query = await asyncio.wait_for(future, TTL)
            return await auth.exchange(query, redirect, nonce, verifier, previous)
        finally:
            listener.close()
            await listener.wait_closed()

    def submit(raw: str):
        if future.done():
            raise ValueError("Authorization callback has already been received")
        future.set_result(callback_query(raw, redirect, state))

    return url, complete, submit, listener.close


_FLOWS: dict = {}


async def oauth_start(request):
    _access(request)
    body = await _body(request)
    # A browser on a remote machine cannot reach the Controller loopback.
    # Use exactly the original redirect URI and PKCE even for a pasted callback.
    host = request.url.hostname or ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host.lower() == "localhost"
    manual = not local or body.get("manual") is True
    if not local and request.url.scheme != "https":
        from ..settings import get_settings
        configured = urlsplit(get_settings().public_base_url or "")
        if configured.scheme != "https":
            raise HTTPException(400, detail="Remote account authorization requires HTTPS")
    try:
        auth = adapter(body.get("method"))
        name = body.get("name")
        _validate({"name": name, "provider": auth.protocol, "base_url": auth.base_url,
                   "models": [], "auto_discover": True})
        if not name:
            raise ValueError("Channel name is required")
        database = _repo().database
        previous = {}
        original = None
        if body.get("reauthorize") is True:
            original = profile(name)
            if original.get("auth_method") != auth.id:
                raise ValueError("Invalid account channel")
            previous = unseal(database, original)
        else:
            try:
                profile(name)
            except ValueError:
                pass
            else:
                raise ValueError("Channel name already exists")
        for fid, flow in list(_FLOWS.items()):
            if flow["expires"] < time.monotonic():
                flow["task"].cancel()
                del _FLOWS[fid]
        if any(flow.get("channel") == name.casefold() and not flow["task"].done() for flow in _FLOWS.values()):
            raise ValueError("An authorization for this channel is already pending")
        if len(_FLOWS) >= 16:
            raise ValueError("Too many pending account authorizations")
        url, complete, submit, close = await loopback(auth, host_id(database), previous)
        flow_id = secrets.token_urlsafe(32)

        async def finish():
            try:
                credentials = await complete()
                await save_account(database, auth.id, name, credentials, original=original)
                return {"status": "complete", "name": name}
            except TimeoutError:
                return {"status": "error", "error": "Authorization expired; try again"}
            except Exception:
                return {"status": "error", "error": "Authorization or model discovery failed; try again"}

        task = asyncio.create_task(finish())
        task.add_done_callback(lambda _: close())
        _FLOWS[flow_id] = {"owner": _owner(request), "expires": time.monotonic() + TTL + 60,
                           "task": task, "submit": submit, "channel": name.casefold()}
        return JSONResponse({"flow": flow_id, "authorization_url": url, "manual": manual}, headers={"Cache-Control": "no-store"})
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, detail=str(exc)) from None


async def oauth_status(request):
    _access(request)
    flow_id = request.query_params.get("flow")
    flow = _FLOWS.get(flow_id)
    if not flow or flow["owner"] != _owner(request):
        raise HTTPException(404, detail="Authorization attempt not found")
    task = flow["task"]
    if flow["expires"] <= time.monotonic():
        task.cancel()
        del _FLOWS[flow_id]
        raise HTTPException(410, detail="Authorization expired; start again")
    if request.method == "POST":
        if task.done() or not flow["submit"]:
            raise HTTPException(409, detail="Authorization is no longer awaiting a manual callback")
        body = await _body(request)
        try:
            flow["submit"](body.get("callback_url"))
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from None
        return JSONResponse({"status": "pending"}, headers={"Cache-Control": "no-store"})
    if request.method == "DELETE":
        task.cancel()
        del _FLOWS[flow_id]
        return JSONResponse({"status": "cancelled"}, headers={"Cache-Control": "no-store"})
    result = task.result() if task.done() and not task.cancelled() else {"status": "pending"}
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
