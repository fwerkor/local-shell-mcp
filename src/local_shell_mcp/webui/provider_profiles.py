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
from .sampling import validate_sampling

_OWNER = "__lsm_controller__"
_PREFIX = "model.provider."
_CHANNEL_PREFIX = "model.channel."
_DEFAULTS = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-sonnet-4-6"),
    "google": ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash"),
}
_PROTOCOLS = frozenset(_DEFAULTS) | {"openai-responses"}
# Built-in provider aliases resolve case-insensitively via profile(). Use the
# same aliases when checking references before resetting saved credentials.
_LEGACY_ALIASES = {
    "openai": ("openai", "openai-compatible", "ollama", "azureopenai", "custom"),
    "anthropic": ("anthropic",),
    "google": ("google", "gemini"),
}
# LibreChat endpointSchema.name must not collide with EModelEndpoint values.
_RESERVED = frozenset({"agents", "openai", "anthropic", "google", "gemini", "custom", "azureopenai",
                       "assistants", "azureassistants", "bedrock", "gptplugins", "chatgptbrowser", "ollama", "openai-compatible"})
# Keep channel IDs path-safe while allowing Unicode letters (including CJK).
# The same rule is used for creation, renaming and deletion.
_NAME = re.compile(r"^[^\W\d_][\w .-]{0,63}$")


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


def profile(channel: str, *, effective: bool = True) -> dict:
    """Resolve a built-in alias or a named channel without ever silently rerouting."""
    if not isinstance(channel, str):
        raise ValueError("Invalid model channel")
    normalized = channel.strip().lower()
    for kind, aliases in _LEGACY_ALIASES.items():
        if normalized in aliases:
            normalized = kind
            break
    if normalized in _DEFAULTS:
        saved = _repo().setting(_OWNER, _PREFIX + normalized)
        return saved if isinstance(saved, dict) else _default_profile(normalized)
    saved = _repo().setting(_OWNER, _CHANNEL_PREFIX + channel)
    if isinstance(saved, dict) and saved.get("name") == channel:
        return _effective_profile(saved) if effective else saved
    raise ValueError("Unsupported provider or Unknown model channel")


def _effective_profile(value: dict) -> dict:
    if value["provider"] == "virtual":
        from .virtual_channels import context_windows
        return {**value, "model_contexts": context_windows(value)}
    return value


def configured(value: dict) -> bool:
    if value["provider"] == "virtual":
        from .virtual_channels import physical_members
        return any(configured(stored) for model in value["models"]
                   for _, stored in physical_members(value, model))
    return bool(value["models"] and (value.get("api_key") or (value.get("oauth_id") and not value.get("oauth_error")) or (
        value["provider"] in {"openai", "openai-responses"} and urlsplit(value["base_url"]).hostname in {"127.0.0.1", "localhost", "::1"})))


def _redact(value: dict) -> dict:
    value = _effective_profile(value)
    parsed = urlsplit(value["base_url"])
    return {"provider": value["provider"],
            **({"name": value["name"]} if "name" in value else {}),
            "base_url": urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", "")),
            "models": value["models"], "model_contexts": value.get("model_contexts", {}),
            "model_sampling": value.get("model_sampling") or {},
            "auto_discover": value.get("auto_discover") is True,
            "discovered_model_contexts": value.get("discovered_model_contexts") or {},
            "model_context_overrides": value.get("model_context_overrides") or {},
            "model_sync_at": value.get("model_sync_at"),
            "model_sync_error": value.get("model_sync_error"),
            "configured": configured(value),
            **({k: value[k] for k in ("routes", "strategy", "session_affinity")} if value["provider"] == "virtual" else {}),
            **({"auth_method": value["auth_method"], "oauth_error": value.get("oauth_error")}
               if value.get("oauth_id") else {})}


def all_profiles() -> list[dict]:
    return [profile(kind) for kind in _DEFAULTS] + [_effective_profile(value) for value in _stored_channels()]


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


def validate_connection(body: dict) -> tuple[str, str, str | None]:
    from .providers import _require_https_or_loopback

    kind = body.get("provider")
    if not isinstance(kind, str) or kind not in _PROTOCOLS:
        raise ValueError("Unsupported model provider")
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
    key = body.get("api_key")
    if key is not None and (not isinstance(key, str) or len(key) > 16384 or any(ord(char) < 32 for char in key)):
        raise ValueError("Invalid model API key")
    return kind, base, (key.strip() or None) if key else None


