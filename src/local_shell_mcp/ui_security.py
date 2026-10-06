from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

UI_LOCAL_TOKEN_HEADER = "x-local-shell-mcp-ui-token"
UI_LOCAL_TOKEN_ENV = "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN"
UI_LOCAL_TOKEN_FD_ENV = "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN_FD"
CLI_LOCAL_TOKEN_HEADER = "x-local-shell-mcp-cli-token"
CLI_LOCAL_TOKEN_ENV = "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN"
CLI_LOCAL_TOKEN_SHA256_ENV = "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256"


@dataclass(frozen=True)
class UiLocalTokenContext:
    email: str | None
    subject: str | None
    scopes: tuple[str, ...]


_UI_LOCAL_TOKENS: dict[str, UiLocalTokenContext] = {}
_UI_LOCAL_TOKEN_LOCK = threading.Lock()


def _ui_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_ui_local_token(
    *,
    email: str | None,
    subject: str | None,
    scopes: tuple[str, ...] | list[str] | set[str],
) -> str:
    """Issue one revocable process-local credential for a controller-spawned TUI.

    Only a digest and the caller's original identity/scopes remain in controller memory.
    The raw token is never persisted to the filesystem or state backend.
    """

    token = secrets.token_urlsafe(48)
    context = UiLocalTokenContext(
        email=email,
        subject=subject,
        scopes=tuple(sorted({str(scope) for scope in scopes if str(scope)})),
    )
    with _UI_LOCAL_TOKEN_LOCK:
        _UI_LOCAL_TOKENS[_ui_token_digest(token)] = context
    return token


def revoke_ui_local_token(token: str | None) -> None:
    if not token:
        return
    with _UI_LOCAL_TOKEN_LOCK:
        _UI_LOCAL_TOKENS.pop(_ui_token_digest(token), None)


def ui_local_token_context(connection: HTTPConnection) -> UiLocalTokenContext | None:
    submitted = connection.headers.get(UI_LOCAL_TOKEN_HEADER, "").strip()
    if not submitted:
        return None
    with _UI_LOCAL_TOKEN_LOCK:
        return _UI_LOCAL_TOKENS.get(_ui_token_digest(submitted))


def has_valid_ui_local_token(connection: HTTPConnection) -> bool:
    return ui_local_token_context(connection) is not None


def cli_local_token_verifier_configured() -> bool:
    return bool(os.getenv(CLI_LOCAL_TOKEN_SHA256_ENV, "").strip())


def cli_local_token_verifier() -> str | None:
    expected_digest = os.getenv(CLI_LOCAL_TOKEN_SHA256_ENV, "").strip().lower()
    if len(expected_digest) != 64:
        return None
    try:
        bytes.fromhex(expected_digest)
    except ValueError:
        return None
    return expected_digest


def has_valid_cli_local_token(connection: HTTPConnection) -> bool:
    submitted = connection.headers.get(CLI_LOCAL_TOKEN_HEADER, "").strip()
    expected_digest = cli_local_token_verifier()
    if not submitted or expected_digest is None:
        return False
    digest = hashlib.sha256(submitted.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected_digest)


def is_loopback_target(connection: HTTPConnection) -> bool:
    """Return whether the request targets a loopback Host value.

    This survives Docker's published-port bridge, where the transport peer may be
    the bridge gateway instead of 127.0.0.1. Public tunnel requests retain their
    public Host value and therefore do not receive the host-CLI bypass.
    """

    host_header = connection.headers.get("host", "").strip()
    if not host_header:
        return False
    try:
        host = urlsplit(f"//{host_header}").hostname or ""
    except ValueError:
        return False
    if host.lower() == "localhost":
        return True
    candidate = host.split("%", 1)[0].strip("[]")
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def is_loopback_connection(connection: HTTPConnection) -> bool:
    """Return whether the transport peer itself is a loopback address.

    Forwarded headers are intentionally ignored. A reverse proxy connected over loopback
    must not inherit the native TUI bypass on behalf of a remote browser.
    """

    host = connection.client.host if connection.client else ""
    if host.lower() == "localhost":
        return True
    candidate = host.split("%", 1)[0].strip("[]")
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False
