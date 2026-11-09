"""Controller-owned model credentials, stored alongside the unified SQLite state.

Profiles are server settings, not Agent resources or client credentials. Public
catalogs expose model identifiers; only the existing admin scope can edit them.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlsplit, urlunsplit

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .routes import _body, _owner, _repo

_OWNER = "__lsm_controller__"
_PREFIX = "model.provider."
_DEFAULTS = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-sonnet-4-6"),
    "google": ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash"),
}


def profile(provider: str) -> dict:
    """Return a saved profile, or the existing environment configuration."""
    saved = _repo().setting(_OWNER, _PREFIX + provider)
    if isinstance(saved, dict):
        return saved
    base, model = _DEFAULTS[provider]
    if provider == "openai":
        base = os.getenv("LOCAL_SHELL_MCP_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL") or base
        model = os.getenv("LOCAL_SHELL_MCP_MODEL") or model
        key = os.getenv("LOCAL_SHELL_MCP_MODEL_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
    else:
        key = os.getenv("GOOGLE_KEY") or os.getenv("GOOGLE_API_KEY", "")
    return {"provider": provider, "base_url": base, "models": [model], "api_key": key}


def configured(value: dict) -> bool:
    return bool(value["models"] and (value.get("api_key") or (
        value["provider"] == "openai" and urlsplit(value["base_url"]).hostname in {"127.0.0.1", "localhost", "::1"})))


def public_profiles() -> dict:
    return {"providers": [{"provider": kind, "base_url": urlunsplit((urlsplit(value["base_url"]).scheme,
                                                     urlsplit(value["base_url"]).netloc.rsplit("@", 1)[-1],
                                                     urlsplit(value["base_url"]).path, "", "")),
                            "models": value["models"], "configured": configured(value)}
                           for kind in _DEFAULTS for value in [profile(kind)]]}


def _validate(body: dict) -> dict:
    from .providers import _require_https_or_loopback

    kind = body.get("provider")
    if not isinstance(kind, str) or kind not in _DEFAULTS:
        raise ValueError("Unsupported model provider")
    base = body.get("base_url")
    if not isinstance(base, str) or not base.strip() or len(base) > 2048:
        raise ValueError("A model provider base URL is required")
    base = base.strip().rstrip("/")
    _require_https_or_loopback(base)
    parsed = urlsplit(base)
    if any(ord(char) <= 32 for char in base) or (parsed.port is not None and parsed.port == 0):
        raise ValueError("Invalid model provider base URL")
    if parsed.query:
        raise ValueError("A model provider base URL must not contain a query")
    models = body.get("models")
    if not isinstance(models, list) or not models or len(models) > 128:
        raise ValueError("Provide between 1 and 128 model identifiers")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 200 or
           any(ord(char) < 32 for char in item) for item in models):
        raise ValueError("Invalid model identifier")
    models = list(dict.fromkeys(item.strip() for item in models))
    if kind == "google" and any(any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in item) for item in models):
        raise ValueError("Unsupported Gemini model identifier")
    key = body.get("api_key")
    if key is not None and (not isinstance(key, str) or len(key) > 16384 or any(ord(char) < 32 for char in key)):
        raise ValueError("Invalid model API key")
    return {"provider": kind, "base_url": base, "models": models, "api_key": (key.strip() or None) if key else None}


async def provider_profiles(request):
    from ..auth import require_scopes
    from ..settings import get_settings

    _owner(request)
    if get_settings().auth_mode != "none":
        require_scopes(request.state.principal, ["admin:config"])
    if request.method == "PUT":
        try:
            value = _validate(await _body(request))
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        # Keep the read/merge/write in one transaction, so simultaneous updates
        # cannot replace a newly saved key with an older credential.
        repo = _repo()
        fallback = profile(value["provider"])
        with repo.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM settings WHERE owner=? AND key=?",
                             (_OWNER, _PREFIX + value["provider"])).fetchone()
            previous = json.loads(row[0]) if row else fallback
            if value["api_key"] is None:
                value["api_key"] = previous.get("api_key", "")
            db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                       "DO UPDATE SET value=excluded.value",
                       (_OWNER, _PREFIX + value["provider"], json.dumps(value)))
    return JSONResponse(public_profiles(), headers={"Cache-Control": "no-store"})
