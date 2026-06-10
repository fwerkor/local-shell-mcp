"""Load, normalize, and validate runtime settings for workspace boundaries, authentication, tools, and remote workers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_WORKSPACE_ROOT = Path("/workspace")
DEFAULT_STATE_DIR = DEFAULT_WORKSPACE_ROOT / ".local-shell-mcp"
DEFAULT_AUDIT_LOG_PATH = DEFAULT_STATE_DIR / "audit.jsonl"
DEFAULT_AGENT_CONFIG_DIR = Path("/home/agent/local-shell-mcp-config")
ENV_PREFIX = "LOCAL_SHELL_MCP_"

SENSITIVE_SETTING_KEYS = {
    "cf_access_audience",
    "cf_access_allowed_emails",
    "cf_access_allowed_email_domains",
    "oauth_admin_pin",
    "oauth_jwt_secret",
}


def _split_csv(value: str | list[str] | None) -> list[str]:
    """Normalize comma-delimited environment values into trimmed non-empty items."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


class Settings(BaseSettings):
    """Runtime settings.

    Environment variables use the LOCAL_SHELL_MCP_ prefix. Optional YAML config can
    be supplied with --config or LOCAL_SHELL_MCP_CONFIG. Effective precedence is:
    defaults < config file < environment variables < CLI overrides.
    """

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8765
    mode: Literal["mcp", "http", "both", "stdio"] = "mcp"

    workspace_root: Path = DEFAULT_WORKSPACE_ROOT
    audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH
    state_dir: Path = DEFAULT_STATE_DIR

    # By default, tools are limited to workspace_root. Set true only inside a disposable container.
    allow_full_container: bool = False
    allow_network: bool = True

    default_timeout_s: int = 60
    max_timeout_s: int = 3600
    max_output_bytes: int = 200_000
    max_file_read_bytes: int = 512_000
    max_file_write_bytes: int = 5_000_000
    max_grep_results: int = 200
    max_directory_entries: int = 5_000
    max_glob_results: int = 5_000
    max_tree_entries: int = 5_000
    max_read_many_files: int = 100
    max_read_many_total_bytes: int = 5_000_000
    max_todos: int = 1_000
    max_todo_bytes: int = 1_000_000
    max_audit_tail_bytes: int = 1_000_000
    max_audit_log_bytes: int = 20_000_000
    max_tmp_files: int = 500
    max_tmp_bytes: int = 50_000_000
    max_concurrent_commands: int = 4
    max_tmux_sessions: int = 16

    # Remote worker mode is enabled by default. Remote machines join with one-time
    # invites, poll for jobs over outbound HTTP(S), and expose near-parity tools.
    remote_enabled: bool = True
    remote_invite_ttl_s: int = 600
    remote_poll_timeout_s: int = 25
    remote_job_timeout_s: int = 3600

    # Agent capability bridge. External sync tools write normalized MCP and skill
    # config here; local-shell-mcp reads it without mutating it.
    agent_bridge_enabled: bool = True
    agent_config_dir: Path = DEFAULT_AGENT_CONFIG_DIR
    agent_mcp_probe_timeout_s: int = 5
    agent_mcp_call_timeout_s: int = 60
    agent_dynamic_mcp_tools: bool = True
    agent_dynamic_skill_tools: bool = True

    shell_executable: str = "/bin/bash"
    tmux_bin: str = "tmux"
    rg_bin: str = "rg"
    git_bin: str = "git"
    python_bin: str = "python3"

    # Authentication. OAuth is the default for ChatGPT custom connectors.
    auth_mode: Literal["none", "oauth"] = "oauth"
    auth_bypass_localhost: bool = True
    require_auth_for_mcp_discovery: bool = False

    # Built-in OAuth 2.1 authorization server for ChatGPT MCP connectors.
    # Set public_base_url to the externally reachable HTTPS origin, e.g. https://local-shell-mcp.example.com
    public_base_url: str | None = None
    oauth_issuer: str | None = None
    oauth_resource: str | None = None
    oauth_admin_pin: str | None = None
    oauth_jwt_secret: str = Field(
        default_factory=lambda: os.getenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET") or "dev-change-me"
    )
    # 0 means access tokens never expire.
    oauth_access_token_ttl_s: int = 0
    oauth_code_ttl_s: int = 300

    # Command policy. Set denylist empty if this container is intentionally disposable.
    command_denylist: list[str] = Field(
        default_factory=lambda: [
            "docker.sock",
            "/var/run/docker.sock",
            "mkfs",
            "mount ",
            "umount ",
            "shutdown",
            "reboot",
            "systemctl ",
            "iptables",
            "nft ",
        ]
    )
    path_denylist: list[str] = Field(
        default_factory=lambda: [
            ".ssh/id_rsa",
            ".ssh/id_ed25519",
            ".env",
            "secrets",
            "credentials",
            ".git/config",
        ]
    )

    @field_validator(
        "workspace_root", "audit_log_path", "state_dir", "agent_config_dir", mode="before"
    )
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        """Expand user and environment variables for path settings before validation."""
        return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()

    @field_validator("command_denylist", "path_denylist", mode="before")
    @classmethod
    def split_csv_fields(cls, value):  # noqa: ANN001
        """Normalize comma-delimited restriction lists supplied through environment variables."""
        return _split_csv(value)

    @model_validator(mode="after")
    def disable_builtin_restrictions_in_full_container_mode(self) -> Settings:
        """Remove built-in command and path restrictions when full-container mode is explicitly enabled."""
        if self.allow_full_container:
            self.command_denylist = []
            self.path_denylist = []
        return self

    def with_workspace_relative_defaults(self) -> Settings:
        """Resolve state and audit paths relative to the workspace when they were left at defaults."""
        if self.workspace_root == DEFAULT_WORKSPACE_ROOT:
            return self

        updates = {}
        if self.state_dir == DEFAULT_STATE_DIR:
            updates["state_dir"] = self.workspace_root / ".local-shell-mcp"
        if self.audit_log_path == DEFAULT_AUDIT_LOG_PATH:
            state_dir = updates.get("state_dir", self.state_dir)
            updates["audit_log_path"] = state_dir / "audit.jsonl"

        if not updates:
            return self
        return self.model_copy(update=updates)


