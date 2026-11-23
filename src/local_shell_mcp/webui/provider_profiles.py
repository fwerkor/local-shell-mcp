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
    if normalized in {"openai-compatible", "ollama", "azureopenai", "custom"}:
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
            "models": value["models"], "configured": configured(value),
            "include_usage": value.get("include_usage") is True or (
                value["provider"] == "openai" and parsed.hostname == "api.openai.com")}


def all_profiles() -> list[dict]:
    return [profile(kind) for kind in _DEFAULTS] + _stored_channels()


def public_profiles() -> dict:
    """Expose editable entries without presenting unsaved provider defaults as channels."""
    entries = []
    for kind in _DEFAULTS:
        value = profile(kind)
        saved = _repo().setting(_OWNER, _PREFIX + kind)
        env_keys = {
            "openai": ("LOCAL_SHELL_MCP_MODEL_BASE_URL", "LOCAL_SHELL_MCP_MODEL",
                       "LOCAL_SHELL_MCP_MODEL_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_KEY"),
            "anthropic": ("ANTHROPIC_API_KEY",),
            "google": ("GOOGLE_KEY", "GOOGLE_API_KEY"),
        }[kind]
        source = "saved" if isinstance(saved, dict) else (
            "environment" if any(os.getenv(key) for key in env_keys) else "default")
        entries.append({**_redact(value), "source": source})
    entries.extend({**_redact(value), "source": "named"} for value in _stored_channels())
    return {"providers": entries}


def _validate(body: dict) -> dict:
    from .providers import _require_https_or_loopback

    kind = body.get("provider")
    if not isinstance(kind, str) or kind not in _DEFAULTS:
        raise ValueError("Unsupported model provider")
    name = body.get("name")
    if name is not None and (not isinstance(name, str) or not _NAME.fullmatch(name) or name != name.strip() or (name.lower() in _RESERVED or name.lower().endswith("assistants"))):
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
    include_usage = body.get('include_usage')
    if include_usage is not None and type(include_usage) is not bool:
        raise ValueError('include_usage must be a boolean')
    return {**({"name": name} if name is not None else {}), "provider": kind, "base_url": base,
            "models": models, "api_key": (key.strip() or None) if key else None,
            'include_usage': include_usage}


def _access(request):
    from ..auth import _is_cross_origin_request, require_scopes
    from ..settings import get_settings

    _owner(request)
    if get_settings().auth_mode == "none" and _is_cross_origin_request(request):
        raise HTTPException(401, detail="Cross-origin Controller settings access is not allowed")
    if get_settings().auth_mode != "none":
        require_scopes(request.state.principal, ["admin:config"])


def _is_referenced(db, name: str) -> bool:
    # Existing Agents, revisions, conversations and persisted runs must not be
    # orphaned by destructive operations or a rename.
    return any((
        db.execute("SELECT 1 FROM agents WHERE json_extract(config,'$.provider')=? LIMIT 1", (name,)).fetchone(),
        db.execute("SELECT 1 FROM runs WHERE json_extract(state,'$.provider')=? LIMIT 1", (name,)).fetchone(),
        db.execute("SELECT 1 FROM conversations WHERE endpoint=? LIMIT 1", (name,)).fetchone(),
        db.execute("SELECT 1 FROM agent_versions WHERE json_extract(snapshot,'$.provider')=? LIMIT 1", (name,)).fetchone(),
    ))


async def provider_profiles(request):
    _access(request)
    if request.method == "DELETE":
        name = request.query_params.get("name")
        legacy = request.query_params.get("legacy_provider")
        if (name is None) == (legacy is None):
            raise HTTPException(400, detail="Specify a named or saved legacy channel")
        if legacy is not None:
            if legacy not in _DEFAULTS:
                raise HTTPException(400, detail="Invalid legacy channel")
            key = _PREFIX + legacy
            aliases = ("openai", "openAI", "openai-compatible", "custom", "ollama",
                       "azureopenai") if legacy == "openai" else (
                           ("google", "gemini") if legacy == "google" else ("anthropic",))
        else:
            if not isinstance(name, str) or not _NAME.fullmatch(name) or name != name.strip() or name.lower() in _RESERVED:
                raise HTTPException(400, detail="Invalid named channel")
            key = _CHANNEL_PREFIX + name
            aliases = (name,)
        with _repo().database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if any(_is_referenced(db, alias) for alias in aliases):
                raise HTTPException(409, detail="Channel is referenced by saved conversations or Agents")
            db.execute("DELETE FROM settings WHERE owner=? AND key=?", (_OWNER, key))
    elif request.method == "PUT":
        body = await _body(request)
        try:
            value = _validate(body)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        old_name = body.get("previous_name")
        if old_name is not None and (
            not isinstance(old_name, str) or not _NAME.fullmatch(old_name) or
            old_name != old_name.strip() or old_name.lower() in _RESERVED or
            "name" not in value
        ):
            raise HTTPException(400, detail="Invalid previous channel name")
        name = value.get("name")
        renaming = old_name is not None and old_name != name
        key = (_CHANNEL_PREFIX + name) if name is not None else (_PREFIX + value["provider"])
        with _repo().database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if name is not None:
                rows = db.execute("SELECT value FROM settings WHERE owner=? AND key LIKE ?",
                                  (_OWNER, _CHANNEL_PREFIX + "%")).fetchall()
                existing = [json.loads(row[0]) for row in rows]
                if any(ch["name"].lower() == name.lower() and ch["name"] not in {name, old_name} for ch in existing):
                    raise HTTPException(409, detail="Channel name already exists")
                if len(existing) >= 64 and not (old_name or any(ch["name"] == name for ch in existing)):
                    raise HTTPException(400, detail="At most 64 named channels are supported")
            if renaming:
                original = db.execute("SELECT value FROM settings WHERE owner=? AND key=?",
                                      (_OWNER, _CHANNEL_PREFIX + old_name)).fetchone()
                if not original:
                    raise HTTPException(404, detail="Original channel no longer exists")
                if db.execute("SELECT 1 FROM settings WHERE owner=? AND key=?", (_OWNER, key)).fetchone():
                    raise HTTPException(409, detail="Channel name already exists")
                if _is_referenced(db, old_name):
                    raise HTTPException(409, detail="Channel is referenced by saved conversations or Agents; update those references before renaming")
                previous = json.loads(original[0])
            else:
                row = db.execute("SELECT value FROM settings WHERE owner=? AND key=?", (_OWNER, key)).fetchone()
                previous = json.loads(row[0]) if row else (
                    _default_profile(value["provider"]) if name is None else {})
            if previous and previous.get("provider") != value["provider"]:
                raise HTTPException(409, detail="Existing channel provider type cannot be changed")
            if value["api_key"] is None:
                value["api_key"] = previous.get("api_key", "")
            if value["include_usage"] is None:
                value["include_usage"] = previous.get("include_usage", False)
            db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                       "DO UPDATE SET value=excluded.value", (_OWNER, key, json.dumps(value)))
            if renaming:
                db.execute("DELETE FROM settings WHERE owner=? AND key=?", (_OWNER, _CHANNEL_PREFIX + old_name))
    return JSONResponse(public_profiles(), headers={"Cache-Control": "no-store"})
