from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

try:
    import yaml
except Exception:  # pragma: no cover - dependency-light worker bootstrap.
    yaml = None

try:
    from pydantic import Field, field_validator, model_validator
    from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
except Exception:  # pragma: no cover - exercised when vendored native deps do not match Python ABI.
    Field = None  # type: ignore[assignment]
    field_validator = None  # type: ignore[assignment]
    model_validator = None  # type: ignore[assignment]
    BaseSettings = object  # type: ignore[assignment]
    NoDecode = object  # type: ignore[assignment]
    SettingsConfigDict = None  # type: ignore[assignment]
    _PYDANTIC_AVAILABLE = False
else:
    _PYDANTIC_AVAILABLE = True

DEFAULT_WORKSPACE_ROOT = Path("/workspace")
DEFAULT_STATE_DIR = DEFAULT_WORKSPACE_ROOT / ".local-shell-mcp"
DEFAULT_AUDIT_LOG_PATH = DEFAULT_STATE_DIR / "audit.jsonl"
DEFAULT_AGENT_CONFIG_DIR = DEFAULT_STATE_DIR / "agent_config"


def default_shell_executable() -> str:
    if os.name == "nt":
        return "power" + "shell.exe"
    return "/bin/bash"


SENSITIVE_SETTING_KEYS = {
    "cf_access_audience",
    "cf_access_allowed_emails",
    "cf_access_allowed_email_domains",
    "oauth_admin_pin",
    "oauth_jwt_secret",
}


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


def _flatten_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load LOCAL_SHELL_MCP_CONFIG")
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text()) or {}
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                flat[f"{key}_{child_key}"] = child_value
        else:
            flat[key] = value
    return flat


