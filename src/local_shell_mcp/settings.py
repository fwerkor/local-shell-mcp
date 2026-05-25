from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_WORKSPACE_ROOT = Path("/workspace")
DEFAULT_STATE_DIR = DEFAULT_WORKSPACE_ROOT / ".local-shell-mcp"
DEFAULT_AUDIT_LOG_PATH = DEFAULT_STATE_DIR / "audit.jsonl"


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


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

    # By default, tools are limited to workspace_root. Set true only inside a disposable container.
    allow_full_container: bool = False
    allow_network: bool = True

    default_timeout_s: int = 60
    max_timeout_s: int = 3600
    max_output_bytes: int = 200_000
    max_file_read_bytes: int = 512_000
    max_file_write_bytes: int = 5_000_000
    max_grep_results: int = 200

    shell_executable: str = "/bin/bash"
    tmux_bin: str = "tmux"
    rg_bin: str = "rg"
    git_bin: str = "git"
    python_bin: str = "python3"

    # Authentication. OAuth is the default for ChatGPT custom connectors.
    # "cloudflare_access" is kept for legacy deployments only.
    auth_mode: Literal["none", "oauth", "cloudflare_access"] = "oauth"
    cf_access_team_domain: str | None = None  # e.g. your-team.cloudflareaccess.com
    cf_access_audience: str | None = None
    cf_access_allowed_emails: list[str] = Field(default_factory=list)
    cf_access_allowed_email_domains: list[str] = Field(default_factory=list)
    auth_bypass_localhost: bool = True
    require_auth_for_mcp_discovery: bool = False

    # Built-in OAuth 2.1 authorization server for ChatGPT MCP connectors.
    # Set public_base_url to the externally reachable HTTPS origin, e.g. https://local-shell-mcp.example.com
    public_base_url: str | None = None
    oauth_issuer: str | None = None
    oauth_resource: str | None = None
    oauth_admin_pin: str | None = None
    oauth_jwt_secret: str = Field(default_factory=lambda: os.getenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET") or "dev-change-me")
    oauth_access_token_ttl_s: int = 8 * 3600
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

    @field_validator("workspace_root", "audit_log_path", "state_dir", mode="before")
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()

    @field_validator("cf_access_allowed_emails", "cf_access_allowed_email_domains", "command_denylist", "path_denylist", mode="before")
    @classmethod
    def split_csv_fields(cls, value):  # noqa: ANN001
        return _split_csv(value)

    def apply_yaml(self, path: Path) -> Settings:
        if not path.exists():
            raise FileNotFoundError(path)
        data = yaml.safe_load(path.read_text()) or {}
        flat = {}
        for key, value in data.items():
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    flat[f"{key}_{child_key}"] = child_value
            else:
                flat[key] = value
        merged = self.model_dump()
        merged.update(flat)
        return Settings(**merged)

    def with_workspace_relative_defaults(self) -> Settings:
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
    return settings
