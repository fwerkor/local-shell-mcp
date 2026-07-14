from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from contextlib import suppress
from pathlib import Path

from starlette.requests import HTTPConnection

from .settings import get_settings

UI_LOCAL_TOKEN_HEADER = "x-local-shell-mcp-ui-token"
UI_LOCAL_TOKEN_ENV = "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN"


def _token_path() -> Path:
    return get_settings().state_dir / "ui" / "local-token"


def _read_token(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if len(value) >= 32 else None


def get_or_create_ui_local_token() -> str:
    """Return the transparent local credential used by native and web-spawned TUIs.

    Human users never enter this token. It prevents a reverse proxy connected over loopback
    from accidentally receiving the native TUI's authentication bypass.
    """

    inherited = os.getenv(UI_LOCAL_TOKEN_ENV, "").strip()
    if len(inherited) >= 32:
        return inherited

    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        existing = _read_token(path)
        if existing:
            return existing

        token = secrets.token_urlsafe(48)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            try:
                path.lstat()
            except FileNotFoundError:
                raise RuntimeError(
                    f"Unable to create UI local token: {path}"
                ) from exc
            except OSError:
                pass

            existing = _read_token(path)
            if existing:
                return existing
            try:
                path.unlink()
            except OSError as replace_exc:
                raise RuntimeError(
                    f"Unable to replace invalid UI local token path: {path}"
                ) from replace_exc
            continue

        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.write("\n")
        with suppress(OSError):
            path.chmod(0o600)
        return token

    existing = _read_token(path)
    if existing:
        return existing
    raise RuntimeError(f"Unable to initialize UI local token: {path}")


def has_valid_ui_local_token(connection: HTTPConnection) -> bool:
    submitted = connection.headers.get(UI_LOCAL_TOKEN_HEADER, "").strip()
    if not submitted:
        return False
    expected = get_or_create_ui_local_token()
    return hmac.compare_digest(submitted, expected)


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
