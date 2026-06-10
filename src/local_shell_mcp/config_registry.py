"""Central registry for runtime configuration surfaces.

The settings registry is the single source of truth for application setting help
text, CLI flag registration, and generated example configuration files.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic.fields import PydanticUndefined

from .settings import ENV_PREFIX, Settings

SectionName = Literal[
    "Server",
    "Paths and state",
    "Authentication and OAuth",
    "Safety and resource limits",
    "Remote workers",
    "Agent capability bridge",
    "Tool executables",
]


@dataclass(frozen=True)
class SettingSpec:
    """Metadata for one application setting exposed through env, YAML, and CLI."""

    name: str
    section: SectionName
    help: str
    metavar: str | None = None
    example_default: Any | None = None

    @property
    def env_var(self) -> str:
        """Return the LOCAL_SHELL_MCP_* variable for this setting."""
        return f"{ENV_PREFIX}{self.name.upper()}"

    @property
    def cli_flag(self) -> str:
        """Return the canonical CLI flag for this setting."""
        return f"--{self.name.replace('_', '-')}"


SECTION_ORDER: tuple[SectionName, ...] = (
    "Server",
    "Paths and state",
    "Authentication and OAuth",
    "Safety and resource limits",
    "Remote workers",
    "Agent capability bridge",
    "Tool executables",
)

SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec("mode", "Server", "Server transport mode: mcp, http, stdio, or both.", "MODE"),
    SettingSpec("host", "Server", "Bind host for HTTP/MCP transports.", "HOST"),
    SettingSpec("port", "Server", "Bind port for HTTP/MCP transports.", "PORT"),
    SettingSpec(
        "workspace_root",
        "Paths and state",
        "Root directory for normal file and command operations.",
        "PATH",
    ),
    SettingSpec(
        "state_dir",
        "Paths and state",
        "Directory for runtime state such as audit logs and temporary files.",
        "PATH",
    ),
    SettingSpec("audit_log_path", "Paths and state", "Path to the JSONL audit log.", "PATH"),
    SettingSpec(
        "auth_mode",
        "Authentication and OAuth",
        "Authentication mode: oauth or none. Do not expose public services with none.",
        "MODE",
    ),
    SettingSpec(
        "auth_bypass_localhost",
        "Authentication and OAuth",
        "Allow localhost requests without bearer authentication.",
        "BOOL",
    ),
    SettingSpec(
        "require_auth_for_mcp_discovery",
        "Authentication and OAuth",
        "Require authentication for MCP initialize/list-tools discovery calls.",
        "BOOL",
    ),
    SettingSpec(
        "public_base_url",
        "Authentication and OAuth",
        "Public HTTPS origin used in OAuth metadata and callbacks.",
        "URL",
    ),
    SettingSpec(
        "oauth_issuer",
        "Authentication and OAuth",
        "Override OAuth issuer metadata; defaults to public_base_url when unset.",
        "URL",
    ),
    SettingSpec(
        "oauth_resource",
        "Authentication and OAuth",
        "Override OAuth resource metadata; defaults to public_base_url when unset.",
        "URL",
    ),
    SettingSpec(
        "oauth_admin_pin",
        "Authentication and OAuth",
        "PIN required to approve OAuth authorization.",
        "PIN",
    ),
    SettingSpec(
        "oauth_jwt_secret",
        "Authentication and OAuth",
        "Secret used to sign OAuth bearer tokens; set a strong random value.",
        "SECRET",
        "dev-change-me",
    ),
    SettingSpec(
        "oauth_access_token_ttl_s",
        "Authentication and OAuth",
        "Bearer token lifetime in seconds; 0 means no expiry.",
        "SECONDS",
    ),
    SettingSpec(
        "oauth_code_ttl_s",
        "Authentication and OAuth",
        "OAuth authorization-code lifetime in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "allow_full_container",
        "Safety and resource limits",
        "Disable built-in workspace and command restrictions; use only in disposable containers or VMs.",
        "BOOL",
    ),
    SettingSpec(
        "allow_network", "Safety and resource limits", "Allow network-capable operations.", "BOOL"
    ),
    SettingSpec(
        "default_timeout_s",
        "Safety and resource limits",
        "Default shell command timeout in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "max_timeout_s",
        "Safety and resource limits",
        "Maximum shell command timeout in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "max_output_bytes",
        "Safety and resource limits",
        "Command output truncation limit in bytes.",
        "BYTES",
    ),
    SettingSpec(
        "max_file_read_bytes",
        "Safety and resource limits",
        "Per-file read limit in bytes.",
        "BYTES",
    ),
    SettingSpec(
        "max_file_write_bytes",
        "Safety and resource limits",
        "Per-file write/edit limit in bytes.",
        "BYTES",
    ),
    SettingSpec(
        "max_grep_results", "Safety and resource limits", "Maximum grep result count.", "COUNT"
    ),
    SettingSpec(
        "max_directory_entries",
        "Safety and resource limits",
        "Maximum listed directory entries.",
        "COUNT",
    ),
    SettingSpec(
        "max_glob_results", "Safety and resource limits", "Maximum glob search results.", "COUNT"
    ),
    SettingSpec(
        "max_tree_entries", "Safety and resource limits", "Maximum tree-view entries.", "COUNT"
    ),
    SettingSpec(
        "max_read_many_files",
        "Safety and resource limits",
        "Maximum files read by a multi-file read operation.",
        "COUNT",
    ),
    SettingSpec(
        "max_read_many_total_bytes",
        "Safety and resource limits",
        "Combined byte limit for multi-file reads.",
        "BYTES",
    ),
    SettingSpec("max_todos", "Safety and resource limits", "Todo-list item limit.", "COUNT"),
    SettingSpec(
        "max_todo_bytes", "Safety and resource limits", "Todo-list serialized byte limit.", "BYTES"
    ),
    SettingSpec(
        "max_audit_tail_bytes",
        "Safety and resource limits",
        "Audit-tail response byte limit.",
        "BYTES",
    ),
    SettingSpec(
        "max_audit_log_bytes",
        "Safety and resource limits",
        "Audit-log rotation threshold in bytes.",
        "BYTES",
    ),
    SettingSpec(
        "max_tmp_files", "Safety and resource limits", "Temporary-file count limit.", "COUNT"
    ),
    SettingSpec(
        "max_tmp_bytes", "Safety and resource limits", "Temporary-file byte limit.", "BYTES"
    ),
    SettingSpec(
        "max_concurrent_commands",
        "Safety and resource limits",
        "Concurrent command limit.",
        "COUNT",
    ),
    SettingSpec(
        "max_tmux_sessions",
        "Safety and resource limits",
        "Persistent shell session limit.",
        "COUNT",
    ),
    SettingSpec(
        "command_denylist",
        "Safety and resource limits",
        "Comma-separated command denylist in env/CLI, or a YAML list in config files. Cleared when full-container mode is enabled.",
        "CSV",
    ),
    SettingSpec(
        "path_denylist",
        "Safety and resource limits",
        "Comma-separated path denylist in env/CLI, or a YAML list in config files. Cleared when full-container mode is enabled.",
        "CSV",
    ),
    SettingSpec(
        "remote_enabled", "Remote workers", "Enable remote worker routes and MCP tools.", "BOOL"
    ),
    SettingSpec(
        "remote_invite_ttl_s",
        "Remote workers",
        "One-time remote worker invite lifetime in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "remote_poll_timeout_s",
        "Remote workers",
        "Remote worker long-poll heartbeat timeout in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "remote_job_timeout_s",
        "Remote workers",
        "Control-side remote job result timeout in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "agent_bridge_enabled",
        "Agent capability bridge",
        "Enable agent capability bridge tools.",
        "BOOL",
    ),
    SettingSpec(
        "agent_config_dir",
        "Agent capability bridge",
        "Read-only capability config directory.",
        "PATH",
    ),
    SettingSpec(
        "agent_mcp_probe_timeout_s",
        "Agent capability bridge",
        "Agent MCP server probe timeout in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "agent_mcp_call_timeout_s",
        "Agent capability bridge",
        "Agent MCP tool-call timeout in seconds.",
        "SECONDS",
    ),
    SettingSpec(
        "agent_dynamic_mcp_tools",
        "Agent capability bridge",
        "Register dynamic MCP bridge tools.",
        "BOOL",
    ),
    SettingSpec(
        "agent_dynamic_skill_tools",
        "Agent capability bridge",
        "Register dynamic skill bridge tools.",
        "BOOL",
    ),
    SettingSpec(
        "shell_executable", "Tool executables", "Shell executable used for shell commands.", "PATH"
    ),
    SettingSpec("tmux_bin", "Tool executables", "tmux executable.", "PATH"),
    SettingSpec("rg_bin", "Tool executables", "ripgrep executable.", "PATH"),
    SettingSpec("git_bin", "Tool executables", "Git executable.", "PATH"),
    SettingSpec("python_bin", "Tool executables", "Python executable.", "PATH"),
)

SPECS_BY_NAME = {spec.name: spec for spec in SETTING_SPECS}

CONFIG_SPEC = SettingSpec(
    "config",
    "Server",
    "Path to optional YAML config file. This selects the config file and is not itself a Settings field.",
    "PATH",
)


def validate_setting_specs() -> None:
    """Ensure every Settings field has exactly one registry entry."""
    fields = set(Settings.model_fields)
    specs = set(SPECS_BY_NAME)
    missing = sorted(fields - specs)
    extra = sorted(specs - fields)
    if missing or extra:
        raise RuntimeError(f"Setting spec mismatch: missing={missing}, extra={extra}")


def default_value(name: str) -> Any:
    """Return the concrete default for a Settings field."""
    if (spec := SPECS_BY_NAME.get(name)) and spec.example_default is not None:
        return spec.example_default
    field = Settings.model_fields[name]
    if field.default is not PydanticUndefined:
        return field.default
    if field.default_factory is not None:
        return field.default_factory()
    return None


def default_to_string(value: Any) -> str:
    """Render a default value for documentation, .env files, and argparse help."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def yaml_default(value: Any) -> Any:
    """Render a default value suitable for YAML dumping."""
    if isinstance(value, Path):
        return str(value)
    return value


