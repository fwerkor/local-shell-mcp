from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from .settings import (
    _WEAK_OAUTH_SECRET_VALUES,
    OAUTH_JWT_SECRET_FILE_NAME,
    SENSITIVE_SETTING_KEYS,
    Settings,
    _read_oauth_secret,
    _without_environment_overrides,
    controller_config_path,
    get_settings,
    validate_public_oauth_configuration,
)

_LOCK = threading.Lock()
_MAX_CONFIG_BYTES = 256 * 1024
_CHOICES = {
    "mode": ["mcp", "http", "both", "stdio"],
    "auth_mode": ["oauth", "none"],
    "state_backend": ["sqlite", "file", "memory", "redis"],
    "ui_wallpaper": ["bing", "aurora", "none"],
    "remote_transfer_strategy": ["auto", "relay", "direct", "object_store"],
}


def config_file() -> Path:
    return controller_config_path().absolute()


def _read_config(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink():
        raise ValueError("Configuration file must not be a symbolic link")
    if not path.exists():
        return {}, hashlib.sha256(b"").hexdigest()
    if not path.is_file():
        raise ValueError("Configuration path is not a regular file")
    with path.open("rb") as stream:
        raw = stream.read(_MAX_CONFIG_BYTES + 1)
    if len(raw) > _MAX_CONFIG_BYTES:
        raise ValueError("Configuration file exceeds 256 KiB")
    parsed = yaml.safe_load(raw) if raw.strip() else {}
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ValueError("Configuration must be a YAML mapping with string keys")
    return parsed, hashlib.sha256(raw).hexdigest()


def _flatten_values(data: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for child, nested in value.items():
                result[f"{key}_{child}"] = nested
        else:
            result[key] = value
    return result


def _is_secret(name: str) -> bool:
    name = name.lower()
    return name in SENSITIVE_SETTING_KEYS or name.endswith(
        ("_password", "_secret", "_api_key", "_token", "_private_key", "_pin")
    )


def _env_locked(name: str) -> bool:
    return f"local_shell_mcp_{name}".casefold() in {key.casefold() for key in os.environ}


def _group(name: str) -> str:
    if name.startswith(("oauth_", "auth_", "require_auth", "public_base_url")):
        return "Authentication"
    if name.startswith(("ui_", "live_workspace_")):
        return "Web UI & Chat"
    if name.startswith(("remote_", "file_download_")):
        return "Remotes & Transfers"
    if name.startswith(("shell_", "tmux_", "command_", "path_")):
        return "Execution & Security"
    if name.startswith(("max_", "default_")):
        return "Resource Limits"
    if name.startswith(("state_", "audit_", "agent_", "workspace_")):
        return "Storage"
    return "General"


def config_snapshot() -> dict[str, Any]:
    path = config_file()
    document, revision = _read_config(path)
    flat = _flatten_values(document)
    current = get_settings().model_dump(mode="json")
    next_values = _validate_candidate(document, set()).model_dump(mode="json")
    fields = []
    for name, value in next_values.items():
        sensitive = _is_secret(name)
        locked = _env_locked(name)
        field_type = (
            "boolean" if isinstance(value, bool) else
            "integer" if isinstance(value, int) else
            "list" if isinstance(value, list) else "text"
        )
        fields.append({
            "name": name,
            "group": _group(name),
            "type": field_type,
            "value": None if sensitive else value,
            "configured": bool(value) if sensitive else name in flat,
            "sensitive": sensitive,
            "locked": locked,
            "pending": value != current[name] and not locked,
            "source": "environment" if locked else "config" if name in flat else "default",
            "choices": _CHOICES.get(name),
        })
    running = get_settings()
    return {
        "path": str(path), "revision": revision, "fields": fields,
        "running": {"port": running.port, "ui_path": running.ui_path},
    }


def _apply_change(document: dict[str, Any], name: str, value: Any) -> None:
    if name in document:
        if value is None:
            del document[name]
        else:
            document[name] = value
        return
    # Respect an existing section-style YAML document, if present.
    for parent, section in document.items():
        if isinstance(section, dict) and name.startswith(parent + "_"):
            child = name[len(parent) + 1:]
            if child in section:
                if value is None:
                    del section[child]
                else:
                    section[child] = value
                return
    if value is not None:
        document[name] = value


def _validate_candidate(document: dict[str, Any], changed: set[str]) -> Settings:
    flat = _flatten_values(document)
    base = Settings()
    merged = base.model_dump()
    merged.update(_without_environment_overrides(flat))
    if merged["mode"] == "both":
        raise ValueError("mode=both is not supported by the controller")
    try:
        if hasattr(Settings, "model_fields"):
            candidate = Settings(**merged)
        else:
            candidate = Settings(**merged, _load_environment=False)
        candidate = candidate.with_workspace_relative_defaults()
        # Stateless OAuth cannot re-use a generated secret from the running server.
        # Its next startup is required to have an explicitly configured secret.
        explicit_secret = (
            os.getenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET")
            or flat.get("oauth_jwt_secret")
        )
        if candidate.stateless_controller and candidate.auth_mode == "oauth":
            if (not isinstance(explicit_secret, str)
                    or len(explicit_secret.encode("utf-8")) < 32
                    or explicit_secret in {"dev-change-me", "change-me-64-hex-random-secret"}):
                raise ValueError("stateless OAuth requires an explicit strong oauth_jwt_secret")
        elif candidate.auth_mode == "oauth" and candidate.oauth_jwt_secret in _WEAK_OAUTH_SECRET_VALUES:
            # Stateful startup uses a persisted generated secret when present.
            # For first startup, validate against a synthetic strong secret
            # without creating persistent state during a snapshot or save.
            secret_file = candidate.state_dir / OAUTH_JWT_SECRET_FILE_NAME
            secret = _read_oauth_secret(secret_file)
            if secret is None and secret_file.exists():
                raise ValueError("Existing OAuth secret file is invalid")
            candidate = candidate.model_copy(update={"oauth_jwt_secret": secret or secrets.token_urlsafe(48)})
        validate_public_oauth_configuration(candidate)
    except Exception as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("stateless OAuth requires"):
            raise
        if hasattr(exc, "errors"):
            errors = exc.errors()
            if errors:
                first = errors[0]
                field = ".".join(map(str, first.get("loc", ())))
                raise ValueError(f"Invalid value for {field or 'configuration'} ({first.get('type', 'validation')})") from None
        # Do not echo inputs, which may contain credentials.
        raise ValueError(f"Invalid configuration ({type(exc).__name__})") from None
    return candidate


def save_config(changes: dict[str, Any], expected_revision: str) -> dict[str, Any]:
    if not isinstance(changes, dict) or not changes or len(changes) > 150:
        raise ValueError("Provide one or more configuration changes")
    valid_names = set(get_settings().model_dump())
    for name in changes:
        if name not in valid_names:
            raise ValueError(f"Unknown configuration key: {name}")
        if _env_locked(name):
            raise ValueError(f"{name} is controlled by an environment variable")
    with _LOCK:
        path = config_file()
        document, revision = _read_config(path)
        if revision != expected_revision:
            raise RuntimeError("Configuration changed since it was loaded; refresh before saving")
        for name, value in changes.items():
            if value is not None and not isinstance(value, (str, int, bool, list)):
                raise ValueError(f"Unsupported value for {name}")
            if isinstance(value, list) and not all(isinstance(item, str) for item in value):
                raise ValueError(f"{name} must be a list of strings")
            _apply_change(document, name, value)
        _validate_candidate(document, set(changes))
        content = yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode("utf-8")
        if len(content) > _MAX_CONFIG_BYTES:
            raise ValueError("Configuration file exceeds 256 KiB")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return {"revision": hashlib.sha256(content).hexdigest(), "changed": list(changes), "restart_required": True}