if _PYDANTIC_AVAILABLE:

    class Settings(BaseSettings):
        """Runtime settings.

        Environment variables use the LOCAL_SHELL_MCP_ prefix.
        YAML config values can be supplied with LOCAL_SHELL_MCP_CONFIG.
        """

        model_config = SettingsConfigDict(env_prefix="LOCAL_SHELL_MCP_", extra="ignore")

        host: str = "0.0.0.0"
        port: int = 8765
        mode: Literal["mcp", "http", "both", "stdio"] = "mcp"

        workspace_root: Path = DEFAULT_WORKSPACE_ROOT
        audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH
        state_dir: Path = DEFAULT_STATE_DIR
        agent_config_dir: Path = DEFAULT_AGENT_CONFIG_DIR

        # By default, tools are limited to workspace_root. Set true only inside a disposable container.
        allow_full_container: bool = False

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

        # Optional agent capability bridge. When enabled, local-shell-mcp can expose
        # externally synced MCP servers and Markdown skills from agent_config_dir.
        agent_bridge_enabled: bool = False
        agent_mcp_probe_timeout_s: float = 5.0
        agent_mcp_call_timeout_s: float = 60.0
        agent_dynamic_mcp_tools: bool = False
        agent_dynamic_skill_tools: bool = False

        file_download_enabled: bool = True
        file_download_default_ttl_s: int = 3600
        file_download_max_ttl_s: int = 604800
        file_download_default_max_downloads: int = 0
        file_download_max_file_bytes: int = 0

        # Remote worker mode is enabled by default. Remote machines join with one-time
        # invites, poll for jobs over outbound HTTP(S), and expose near-parity tools.
        remote_enabled: bool = True
        remote_invite_ttl_s: int = 600
        remote_poll_timeout_s: int = 25
        remote_job_timeout_s: int = 3600

        shell_executable: str = Field(default_factory=default_shell_executable)
        shell_env_blocklist: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["CLOUDFLARE_TUNNEL_TOKEN"])
        shell_env_blocked_prefixes: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["LOCAL_SHELL_MCP_", "DOCKER_"])
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
        oauth_jwt_secret: str = Field(default_factory=lambda: os.getenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET") or "dev-change-me")
        # 0 means access tokens never expire.
        oauth_access_token_ttl_s: int = 0
        oauth_code_ttl_s: int = 300

        # Command policy. Set denylist empty if this container is intentionally disposable.
        command_denylist: Annotated[list[str], NoDecode] = Field(
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
        path_denylist: Annotated[list[str], NoDecode] = Field(
            default_factory=lambda: [
                ".ssh/id_rsa",
                ".ssh/id_ed25519",
                ".env",
                "secrets",
                "credentials",
                ".git/config",
            ]
        )

        @field_validator("workspace_root", "audit_log_path", "state_dir", "agent_config_dir", mode="before")
        @classmethod
        def expand_path(cls, value: str | Path) -> Path:
            return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()

        @field_validator("command_denylist", "path_denylist", "shell_env_blocklist", "shell_env_blocked_prefixes", mode="before")
        @classmethod
        def split_csv_fields(cls, value):  # noqa: ANN001
            return _split_csv(value)

        @model_validator(mode="after")
        def disable_builtin_restrictions_in_full_container_mode(self) -> Settings:
            if self.allow_full_container:
                self.command_denylist = []
                self.path_denylist = []
            return self

        def apply_yaml(self, path: Path) -> Settings:
            flat = _flatten_yaml(path)
            merged = self.model_dump()
            merged.update(flat)
            return Settings(**merged)

        def with_workspace_relative_defaults(self) -> Settings:
            if self.workspace_root == DEFAULT_WORKSPACE_ROOT:
                return self

            updates = {}
            if self.state_dir == DEFAULT_STATE_DIR:
                updates["state_dir"] = self.workspace_root / ".local-shell-mcp"
            state_dir = updates.get("state_dir", self.state_dir)
            if self.audit_log_path == DEFAULT_AUDIT_LOG_PATH:
                updates["audit_log_path"] = state_dir / "audit.jsonl"
            if self.agent_config_dir == DEFAULT_AGENT_CONFIG_DIR:
                updates["agent_config_dir"] = state_dir / "agent_config"

            if not updates:
                return self
            return self.model_copy(update=updates)

else:
    from dataclasses import asdict, dataclass, field, fields, replace

    def _env_bool(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _coerce_env_value(value: str, current: Any) -> Any:
        if isinstance(current, bool):
            return _env_bool(value)
        if isinstance(current, int) and not isinstance(current, bool):
            return int(value)
        if isinstance(current, float):
            return float(value)
        if isinstance(current, Path):
            return Path(os.path.expandvars(os.path.expanduser(value))).resolve()
        if isinstance(current, list):
            return _split_csv(value)
        if current is None:
            return value or None
        return value

    @dataclass
    class Settings:
        """Dependency-light fallback settings for remote worker bootstraps."""

        host: str = "0.0.0.0"
        port: int = 8765
        mode: Literal["mcp", "http", "both", "stdio"] = "mcp"

        workspace_root: Path = DEFAULT_WORKSPACE_ROOT
        audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH
        state_dir: Path = DEFAULT_STATE_DIR
        agent_config_dir: Path = DEFAULT_AGENT_CONFIG_DIR

        allow_full_container: bool = False

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

        agent_bridge_enabled: bool = False
        agent_mcp_probe_timeout_s: float = 5.0
        agent_mcp_call_timeout_s: float = 60.0
        agent_dynamic_mcp_tools: bool = False
        agent_dynamic_skill_tools: bool = False

        file_download_enabled: bool = True
        file_download_default_ttl_s: int = 3600
        file_download_max_ttl_s: int = 604800
        file_download_default_max_downloads: int = 0
        file_download_max_file_bytes: int = 0

        remote_enabled: bool = True
        remote_invite_ttl_s: int = 600
        remote_poll_timeout_s: int = 25
        remote_job_timeout_s: int = 3600

        shell_executable: str = field(default_factory=default_shell_executable)
        shell_env_blocklist: list[str] = field(default_factory=lambda: ["CLOUDFLARE_TUNNEL_TOKEN"])
        shell_env_blocked_prefixes: list[str] = field(default_factory=lambda: ["LOCAL_SHELL_MCP_", "DOCKER_"])
        tmux_bin: str = "tmux"
        rg_bin: str = "rg"
        git_bin: str = "git"
        python_bin: str = "python3"

        auth_mode: Literal["none", "oauth"] = "oauth"
        auth_bypass_localhost: bool = True
        require_auth_for_mcp_discovery: bool = False

        public_base_url: str | None = None
        oauth_issuer: str | None = None
        oauth_resource: str | None = None
        oauth_admin_pin: str | None = None
        oauth_jwt_secret: str = field(default_factory=lambda: os.getenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET") or "dev-change-me")
        oauth_access_token_ttl_s: int = 0
        oauth_code_ttl_s: int = 300

        command_denylist: list[str] = field(
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
        path_denylist: list[str] = field(
            default_factory=lambda: [
                ".ssh/id_rsa",
                ".ssh/id_ed25519",
                ".env",
                "secrets",
                "credentials",
                ".git/config",
            ]
        )

        def __post_init__(self) -> None:
            for item in fields(self):
                env_name = "LOCAL_SHELL_MCP_" + item.name.upper()
                if env_name in os.environ:
                    setattr(self, item.name, _coerce_env_value(os.environ[env_name], getattr(self, item.name)))
            for attr in ("workspace_root", "audit_log_path", "state_dir", "agent_config_dir"):
                setattr(self, attr, Path(os.path.expandvars(os.path.expanduser(str(getattr(self, attr))))).resolve())
            if self.allow_full_container:
                self.command_denylist = []
                self.path_denylist = []

        def model_dump(self, mode: str | None = None) -> dict[str, Any]:
            data = asdict(self)
            if mode == "json":
                for key, value in list(data.items()):
                    if isinstance(value, Path):
                        data[key] = str(value)
            return data

        def model_copy(self, update: dict[str, Any] | None = None) -> Settings:
            return replace(self, **(update or {}))

        def apply_yaml(self, path: Path) -> Settings:
            merged = self.model_dump()
            merged.update(_flatten_yaml(path))
            return Settings(**merged)

        def with_workspace_relative_defaults(self) -> Settings:
            if self.workspace_root == DEFAULT_WORKSPACE_ROOT:
                return self
            updates = {}
            if self.state_dir == DEFAULT_STATE_DIR:
                updates["state_dir"] = self.workspace_root / ".local-shell-mcp"
            state_dir = updates.get("state_dir", self.state_dir)
            if self.audit_log_path == DEFAULT_AUDIT_LOG_PATH:
                updates["audit_log_path"] = state_dir / "audit.jsonl"
            if self.agent_config_dir == DEFAULT_AGENT_CONFIG_DIR:
                updates["agent_config_dir"] = state_dir / "agent_config"
            return self.model_copy(update=updates) if updates else self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    config = os.getenv("LOCAL_SHELL_MCP_CONFIG")
    if config:
        settings = settings.apply_yaml(Path(config).expanduser())
    settings = settings.with_workspace_relative_defaults()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.agent_config_dir.mkdir(parents=True, exist_ok=True)
    return settings


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
    settings = settings or get_settings()
    if settings.auth_mode != "oauth" or not settings.public_base_url:
        return
    weak_values = {"", "dev-" + "change-me"}
    if settings.oauth_jwt_secret in weak_values:
        raise RuntimeError(
            "LOCAL_SHELL_MCP_OAUTH_JWT_SECRET must be set to a strong random value "
            "when LOCAL_SHELL_MCP_PUBLIC_BASE_URL is configured."
        )
