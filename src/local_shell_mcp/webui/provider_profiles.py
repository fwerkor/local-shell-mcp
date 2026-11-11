"""Controller-owned, independently keyed model channels in shared SQLite.

Legacy ``model.provider.<kind>`` settings remain authoritative for the three
built-in channels. Named channels use ``model.channel.<name>``. No model API
credentials are returned from the public catalog, endpoint selector or errors.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit, urlunsplit

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .routes import _body, _owner, _repo

_OWNER = "__lsm_controller__"
_PREFIX = "model.provider."
_CHANNEL_PREFIX = "model.channel."
_DEFAULTS = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-sonnet-4-6"),
    "google": ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash"),
}
# LibreChat endpointSchema.name must not collide with EModelEndpoint values.
_RESERVED = frozenset({"agents", "openai", "anthropic", "google", "gemini", "custom", "azureopenai",
                       "assistants", "azureassistants", "bedrock", "gptplugins", "chatgptbrowser", "ollama", "openai-compatible"})
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 _.-]{0,63}$")


def _stored_channels() -> list[dict]:
    with _repo().database.connect() as db:
        rows = db.execute("SELECT value FROM settings WHERE owner=? AND key LIKE ? ORDER BY key",
                          (_OWNER, _CHANNEL_PREFIX + "%")).fetchall()
    return [json.loads(row[0]) for row in rows]


def _default_profile(provider: str) -> dict:
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


def profile(channel: str) -> dict:
    """Resolve a built-in alias or a named channel without ever silently rerouting."""
    if not isinstance(channel, str):
        raise ValueError("Invalid model channel")
    normalized = channel.strip().lower()
    if normalized in {"openai-compatible", "ollama", "azureopenai"}:
        normalized = "openai"
    if normalized == "gemini":
        normalized = "google"
    if normalized in _DEFAULTS:
        saved = _repo().setting(_OWNER, _PREFIX + normalized)
        return saved if isinstance(saved, dict) else _default_profile(normalized)
    saved = _repo().setting(_OWNER, _CHANNEL_PREFIX + channel)
    if isinstance(saved, dict) and saved.get("name") == channel:
        return saved
    raise ValueError("Unsupported provider or Unknown model channel")


def configured(value: dict) -> bool:
    return bool(value["models"] and (value.get("api_key") or (
        value["provider"] == "openai" and urlsplit(value["base_url"]).hostname in {"127.0.0.1", "localhost", "::1"})))


def _redact(value: dict) -> dict:
    parsed = urlsplit(value["base_url"])
    return {"provider": value["provider"],
            **({"name": value["name"]} if "name" in value else {}),
            "base_url": urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", "")),
            "models": value["models"], "configured": configured(value)}


def all_profiles() -> list[dict]:
    return [profile(kind) for kind in _DEFAULTS] + _stored_channels()


def public_profiles() -> dict:
    return {"providers": [_redact(value) for value in all_profiles()]}


def _validate(body: dict) -> dict:
    from .providers import _require_https_or_loopback

    kind = body.get("provider")
    if not isinstance(kind, str) or kind not in _DEFAULTS:
        raise ValueError("Unsupported model provider")
    name = body.get("name")
    if name is not None and (not isinstance(name, str) or not _NAME.fullmatch(name) or name != name.strip() or name.lower() in _RESERVED):
        raise ValueError("Invalid or reserved channel name")
    base = body.get("base_url")
    if not isinstance(base, str) or not base.strip() or len(base) > 2048:
        raise ValueError("A model provider base URL is required")
    base = base.strip().rstrip("/")
    _require_https_or_loopback(base)
    parsed = urlsplit(base)
    try:
        invalid_port = parsed.port is not None and parsed.port == 0
    except ValueError as exc:
        raise ValueError("Invalid model provider base URL") from exc
    if any(ord(char) <= 32 for char in base) or invalid_port:
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
    return {**({"name": name} if name is not None else {}), "provider": kind, "base_url": base,
            "models": models, "api_key": (key.strip() or None) if key else None}


def _access(request):
    from ..auth import _is_cross_origin_request, require_scopes
    from ..settings import get_settings

    _owner(request)
    if get_settings().auth_mode == "none" and _is_cross_origin_request(request):
        raise HTTPException(401, detail="Cross-origin Controller settings access is not allowed")
    if get_settings().auth_mode != "none":
        require_scopes(request.state.principal, ["admin:config"])


async def provider_profiles(request):
    _access(request)
    if request.method == "DELETE":
        name = request.query_params.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name != name.strip() or name.lower() in _RESERVED:
            raise HTTPException(400, detail="Invalid named channel")
        # Refuse to silently orphan saved Agents or conversations. Direct runs
        # already in progress also retain a persisted provider identifier.
        with _repo().database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM agents WHERE json_extract(config,'$.provider')=? LIMIT 1", (name,)).fetchone() or db.execute(
                "SELECT 1 FROM runs WHERE json_extract(state,'$.provider')=? LIMIT 1", (name,)
            ).fetchone() or db.execute("SELECT 1 FROM conversations WHERE endpoint=? LIMIT 1", (name,)).fetchone():
                raise HTTPException(409, detail="Channel is referenced by saved conversations or Agents")
            db.execute("DELETE FROM settings WHERE owner=? AND key=?", (_OWNER, _CHANNEL_PREFIX + name))
    elif request.method == "PUT":
        try:
            value = _validate(await _body(request))
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        key = (_CHANNEL_PREFIX + value["name"]) if "name" in value else (_PREFIX + value["provider"])
        # Atomic read/merge/write preserves omitted keys across concurrent edits.
        with _repo().database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if "name" in value:
                channels = db.execute("SELECT value FROM settings WHERE owner=? AND key LIKE ?",
                                      (_OWNER, _CHANNEL_PREFIX + "%")).fetchall()
                existing = [json.loads(row[0]) for row in channels]
                if any(ch["name"].lower() == value["name"].lower() and ch["name"] != value["name"] for ch in existing):
                    raise HTTPException(409, detail="Channel name already exists")
                if len(existing) >= 64 and not any(ch["name"] == value["name"] for ch in existing):
                    raise HTTPException(400, detail="At most 64 named channels are supported")
            row = db.execute("SELECT value FROM settings WHERE owner=? AND key=?", (_OWNER, key)).fetchone()
            previous = json.loads(row[0]) if row else (
                _default_profile(value["provider"]) if "name" not in value else {})
            if row and previous.get("provider") != value["provider"]:
                raise HTTPException(409, detail="Existing channel provider type cannot be changed")
            if value["api_key"] is None:
                value["api_key"] = previous.get("api_key", "")
            db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                       "DO UPDATE SET value=excluded.value", (_OWNER, key, json.dumps(value)))
    return JSONResponse(public_profiles(), headers={"Cache-Control": "no-store"})