def _validate_virtual(body: dict) -> dict:
    from .virtual_channels import STRATEGIES
    name = body.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or name != name.strip() or name.lower() in _RESERVED or name.lower().endswith("assistants"):
        raise ValueError("Invalid or reserved channel name")
    routes = body.get("routes")
    strategy = body.get("strategy", "priority")
    affinity = body.get("session_affinity", True)
    if strategy not in STRATEGIES or type(affinity) is not bool or not isinstance(routes, dict) or not 1 <= len(routes) <= 128:
        raise ValueError("Invalid virtual channel configuration")
    normalized = {}
    for model, members in routes.items():
        if not isinstance(model, str) or not model.strip() or model != model.strip() or len(model) > 200 or any(ord(c) < 32 for c in model):
            raise ValueError("Invalid virtual model identifier")
        if not isinstance(members, list) or not 1 <= len(members) <= 128:
            raise ValueError("Every virtual model requires members")
        seen = set()
        normalized[model] = []
        for member in members:
            if not isinstance(member, dict):
                raise ValueError("Invalid virtual model member")
            channel, target, weight = member.get("channel"), member.get("model"), member.get("weight", 1)
            if not isinstance(channel, str) or not isinstance(target, str) or type(weight) is not int or not 1 <= weight <= 10000:
                raise ValueError("Invalid virtual model member")
            stored = profile(channel, effective=False)
            if stored["provider"] == "virtual" or target not in stored["models"]:
                raise ValueError("Members must reference existing physical channel models")
            channel = stored.get("name") or stored["provider"]
            if channel == name or (channel, target) in seen:
                raise ValueError("Duplicate or recursive virtual model member")
            seen.add((channel, target))
            normalized[model].append({"channel": channel, "model": target, "weight": weight})
    sampling = body.get("model_sampling")
    if sampling is not None:
        if not isinstance(sampling, dict) or sampling.keys() - normalized.keys():
            raise ValueError("Sampling defaults must belong to configured models")
        sampling = {model: validate_sampling(v) for model, v in sampling.items()}
    return {"name": name, "provider": "virtual", "base_url": "", "api_key": None,
            "models": list(normalized), "routes": normalized, "strategy": strategy,
            "session_affinity": affinity, "auto_discover": False, "model_contexts": {},
            "model_sampling": sampling}


def _validate(body: dict) -> dict:
    if body.get("provider") == "virtual":
        return _validate_virtual(body)
    kind, base, key = validate_connection(body)
    name = body.get("name")
    if kind == "openai-responses" and name is None:
        raise ValueError("Responses channels require a channel name")
    if name is not None and (not isinstance(name, str) or not _NAME.fullmatch(name) or name != name.strip() or (name.lower() in _RESERVED or name.lower().endswith("assistants"))):
        raise ValueError("Invalid or reserved channel name")
    auto_discover = body.get("auto_discover", False)
    if type(auto_discover) is not bool:
        raise ValueError("auto_discover must be a boolean")
    models = body.get("models", [])
    if not isinstance(models, list) or (not models and not auto_discover) or len(models) > 128:
        raise ValueError("Provide between 1 and 128 model identifiers")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 200 or
           any(ord(char) < 32 for char in item) for item in models):
        raise ValueError("Invalid model identifier")
    models = list(dict.fromkeys(item.strip() for item in models))
    if kind == "google" and any(any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in item) for item in models):
        raise ValueError("Unsupported Gemini model identifier")
    model_contexts = body.get('model_contexts', {})
    if not isinstance(model_contexts, dict) or any(
        model not in models or type(limit) is not int or not 1 <= limit <= 2_000_000
        for model, limit in model_contexts.items()
    ):
        raise ValueError('Model context windows must be integers from 1 to 2000000 for configured models')
    model_sampling = body.get("model_sampling")
    if model_sampling is not None:
        if not isinstance(model_sampling, dict) or model_sampling.keys() - set(models):
            raise ValueError("Sampling defaults must belong to configured models")
        model_sampling = {model: validate_sampling(value, provider=kind) for model, value in model_sampling.items()}
    return {**({"name": name} if name is not None else {}), "provider": kind, "base_url": base,
            "models": models, "api_key": key,
            "model_contexts": model_contexts,
            "auto_discover": auto_discover,
            "model_sampling": model_sampling}


def _access(request):
    from ..auth import _is_cross_origin_request, require_scopes
    from ..settings import get_settings

    _owner(request)
    if get_settings().auth_mode == "none" and _is_cross_origin_request(request):
        raise HTTPException(401, detail="Cross-origin Controller settings access is not allowed")
    if get_settings().auth_mode != "none":
        require_scopes(request.state.principal, ["admin:config"])