def _flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten one level of grouped YAML keys into Settings field names."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                flat[f"{key}_{child_key}"] = child_value
        else:
            flat[key] = value
    return flat


def read_config_file(path: str | Path | None) -> dict[str, Any]:
    """Read optional YAML configuration values."""
    if not path:
        return {}
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(config_path)
    data = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {config_path}")
    return _flatten_config(data)


def _env_overrides() -> dict[str, Any]:
    """Return settings explicitly present in the process environment."""
    present = {
        name: field_name
        for field_name in Settings.model_fields
        if (name := f"{ENV_PREFIX}{field_name.upper()}") in os.environ
    }
    if not present:
        return {}
    env_settings = Settings()
    return {field_name: getattr(env_settings, field_name) for field_name in present.values()}


def _prepare_settings(settings: Settings, *, create_dirs: bool) -> Settings:
    """Apply derived defaults and create runtime directories when requested."""
    settings = settings.with_workspace_relative_defaults()
    if create_dirs:
        settings.workspace_root.mkdir(parents=True, exist_ok=True)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        settings.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


def load_settings(
    config_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    *,
    create_dirs: bool = True,
) -> Settings:
    """Load settings with precedence: defaults < config file < environment < explicit overrides."""
    config_path = config_path or os.getenv("LOCAL_SHELL_MCP_CONFIG")
    values = read_config_file(config_path)
    values.update(_env_overrides())
    values.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return _prepare_settings(Settings(**values), create_dirs=create_dirs)


@lru_cache(maxsize=1)
def _cached_settings(settings: Settings | None = None) -> Settings:
    if settings is None:
        return load_settings()
    return settings


def get_settings() -> Settings:
    """Return cached settings, optionally primed by configure_settings."""
    return _cached_settings()


def configure_settings(settings: Settings) -> None:
    """Install a fully resolved Settings object for subsequent get_settings calls."""
    _cached_settings.cache_clear()
    _cached_settings(settings)


def clear_settings_cache() -> None:
    """Clear cached settings. Intended for tests and CLI reconfiguration."""
    _cached_settings.cache_clear()


# Backwards-compatible test helper: many tests call get_settings.cache_clear().
get_settings.cache_clear = clear_settings_cache  # type: ignore[attr-defined]


def safe_settings_dump(settings: Settings | None = None) -> dict:
    """Return settings for diagnostics without exposing credentials or auth secrets."""

    data = (settings or get_settings()).model_dump(mode="json")
    for key in SENSITIVE_SETTING_KEYS:
        if key in data:
            value = data[key]
            if value in (None, "", []):
                data[key] = value
            else:
                data[key] = "<redacted>"
    return data


def validate_public_oauth_configuration(settings: Settings | None = None) -> None:
    """Reject HTTP OAuth startup configurations that cannot produce externally valid issuer and resource metadata."""
    settings = settings or get_settings()
    if settings.auth_mode != "oauth" or not settings.public_base_url:
        return
    weak_values = {"", "dev-" + "change-me"}
    if settings.oauth_jwt_secret in weak_values:
        raise RuntimeError(
            "LOCAL_SHELL_MCP_OAUTH_JWT_SECRET must be set to a strong random value "
            "when LOCAL_SHELL_MCP_PUBLIC_BASE_URL is configured."
        )