def argparse_type_for(name: str):  # noqa: ANN201
    """Return an argparse type callable for a Settings field."""
    annotation = Settings.model_fields[name].annotation
    if annotation is int:
        return int
    return str


def argparse_choices_for(name: str) -> tuple[str, ...] | None:
    """Return argparse choices for Literal settings."""
    annotation = Settings.model_fields[name].annotation
    if get_origin(annotation) is Literal:
        return tuple(str(item) for item in get_args(annotation))
    return None


def is_bool_setting(name: str) -> bool:
    """Return whether a Settings field is boolean."""
    return Settings.model_fields[name].annotation is bool


def register_setting_cli_args(parser: argparse.ArgumentParser) -> None:
    """Register one CLI option for every Settings field, grouped by section."""
    validate_setting_specs()
    for section in SECTION_ORDER:
        group = parser.add_argument_group(section)
        for spec in (item for item in SETTING_SPECS if item.section == section):
            kwargs: dict[str, Any] = {
                "dest": spec.name,
                "default": None,
                "help": f"{spec.help} Overrides {spec.env_var} and config files. Default: {default_to_string(default_value(spec.name)) or 'unset'}.",
            }
            if spec.metavar:
                kwargs["metavar"] = spec.metavar
            choices = argparse_choices_for(spec.name)
            if choices:
                kwargs["choices"] = choices
            if is_bool_setting(spec.name):
                kwargs.update({"type": _parse_bool})
            elif Settings.model_fields[spec.name].annotation is int:
                kwargs["type"] = int
            group.add_argument(spec.cli_flag, **kwargs)


def _parse_bool(value: str) -> bool:
    """Parse a boolean value for CLI settings."""
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected one of: true, false, yes, no, 1, 0, on, off")


def cli_overrides_from_args(args: argparse.Namespace) -> dict[str, object]:
    """Collect explicit CLI server options as Settings field overrides."""
    validate_setting_specs()
    return {
        spec.name: value
        for spec in SETTING_SPECS
        if (value := getattr(args, spec.name, None)) is not None
    }