def _reference_types(db, name: str, *, legacy: bool = False) -> list[str]:
    # Retain snapshots and chat history; a forced removal must not rewrite the
    # original provider identity to point at unrelated credentials.
    references = (
        ("agents", "json_extract(config,'$.provider')", "Agents"),
        ("runs", "json_extract(state,'$.provider')", "run history"),
        ("conversations", "endpoint", "saved conversations"),
        ("agent_versions", "json_extract(snapshot,'$.provider')", "Agent revisions"),
    )
    aliases = _LEGACY_ALIASES[name] if legacy else ()
    used_by = []
    for table, field, label in references:
        if legacy:
            placeholders = ",".join("?" for _ in aliases)
            query = f"SELECT 1 FROM {table} WHERE LOWER(TRIM({field})) IN ({placeholders}) LIMIT 1"
            params = aliases
        else:
            query = f"SELECT 1 FROM {table} WHERE {field}=? LIMIT 1"
            params = (name,)
        if db.execute(query, params).fetchone():
            used_by.append(label)
    rows = db.execute("SELECT value FROM settings WHERE owner=? AND key LIKE ?",
                      (_OWNER, _CHANNEL_PREFIX + "%")).fetchall()
    for row in rows:
        value = json.loads(row[0])
        if value.get("provider") == "virtual" and any(
            member["channel"] in (aliases if legacy else (name,))
            for members in value.get("routes", {}).values() for member in members
        ):
            used_by.append("virtual channels")
            break
    return used_by


def _is_referenced(db, name: str, *, legacy: bool = False) -> bool:
    return bool(_reference_types(db, name, legacy=legacy))


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
        else:
            if not isinstance(name, str) or not _NAME.fullmatch(name) or name != name.strip() or name.lower() in _RESERVED:
                raise HTTPException(400, detail="Invalid named channel")
            key = _CHANNEL_PREFIX + name
        # Explicit force removal is limited to named channels: resetting a
        # referenced built-in alias would silently route old chats to defaults.
        force = request.query_params.get("force", "false")
        if force not in {"false", "true"}:
            raise HTTPException(400, detail="force must be true or false")
        with _repo().database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            references = _reference_types(db, legacy or name, legacy=legacy is not None)
            if references and (force != "true" or legacy is not None):
                return JSONResponse({
                    "detail": "Channel is referenced by " + ", ".join(references) + ". "
                              + ("Choose another channel in affected chats and Agents before resetting "
                                 "this built-in channel."
                                 if legacy is not None else
                                 "Deleting it keeps history but affected chats and Agents must "
                                 "select another channel before running again."),
                    "can_force": legacy is None,
                }, status_code=409, headers={"Cache-Control": "no-store"})
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
        discovery = None
        previous_connection = None
        previous_key = _CHANNEL_PREFIX + old_name if renaming else key
        saved = _repo().setting(_OWNER, previous_key)
        if isinstance(saved, dict) and saved.get("oauth_id") and (
            value["api_key"] is not None or value["base_url"] != saved["base_url"] or value["provider"] != saved["provider"]
        ):
            raise HTTPException(400, detail="Account channel authentication and endpoint cannot be changed")
        if value["auto_discover"]:
            from .model_discovery import prepare_auto_save

            previous_key = _CHANNEL_PREFIX + old_name if renaming else key
            saved = _repo().setting(_OWNER, previous_key)
            previous = saved if isinstance(saved, dict) else (
                _default_profile(value["provider"]) if name is None else {})
            previous_connection, discovery = await prepare_auto_save(value, previous)
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
            if previous.get("oauth_id"):
                if value["api_key"] is not None or value["base_url"] != previous["base_url"] or value["provider"] != previous["provider"]:
                    raise HTTPException(400, detail="Account channel authentication and endpoint cannot be changed")
                for field in ("auth_method", "oauth_id", "oauth_credentials", "oauth_error"):
                    value[field] = previous[field]
            if value["api_key"] is None:
                value["api_key"] = previous.get("api_key", "")
            if value["model_sampling"] is None:
                value["model_sampling"] = {model: sampling for model, sampling in
                                           (previous.get("model_sampling") or {}).items()
                                           if value["auto_discover"] or model in value["models"]}
            if value["auto_discover"]:
                from .model_discovery import apply_auto_save, connection_identity

                if previous_connection != connection_identity(previous):
                    raise HTTPException(409, detail="Channel connection changed; retry saving")
                apply_auto_save(value, previous, discovery)
            db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                       "DO UPDATE SET value=excluded.value", (_OWNER, key, json.dumps(value)))
            if renaming:
                db.execute("DELETE FROM settings WHERE owner=? AND key=?", (_OWNER, _CHANNEL_PREFIX + old_name))
    return JSONResponse(public_profiles(), headers={"Cache-Control": "no-store"})
