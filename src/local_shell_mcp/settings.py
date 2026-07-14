from __future__ import annotations

import contextlib
import os
import secrets
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
OAUTH_JWT_SECRET_FILE_NAME = "oauth-jwt-secret"
_WEAK_OAUTH_SECRET_VALUES = {
    "",
    "dev-" + "change-me",
    "change-me-64-hex-random-secret",
}


def _matches_default_path(value: Path, default: Path) -> bool:
    """Match a default path before or after platform-specific normalization."""
    if value == default:
        return True
    try:
        return value == default.resolve()
    except (OSError, RuntimeError):
        return False


def default_shell_executable() -> str:
    if os.name == "nt":
        return "power" + "shell.exe"
    return "/bin/bash"


def _replace_settings(settings: Settings, **updates: Any) -> Settings:
    if hasattr(settings, "model_copy"):
        return settings.model_copy(update=updates)
    from dataclasses import replace

    return replace(settings, **updates)


def _read_oauth_secret(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if len(value.encode("utf-8")) >= 32 else None


def _get_or_create_oauth_secret(state_dir: Path) -> str:
    path = state_dir / OAUTH_JWT_SECRET_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        existing = _read_oauth_secret(path)
        if existing:
            return existing
        generated = secrets.token_urlsafe(48)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                path.unlink()
            except OSError as exc:
                raise RuntimeError(f"Unable to replace invalid OAuth secret: {path}") from exc
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(generated)
            handle.write("\n")
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return generated
    existing = _read_oauth_secret(path)
    if existing:
        return existing
    raise RuntimeError(f"Unable to initialize OAuth secret: {path}")


def _ensure_oauth_jwt_secret(settings: Settings) -> Settings:
    if settings.auth_mode != "oauth":
        return settings
    current = str(settings.oauth_jwt_secret or "")
    if current not in _WEAK_OAUTH_SECRET_VALUES:
        return settings
    return _replace_settings(
        settings,
        oauth_jwt_secret=_get_or_create_oauth_secret(settings.state_dir),
    )


_RESERVED_UI_PATHS = {
    "/",
    "/api",
    "/mcp",
    "/oauth",
    "/.well-known",
    "/download",
    "/remote",
    "/join",
    "/healthz",
    "/readyz",
    "/docs",
    "/openapi.json",
}


def normalize_ui_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw.startswith("/"):
        raise ValueError("ui_path must start with '/'")
    if any(character in raw for character in ("?", "#", "\\")):
        raise ValueError("ui_path must be a plain URL path")
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("ui_path must identify a non-root path without dot segments")
    normalized = "/" + "/".join(parts)
    for reserved in _RESERVED_UI_PATHS:
        if normalized == reserved or normalized.startswith(reserved + "/"):
            raise ValueError(f"ui_path conflicts with reserved service path: {reserved}")
    return normalized


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
        max_skills: int = 256
        max_skill_related_files: int = 1_000
        max_skill_scan_entries: int = 5_000
        max_skill_path_bytes: int = 200_000
        max_read_many_files: int = 100
        max_read_many_total_bytes: int = 5_000_000
        max_todos: int = 1_000
        max_todo_bytes: int = 1_000_000
        max_job_log_bytes: int = 10_000_000
        max_audit_tail_bytes: int = 1_000_000
        max_audit_log_bytes: int = 20_000_000
        max_tmp_files: int = 500
        max_tmp_bytes: int = 50_000_000
        max_transfer_archive_entries: int = 100_000
        max_transfer_unpacked_bytes: int = 10_000_000_000
        max_concurrent_commands: int = 4
        max_tmux_sessions: int = 16

        # Human-facing OpenTUI/WebUI. The browser interface is mounted on the same
        # ASGI service and launches the exact same TUI executable as the local CLI.
        ui_enabled: bool = True
        ui_path: str = "/ui"
        ui_tui_command: str | None = None
        ui_wallpaper: Literal["bing", "aurora", "none"] = "bing"
        ui_terminal_idle_timeout_s: int = 3600
        ui_terminal_max_sessions: int = 8
        ui_remote_request_timeout_s: int = 30

        # Optional agent MCP capability bridge. Skills use the fixed skills_list and
        # skill_load tools and are read from agent_config_dir/skills.
        agent_bridge_enabled: bool = False
        agent_mcp_probe_timeout_s: float = 5.0
        agent_mcp_call_timeout_s: float = 60.0
        agent_dynamic_mcp_tools: bool = False

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
        remote_max_pending_jobs: int = 256

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

        @field_validator("ui_path", mode="before")
        @classmethod
        def validate_ui_path(cls, value: str) -> str:
            return normalize_ui_path(value)

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
            updates = {}
            workspace_is_default = _matches_default_path(
                self.workspace_root, DEFAULT_WORKSPACE_ROOT
            )
            state_is_default = _matches_default_path(self.state_dir, DEFAULT_STATE_DIR)
            if state_is_default and not workspace_is_default:
                updates["state_dir"] = self.workspace_root / ".local-shell-mcp"
            state_dir = updates.get("state_dir", self.state_dir)
            if _matches_default_path(self.audit_log_path, DEFAULT_AUDIT_LOG_PATH):
                updates["audit_log_path"] = state_dir / "audit.jsonl"
            if _matches_default_path(self.agent_config_dir, DEFAULT_AGENT_CONFIG_DIR):
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
        max_skills: int = 256
        max_skill_related_files: int = 1_000
        max_skill_scan_entries: int = 5_000
        max_skill_path_bytes: int = 200_000
        max_read_many_files: int = 100
        max_read_many_total_bytes: int = 5_000_000
        max_todos: int = 1_000
        max_todo_bytes: int = 1_000_000
        max_job_log_bytes: int = 10_000_000
        max_audit_tail_bytes: int = 1_000_000
        max_audit_log_bytes: int = 20_000_000
        max_tmp_files: int = 500
        max_tmp_bytes: int = 50_000_000
        max_transfer_archive_entries: int = 100_000
        max_transfer_unpacked_bytes: int = 10_000_000_000
        max_concurrent_commands: int = 4
        max_tmux_sessions: int = 16

        ui_enabled: bool = True
        ui_path: str = "/ui"
        ui_tui_command: str | None = None
        ui_wallpaper: Literal["bing", "aurora", "none"] = "bing"
        ui_terminal_idle_timeout_s: int = 3600
        ui_terminal_max_sessions: int = 8
        ui_remote_request_timeout_s: int = 30

        agent_bridge_enabled: bool = False
        agent_mcp_probe_timeout_s: float = 5.0
        agent_mcp_call_timeout_s: float = 60.0
        agent_dynamic_mcp_tools: bool = False

        file_download_enabled: bool = True
        file_download_default_ttl_s: int = 3600
        file_download_max_ttl_s: int = 604800
        file_download_default_max_downloads: int = 0
        file_download_max_file_bytes: int = 0

        remote_enabled: bool = True
        remote_invite_ttl_s: int = 600
        remote_poll_timeout_s: int = 25
        remote_job_timeout_s: int = 3600
        remote_max_pending_jobs: int = 256

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
            self.ui_path = normalize_ui_path(self.ui_path)
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
            updates = {}
            workspace_is_default = _matches_default_path(
                self.workspace_root, DEFAULT_WORKSPACE_ROOT
            )
            state_is_default = _matches_default_path(self.state_dir, DEFAULT_STATE_DIR)
            if state_is_default and not workspace_is_default:
                updates["state_dir"] = self.workspace_root / ".local-shell-mcp"
            state_dir = updates.get("state_dir", self.state_dir)
            if _matches_default_path(self.audit_log_path, DEFAULT_AUDIT_LOG_PATH):
                updates["audit_log_path"] = state_dir / "audit.jsonl"
            if _matches_default_path(self.agent_config_dir, DEFAULT_AGENT_CONFIG_DIR):
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
    settings = _ensure_oauth_jwt_secret(settings)
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
    if settings.auth_mode != "oauth":
        return
    if (
        settings.oauth_jwt_secret in _WEAK_OAUTH_SECRET_VALUES
        or len(settings.oauth_jwt_secret.encode("utf-8")) < 32
    ):
        raise RuntimeError(
            "LOCAL_SHELL_MCP_OAUTH_JWT_SECRET must be at least 32 bytes of strong random data "
            "when OAuth authentication is enabled."
        )
    if not settings.public_base_url:
        return
    pin = (settings.oauth_admin_pin or "").strip()
    weak_pin_values = {"", "change-me", "change-me-long-random-pin"}
    if pin in weak_pin_values or len(pin) < 12:
        raise RuntimeError(
            "LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN must be set to a non-placeholder value of at least 12 characters "
            "when LOCAL_SHELL_MCP_PUBLIC_BASE_URL is configured."
        )
