"""Short-lived identity handoff to the optional, separately isolated LibreChat runtime."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import jwt

TICKET_AUDIENCE = "lsm-embedded-librechat"
TICKET_ISSUER = "local-shell-mcp"
TICKET_TTL_S = 60


def bridge_url() -> str | None:
    configured = os.environ.get("LOCAL_SHELL_MCP_LIBRECHAT_URL", "").strip().rstrip("/")
    if not configured:
        return None
    url = urlsplit(configured)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("LibreChat URL must be an absolute HTTP(S) origin without credentials")
    if url.scheme != "https" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("LibreChat must use HTTPS except on localhost")
    return configured


def bridge_secret() -> str:
    secret = os.environ.get("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("LibreChat requires a shared bridge secret of at least 32 bytes")
    return secret


def issue_chat_ticket(
    subject: str, *, scopes: str = "", auth_mode: str = "oauth",
    grant_expires_at: int | None = None,
) -> dict[str, str]:
    url = bridge_url()
    if not url:
        raise ValueError("LibreChat is not configured")
    secret = bridge_secret()
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 1024:
        raise PermissionError("A stable authenticated LSM identity is required")
    now = int(time.time())
    if auth_mode != "none":
        grant_expires_at = min(now + 3600, int(grant_expires_at or now + 3600))
        if grant_expires_at <= now:
            raise PermissionError("The LSM authentication token has expired")
    token = jwt.encode(
        {
            "iss": TICKET_ISSUER,
            "aud": TICKET_AUDIENCE,
            "sub": subject,
            "scope": scopes,
            "auth_mode": "none" if auth_mode == "none" else "oauth",
            "grant_until": grant_expires_at,
            "iat": now,
            "nbf": now,
            "exp": now + TICKET_TTL_S,
            "jti": secrets.token_urlsafe(24),
        },
        secret,
        algorithm="HS256",
    )
    return {"url": url, "ticket": token}


def read_chat_ticket(ticket: str) -> dict:
    return jwt.decode(
        ticket, bridge_secret(), algorithms=["HS256"],
        audience=TICKET_AUDIENCE, issuer=TICKET_ISSUER,
        options={"require": ["sub", "iat", "exp", "nbf", "jti"]},
    )


def is_bridge_service(request) -> bool:
    expected = os.environ.get("LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET", "")
    bearer = request.headers.get("authorization", "")
    return (
        len(expected.encode("utf-8")) >= 32
        and bearer.startswith("Bearer ")
        and hmac.compare_digest(bearer[7:], expected)
    )


def _identity_key(librechat_id: str) -> str:
    if not isinstance(librechat_id, str) or not re.fullmatch(r"[0-9a-f]{24}", librechat_id):
        raise ValueError("Invalid LibreChat user identifier")
    return f"librechat-bridge/identities/{librechat_id}.json"


def register_identity(librechat_id: str, ticket: str) -> dict:
    from .state_store import get_state_store

    claims = read_chat_ticket(ticket)
    key = _identity_key(librechat_id)
    entry = {
        "subject": claims["sub"],
        "scopes": claims.get("scope", ""),
        "auth_mode": claims.get("auth_mode", "oauth"),
        "grant_until": claims.get("grant_until"),
    }
    store = get_state_store()
    with store.lock(key):
        # The one internal LibreChat account follows the active LSM login.
        # A valid signed ticket may replace its prior subject/grant.
        store.write_bytes(key, json.dumps(entry, separators=(",", ":")).encode("utf-8"))
    return entry


def principal_for_chat_user(librechat_id: str) -> dict:
    from .state_store import get_state_store

    value = get_state_store().read_bytes(_identity_key(librechat_id))
    if value is None:
        raise PermissionError("LibreChat identity has not been registered")
    result = json.loads(value)
    if not isinstance(result.get("subject"), str):
        raise PermissionError("Invalid LibreChat identity")
    if result.get("auth_mode") != "none" and (
        not isinstance(result.get("grant_until"), int)
        or int(time.time()) >= result["grant_until"]
    ):
        raise PermissionError("LSM authorization has expired; reopen Chat from LSM")
    return result


MAX_CHAT_UPLOAD_BYTES = 32 * 1024 * 1024


def local_upload_path(subject: str, filename: str, workspace: Path) -> Path:
    if not subject or len(subject) > 1024:
        raise PermissionError("An authenticated user is required")
    if not isinstance(filename, str) or not filename or len(filename) > 200:
        raise ValueError("Invalid upload filename")
    name = filename.replace("\\", "/").split("/")[-1]
    if name in {"", ".", ".."} or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid upload filename")
    # The path is automatically allocated. The caller cannot choose an arbitrary
    # location on the local machine, and the filename can never escape its directory.
    owner = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
    root = workspace.resolve()
    parent = root / ".lsm-chat-uploads" / owner
    if root not in parent.resolve().parents:
        raise PermissionError("Unsafe upload destination")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return parent / f"{uuid.uuid4().hex}-{name}"


def _chat_policy_key(librechat_id: str, conversation_id: str) -> str:
    _identity_key(librechat_id)
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", conversation_id):
        raise ValueError("Invalid chat conversation identifier")
    return f"librechat-bridge/policies/{librechat_id}/{conversation_id}.json"


EXTERNAL_MCP_CALL_TOOLS = frozenset({
    "mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call",
})


def set_chat_tool_policy(
    librechat_id: str, conversation_id: str, lsm_enabled: bool,
    mcp_enabled: bool = True,
) -> None:
    from .state_store import get_state_store

    if type(lsm_enabled) is not bool or type(mcp_enabled) is not bool:
        raise ValueError("Invalid chat tool permission")
    principal_for_chat_user(librechat_id)
    key = _chat_policy_key(librechat_id, conversation_id)
    store = get_state_store()
    with store.lock(key):
        store.write_bytes(
            key, json.dumps({"lsm": lsm_enabled, "mcp": mcp_enabled}, separators=(",", ":")).encode("utf-8")
        )


def may_chat_call_lsm(
    librechat_id: str, conversation_id: str, tool_name: str | None = None,
) -> bool:
    from .state_store import get_state_store

    principal_for_chat_user(librechat_id)
    if conversation_id == "new":
        return True
    value = get_state_store().read_bytes(_chat_policy_key(librechat_id, conversation_id))
    policy = json.loads(value) if value is not None else {}
    if tool_name in EXTERNAL_MCP_CALL_TOOLS:
        return policy.get("mcp", True) is True
    return policy.get("lsm", True) is True
