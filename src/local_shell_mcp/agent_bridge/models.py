"""Agent bridge configuration and registry data models."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentMcpServerConfig(BaseModel):
    """Configuration for one upstream MCP server exposed through the agent bridge."""

    type: Literal["stdio", "http", "sse"]
    """Transport type used to connect to the upstream MCP server."""
    enabled: bool = True
    """Whether this upstream server should be probed and exposed."""
    command: str | None = None
    """Executable command for stdio MCP servers."""
    args: list[str] = Field(default_factory=list)
    """Command-line arguments passed to a stdio MCP server."""
    env: dict[str, str] = Field(default_factory=dict)
    """Environment variables injected into a stdio MCP server process."""
    url: str | None = None
    """HTTP or SSE endpoint URL for network MCP servers."""
    headers: dict[str, str] = Field(default_factory=dict)
    """HTTP headers sent when connecting to network MCP servers."""

    @field_validator("command")
    @classmethod
    def non_empty_command(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("command must not be empty")
        return value

    @field_validator("url")
    @classmethod
    def non_empty_url(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("url must not be empty")
        return value


class AgentDynamicToolsConfig(BaseModel):
    """Feature flags for exposing discovered upstream MCP capabilities as public tools."""

    mcp: bool = True
    """Whether discovered upstream MCP tools become public dynamic tools."""


class AgentBridgeManifest(BaseModel):
    """Validated bridge manifest."""

    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    """Manifest schema version supported by this bridge loader."""
    mcp_servers: dict[str, AgentMcpServerConfig] = Field(
        default_factory=dict, alias="mcpServers"
    )
    """Named upstream MCP server configurations."""
    dynamic_tools: AgentDynamicToolsConfig = Field(
        default_factory=AgentDynamicToolsConfig, alias="dynamicTools"
    )
    """Dynamic tool exposure settings for discovered capabilities."""

    @field_validator("version")
    @classmethod
    def supported_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("version must be 1")
        return value


@dataclass(frozen=True)
class LoadedAgentManifest:
    """Manifest load result."""

    config_path: Path
    """Path to the bridge manifest file."""
    status: Literal["missing_config", "invalid_config", "loaded"]
    """Load status for missing, invalid, or successfully parsed config."""
    data: AgentBridgeManifest = field(default_factory=AgentBridgeManifest)
    """Parsed manifest data, or defaults when config is absent or invalid."""
    errors: list[str] = field(default_factory=list)
    """Validation or parse errors collected while loading the manifest."""


@dataclass(frozen=True)
class SkillRecord:
    """Resolved skill metadata."""

    name: str
    """Stable skill name derived from its directory."""
    entry_path: str
    """Path to the Markdown skill entry file."""
    description: str
    """Human-readable skill summary."""
    related_files: list[str]
    """Additional files related to the skill entry."""


@dataclass(frozen=True)
class SkillScanResult:
    """Skill discovery result."""

    skills: dict[str, SkillRecord] = field(default_factory=dict)
    """Accepted skills keyed by skill name."""
    warnings: list[str] = field(default_factory=list)
    """Non-fatal discovery warnings for ignored or invalid entries."""


@dataclass(frozen=True)
class AgentMcpServerRecord:
    """Probe result for one configured upstream MCP server."""

    name: str
    """Manifest key for the upstream MCP server."""
    config: AgentMcpServerConfig
    """Validated connection configuration for the server."""
    available: bool
    """Whether the server was reachable during probing."""
    tools: list[Any] = field(default_factory=list)
    """Normalized upstream tools discovered from the server."""
    error: str | None = None
    """Redacted probe error when the server is unavailable."""


@dataclass(frozen=True)
class DynamicMcpToolRecord:
    """Association between a generated public tool name and an upstream MCP server tool."""

    dynamic_name: str
    """Public dynamic tool name exposed by local-shell-mcp."""
    server_name: str
    """Manifest key for the upstream MCP server."""
    tool_name: str
    """Original upstream MCP tool name."""


@dataclass(frozen=True)
class AgentCapabilityRegistry:
    """Snapshot of discovered agent bridge capabilities."""

    config_dir: Path
    """Directory containing the bridge configuration."""
    config_path: Path
    """Path to the bridge manifest file."""
    manifest_status: str
    """Load status for the current manifest."""
    manifest_errors: list[str]
    """Validation or parse errors collected while loading."""
    mcp_servers: dict[str, AgentMcpServerRecord]
    """Probed upstream MCP servers keyed by manifest name."""
    dynamic_mcp_tools: bool
    """Whether dynamic MCP tool exposure is enabled."""
    dynamic_mcp_tool_map: dict[str, DynamicMcpToolRecord]
    """Public MCP tool names mapped to upstream tools."""
    client_manager: Any
    """MCP client-session manager used to call upstream tools."""

    def config_status(self) -> dict[str, Any]:
        """Return a redacted status payload suitable for diagnostics and public tool responses."""
        from .redaction import _redact_text, redact_configured_values

        return {
            "config_dir": str(self.config_dir),
            "config_path": str(self.config_path),
            "manifest_status": self.manifest_status,
            "manifest_errors": self.manifest_errors,
            "mcp_servers": {
                name: {
                    "type": record.config.type,
                    "enabled": record.config.enabled,
                    "available": record.available,
                    "tool_count": len(record.tools),
                    "error": (
                        _redact_text(
                            redact_configured_values(
                                record.error,
                                record.config.env,
                                record.config.headers,
                            )
                        )
                        if record.error
                        else None
                    ),
                    "env": {
                        str(key): "<redacted>" for key in record.config.env
                    },
                    "headers": {
                        str(key): "<redacted>" for key in record.config.headers
                    },
                }
                for name, record in self.mcp_servers.items()
            },
            "dynamic_tools": {"mcp": self.dynamic_mcp_tools},
        }
