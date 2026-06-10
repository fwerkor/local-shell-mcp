"""Load agent bridge manifests, scan local skills, probe configured MCP servers, and assemble redacted dynamic tool registries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import re
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SENSITIVE_KEY_PATTERN = (
    r"(?:authorization|cookie|credentials?|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"token|secret|password|passwd)"
)
SENSITIVE_KEY_RE = re.compile(SENSITIVE_KEY_PATTERN, re.I)
SENSITIVE_ARG_RE = re.compile(
    rf"(?P<prefix>--?[A-Za-z0-9_.-]*{SENSITIVE_KEY_PATTERN}[A-Za-z0-9_.-]*=)\S+",
    re.I,
)
SENSITIVE_SPACED_ARG_RE = re.compile(
    rf"(?P<prefix>(?:^|\s)--?[A-Za-z0-9_.-]*{SENSITIVE_KEY_PATTERN}"
    rf"[A-Za-z0-9_.-]*\s+)\S+",
    re.I,
)
SENSITIVE_FLAG_RE = re.compile(
    rf"^--?[A-Za-z0-9_.-]*{SENSITIVE_KEY_PATTERN}[A-Za-z0-9_.-]*$",
    re.I,
)
TEXT_SENSITIVE_KEY_PATTERN = (
    r"(?:[A-Za-z0-9_.-]*(?:authorization|cookie|credentials?|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|token|secret|password|passwd)[A-Za-z0-9_.-]*|key)"
)
SENSITIVE_TEXT_QUOTED_VALUE_RE = re.compile(
    rf"(?P<prefix>(?<![A-Za-z0-9_.-])(?P<key_quote>['\"]?)"
    rf"{TEXT_SENSITIVE_KEY_PATTERN}(?P=key_quote)\s*[:=]\s*)"
    r"(?P<value_quote>['\"])(?P<value>[^'\"]*)(?P=value_quote)",
    re.I,
)
SENSITIVE_TEXT_UNQUOTED_VALUE_RE = re.compile(
    rf"(?P<prefix>(?<![A-Za-z0-9_.-])(?P<key_quote>['\"]?)"
    rf"{TEXT_SENSITIVE_KEY_PATTERN}(?P=key_quote)\s*[:=]\s*)"
    r"(?P<value>[^\s,;'\"\)\}\]\n][^,;'\"\)\}\]\n]*)",
    re.I,
)
SENSITIVE_HEADER_VALUE_RE = re.compile(
    r"(?P<prefix>(?<![A-Za-z0-9_.-])(?P<key_quote>['\"]?)"
    r"(?:authorization|proxy-authorization|cookie|set-cookie)(?P=key_quote)"
    r"[^\S\r\n]*:[^\S\r\n]*)"
    r"(?P<value>[^'\"\r\n][^\r\n]*)",
    re.I,
)
SENSITIVE_QUOTED_ARG_LIST_RE = re.compile(
    rf"(?P<prefix>(?P<flag_quote>['\"])--?[A-Za-z0-9_.-]*"
    rf"{SENSITIVE_KEY_PATTERN}[A-Za-z0-9_.-]*(?P=flag_quote)\s*,\s*"
    r"(?P<value_quote>['\"]))(?P<value>[^'\"]*)(?P=value_quote)",
    re.I,
)
BEARER_TOKEN_RE = re.compile(r"\bBearer\s+[^\s,;'\"\)\}\]]+", re.I)
HIGH_CONFIDENCE_TOKEN_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16})\b"
)
URL_USERINFO_PASSWORD_RE = re.compile(r"(?P<prefix>https?://[^/\s:@?#]+:)[^@/\s?#]+(?=@)", re.I)
URL_QUERY_RE = re.compile(r"(?P<prefix>https?://[^\s?]+)\?[^\s\"')]+", re.I)


class AgentMcpServerConfig(BaseModel):
    """Configuration for one upstream MCP server exposed through the agent bridge."""

    type: Literal["stdio", "http", "sse"]
    enabled: bool = True
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

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


class AgentSkillsConfig(BaseModel):
    """Configuration for loading Markdown-based agent skills from the agent config directory."""

    enabled: bool = True
    directory: str = "skills"


class AgentDynamicToolsConfig(BaseModel):
    """Feature flags that control whether discovered skills and MCP tools become dynamic public tools."""

    mcp: bool = True
    skills: bool = True


class AgentBridgeManifest(BaseModel):
    """Validated bridge manifest describing upstream MCP servers, skill discovery, and dynamic-tool settings."""

    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    mcp_servers: dict[str, AgentMcpServerConfig] = Field(default_factory=dict, alias="mcpServers")
    skills: AgentSkillsConfig = Field(default_factory=AgentSkillsConfig)
    dynamic_tools: AgentDynamicToolsConfig = Field(
        default_factory=AgentDynamicToolsConfig, alias="dynamicTools"
    )

    @field_validator("version")
    @classmethod
    def supported_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("version must be 1")
        return value


@dataclass(frozen=True)
class LoadedAgentManifest:
    """Manifest load result that keeps missing or invalid configuration visible without aborting startup."""

    config_path: Path
    status: Literal["missing_config", "invalid_config", "loaded"]
    data: AgentBridgeManifest = field(default_factory=AgentBridgeManifest)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillRecord:
    """Resolved skill metadata used to activate a Markdown skill and expose it as a dynamic tool."""

    name: str
    entry_path: str
    description: str
    related_files: list[str]


@dataclass(frozen=True)
class SkillScanResult:
    """Skill discovery result containing accepted skill records and warnings for ignored entries."""

    skills: dict[str, SkillRecord] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentMcpServerRecord:
    """Probe result for one configured upstream MCP server, including available tools or a redacted error."""

    name: str
    config: AgentMcpServerConfig
    available: bool
    tools: list[Any] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class DynamicSkillToolRecord:
    """Association between a generated tool name and the skill it activates."""

    dynamic_name: str
    skill_name: str


@dataclass(frozen=True)
class DynamicMcpToolRecord:
    """Association between a generated public tool name and an upstream MCP server tool."""

    dynamic_name: str
    server_name: str
    tool_name: str


@dataclass(frozen=True)
class AgentCapabilityRegistry:
    """Snapshot of the bridge configuration, discovered skills, probed servers, and dynamic-tool maps."""

    config_dir: Path
    config_path: Path
    manifest_status: str
    manifest_errors: list[str]
    skills: dict[str, SkillRecord]
    skill_warnings: list[str]
    mcp_servers: dict[str, AgentMcpServerRecord]
    dynamic_mcp_tools: bool
    dynamic_skill_tools: bool
    dynamic_skill_tool_map: dict[str, DynamicSkillToolRecord]
    dynamic_mcp_tool_map: dict[str, DynamicMcpToolRecord]
    client_manager: Any

    def config_status(self) -> dict[str, Any]:
        """Return a redacted status payload suitable for diagnostics and public tool responses."""
        return {
            "config_dir": str(self.config_dir),
            "config_path": str(self.config_path),
            "manifest_status": self.manifest_status,
            "manifest_errors": self.manifest_errors,
            "skills": {"count": len(self.skills), "warnings": self.skill_warnings},
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
                    "env": {str(key): "<redacted>" for key in record.config.env},
                    "headers": {str(key): "<redacted>" for key in record.config.headers},
                }
                for name, record in self.mcp_servers.items()
            },
            "dynamic_tools": {
                "mcp": self.dynamic_mcp_tools,
                "skills": self.dynamic_skill_tools,
            },
        }


def _relative_posix(base: Path, path: Path) -> str:
    """Render a path relative to a base directory using POSIX separators for stable manifest output."""
    return path.resolve().relative_to(base.resolve()).as_posix()


def _is_relative_child_path(value: Path) -> bool:
    """Accept only relative child paths so skill manifests cannot reference arbitrary filesystem locations."""
    return not value.is_absolute() and ".." not in value.parts


def _first_sentence(value: str) -> str:
    """Extract the first prose sentence used as a compact skill or tool description."""
    match = re.match(r"(.+?[.!?])(?:\s|$)", value)
    if match:
        return match.group(1)
    return value


def _description_value(line: str) -> str | None:
    """Parse a front-matter description field from a Markdown skill file."""
    key, separator, value = line.strip().partition(":")
    if separator and key.strip().lower() == "description":
        return value.strip().strip("'\"") or "Agent skill"
    return None


def _skill_description(markdown: str) -> str:
    """Derive a human-readable skill description from front matter, heading text, or body prose."""
    lines = markdown.splitlines()
    line_index = 0
    while line_index < len(lines) and not lines[line_index].strip():
        line_index += 1

    if line_index < len(lines) and lines[line_index].strip() in {"---", "+++"}:
        delimiter = lines[line_index].strip()
        line_index += 1
        while line_index < len(lines):
            stripped = lines[line_index].strip()
            if stripped in {delimiter, "..."}:
                line_index += 1
                break
            description = _description_value(lines[line_index])
            if description is not None:
                return description
            line_index += 1

    in_code_fence = False
    for line in lines[line_index:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped in {"---", "...", "+++"} or stripped.startswith("#"):
            continue
        return _first_sentence(stripped)
    return "Agent skill"


def scan_agent_skills(config_dir: Path, directory: str = "skills") -> SkillScanResult:
    """Discover valid Markdown skill files, resolve related files, and report unsafe or malformed entries as warnings."""
    try:
        config_root = config_dir.resolve()
    except (OSError, RuntimeError) as exc:
        return SkillScanResult(warnings=[f"Could not scan skills directory {directory}: {exc}"])
    directory_path = Path(directory)
    if not _is_relative_child_path(directory_path):
        return SkillScanResult(
            warnings=[f"Skills directory must be inside config directory: {directory}"]
        )

    try:
        skills_dir = (config_root / directory_path).resolve()
    except (OSError, RuntimeError) as exc:
        return SkillScanResult(warnings=[f"Could not scan skills directory {directory}: {exc}"])
    if not skills_dir.is_relative_to(config_root):
        return SkillScanResult(
            warnings=[f"Skills directory must be inside config directory: {directory}"]
        )
    try:
        skills_dir_exists = skills_dir.exists()
    except OSError as exc:
        return SkillScanResult(warnings=[f"Could not scan skills directory {directory}: {exc}"])
    if not skills_dir_exists:
        return SkillScanResult(warnings=[f"Skills directory not found: {directory}"])

    skills: dict[str, SkillRecord] = {}
    warnings: list[str] = []
    try:
        children = sorted(skills_dir.iterdir(), key=lambda candidate: candidate.name)
    except OSError as exc:
        return SkillScanResult(warnings=[f"Could not scan skills directory {directory}: {exc}"])

    for child in children:
        try:
            if not child.is_dir():
                continue
            if child.is_symlink():
                warnings.append(f"Skipping skill {child.name}: skill directory is a symlink")
                continue
            skill_root = child.resolve()
            if not skill_root.is_relative_to(config_root):
                warnings.append(
                    f"Skipping skill {child.name}: skill directory must be inside config directory"
                )
                continue
            entry_path = child / "SKILL.md"
            if entry_path.is_symlink():
                warnings.append(
                    f"Skipping skill {child.name}: "
                    "SKILL.md must be a regular file inside the skill directory"
                )
                continue
            if not entry_path.is_file():
                warnings.append(f"Skipping skill {child.name}: missing SKILL.md")
                continue
            if not entry_path.resolve().is_relative_to(skill_root):
                warnings.append(
                    f"Skipping skill {child.name}: SKILL.md must be inside the skill directory"
                )
                continue
            markdown = entry_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"Skipping skill {child.name}: {exc}")
            continue

        related_files: list[str] = []
        try:
            for related_path in child.rglob("*"):
                try:
                    if not related_path.is_file():
                        continue
                    if related_path.is_symlink() or not related_path.resolve().is_relative_to(
                        skill_root
                    ):
                        warnings.append(
                            f"Skipping related file "
                            f"{related_path.relative_to(config_root).as_posix()}: "
                            "file must be inside the skill directory"
                        )
                        continue
                    related_files.append(_relative_posix(config_root, related_path))
                except OSError as exc:
                    try:
                        related_display = related_path.relative_to(config_root).as_posix()
                    except ValueError:
                        related_display = str(related_path)
                    warnings.append(f"Skipping related file {related_display}: {exc}")
        except OSError as exc:
            warnings.append(f"Skipping related files for skill {child.name}: {exc}")

        skills[child.name] = SkillRecord(
            name=child.name,
            entry_path=_relative_posix(config_root, entry_path),
            description=_skill_description(markdown),
            related_files=sorted(related_files),
        )
    return SkillScanResult(skills=skills, warnings=warnings)


def activate_skill(config_dir: Path, skill: SkillRecord) -> dict[str, Any]:
    """Load a skill entry point and related files into a payload that an agent can use to execute the skill."""
    config_root = config_dir.resolve()
    entry_relative = Path(skill.entry_path)
    if not _is_relative_child_path(entry_relative):
        raise ValueError("Skill entry path must be inside config directory")
    entry_path = config_root / entry_relative
    skill_root = entry_path.parent.resolve()
    if entry_path.is_symlink() or not entry_path.is_file():
        raise ValueError("Skill entry path must be a regular file")
    entry_resolved = entry_path.resolve()
    if not entry_resolved.is_relative_to(config_root):
        raise ValueError("Skill entry path must be inside config directory")
    if not entry_resolved.is_relative_to(skill_root):
        raise ValueError("Skill entry path must be inside the skill directory")
    content = entry_path.read_text(encoding="utf-8", errors="replace")
    return {
        "name": skill.name,
        "entry_path": skill.entry_path,
        "description": skill.description,
        "content": content,
        "related_files": list(skill.related_files),
    }


def _sanitize_name(value: str) -> str:
    """Convert arbitrary server, skill, or tool names into safe lowercase fragments for generated tool names."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_").lower()
    return sanitized or "unnamed"


def make_unique_tool_name(prefix: str, raw_name: str, seen: set[str]) -> str:
    """Create a collision-free public tool name from a prefix and upstream name."""
    base_name = f"{_sanitize_name(prefix)}__{_sanitize_name(raw_name)}"
    candidate = base_name
    if candidate in seen:
        digest = hashlib.sha1(raw_name.encode("utf-8")).hexdigest()[:8]
        candidate = f"{base_name}__{digest}"
        counter = 2
        while candidate in seen:
            candidate = f"{base_name}__{digest}_{counter}"
            counter += 1
    seen.add(candidate)
    return candidate


def redact_mapping(value: Any) -> Any:
    """Recursively redact mapping values whose keys are likely to contain credentials."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = redact_mapping(child)
        return result
    if isinstance(value, list):
        list_result: list[Any] = []
        redact_next = False
        for item in value:
            if redact_next:
                list_result.append("<redacted>")
                redact_next = False
                continue
            list_result.append(redact_mapping(item))
            if isinstance(item, str) and SENSITIVE_FLAG_RE.fullmatch(item):
                redact_next = True
        return list_result
    if isinstance(value, str):
        redacted = SENSITIVE_ARG_RE.sub(r"\g<prefix><redacted>", value)
        return SENSITIVE_SPACED_ARG_RE.sub(r"\g<prefix><redacted>", redacted)
    return value


def _redact_text(value: str) -> str:
    """Mask credential-like tokens in free-form text before returning diagnostics or errors."""
    redacted = redact_mapping(value)
    redacted = SENSITIVE_QUOTED_ARG_LIST_RE.sub(
        lambda match: f"{match.group('prefix')}<redacted>{match.group('value_quote')}",
        redacted,
    )
    redacted = BEARER_TOKEN_RE.sub("Bearer <redacted>", redacted)
    redacted = HIGH_CONFIDENCE_TOKEN_RE.sub("<redacted>", redacted)
    redacted = URL_USERINFO_PASSWORD_RE.sub(r"\g<prefix><redacted>", redacted)
    redacted = URL_QUERY_RE.sub(r"\g<prefix>?<redacted>", redacted)
    redacted = SENSITIVE_HEADER_VALUE_RE.sub(
        lambda match: f"{match.group('prefix')}<redacted>",
        redacted,
    )
    redacted = SENSITIVE_TEXT_QUOTED_VALUE_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('value_quote')}"
            f"<redacted>{match.group('value_quote')}"
        ),
        redacted,
    )
    return SENSITIVE_TEXT_UNQUOTED_VALUE_RE.sub(
        lambda match: f"{match.group('prefix')}<redacted>",
        redacted,
    )


def _configured_value_variants(value: str) -> set[str]:
    """Build literal and URL-decoded variants of configured secrets so all common renderings can be redacted."""
    variants = {value}
    for serialized in (repr(value), json.dumps(value), json.dumps(value, ensure_ascii=False)):
        variants.add(serialized)
        if len(serialized) >= 2 and serialized[0] == serialized[-1] and serialized[0] in {"'", '"'}:
            variants.add(serialized[1:-1])
    return {variant for variant in variants if variant}


def redact_configured_values(text: str, *maps: dict[str, str]) -> str:
    """Replace configured environment and header values wherever they appear in text."""
    redacted = text
    values = {
        variant
        for mapping in maps
        for value in mapping.values()
        if value
        for variant in _configured_value_variants(value)
    }
    for value in sorted(values, key=lambda item: (-len(item), item)):
        redacted = redacted.replace(value, "<redacted>")
    return redacted


def redact_configured_value_tree(value: Any, *maps: dict[str, str]) -> Any:
    """Apply configured-value and key-based redaction across nested response structures."""
    if isinstance(value, dict):
        return {
            _redact_text(redact_configured_values(str(key), *maps)): redact_configured_value_tree(
                child, *maps
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_configured_value_tree(item, *maps) for item in value]
    if isinstance(value, str):
        return _redact_text(redact_configured_values(value, *maps))
    return value


def agent_config_fingerprint(config_dir: Path) -> str:
    """Return a stable content fingerprint for the injected agent config tree."""

    root = Path(config_dir)
    digest = hashlib.sha256()

    def update(*parts: object) -> None:
        for part in parts:
            digest.update(str(part).encode("utf-8", errors="replace"))
            digest.update(b"\0")

    def relative_path(path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    def update_path(path: Path, relative: str) -> None:
        try:
            file_stat = path.lstat()
        except OSError as exc:
            update(relative, "stat_error", type(exc).__name__, exc)
            return

        mode = file_stat.st_mode
        update(relative, stat.S_IFMT(mode), file_stat.st_size, file_stat.st_mtime_ns)
        if stat.S_ISLNK(mode):
            try:
                update("link", os.readlink(path))
            except OSError as exc:
                update("link_error", type(exc).__name__, exc)
            return
        if not stat.S_ISREG(mode):
            return

        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        except OSError as exc:
            update("read_error", type(exc).__name__, exc)

    update_path(root, ".")
    try:
        root_stat = root.lstat()
    except OSError:
        return digest.hexdigest()
    if not stat.S_ISDIR(root_stat.st_mode):
        return digest.hexdigest()

    walk_errors: list[OSError] = []

    def on_walk_error(exc: OSError) -> None:
        walk_errors.append(exc)

    for current, dirnames, filenames in os.walk(root, topdown=True, onerror=on_walk_error):
        dirnames.sort()
        filenames.sort()
        current_path = Path(current)

        for dirname in list(dirnames):
            child = current_path / dirname
            update_path(child, relative_path(child))
            try:
                if child.is_symlink():
                    dirnames.remove(dirname)
            except OSError:
                dirnames.remove(dirname)

        for filename in filenames:
            child = current_path / filename
            update_path(child, relative_path(child))

    for error in walk_errors:
        update("walk_error", type(error).__name__, error)

    return digest.hexdigest()


def load_agent_manifest(config_dir: Path) -> LoadedAgentManifest:
    """Read and validate the bridge manifest while preserving structured errors for status reporting."""
    config_path = config_dir / "config.json"
    if not config_path.exists():
        return LoadedAgentManifest(config_path=config_path, status="missing_config")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        data = AgentBridgeManifest.model_validate(raw)
    except ValidationError as exc:
        return LoadedAgentManifest(
            config_path=config_path,
            status="invalid_config",
            errors=[str(error) for error in exc.errors(include_input=False)],
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return LoadedAgentManifest(
            config_path=config_path,
            status="invalid_config",
            errors=[str(exc)],
        )
    return LoadedAgentManifest(config_path=config_path, status="loaded", data=data)


def _run_async_blocking(coro: Any, timeout_s: float | None = None) -> Any:
    """Run an async probe from synchronous registry-building code with a bounded timeout."""
    if timeout_s is None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result_queue.put((True, asyncio.run(coro)))
        except BaseException as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        if timeout_s is None:
            success, result = result_queue.get()
        else:
            success, result = result_queue.get(timeout=timeout_s)
    except queue.Empty:
        raise TimeoutError(f"operation timed out after {timeout_s:g}s") from None
    if success:
        return result
    raise result


def _probe_timeout_seconds(probe_timeout_s: float) -> float:
    """Clamp the MCP probe timeout to a positive value before probing upstream servers."""
    return max(0.001, probe_timeout_s)


def build_agent_registry(
    config_dir: Path,
    client_manager: Any | None = None,
    probe_timeout_s: float = 5,
    dynamic_mcp_tools: bool | None = None,
    dynamic_skill_tools: bool | None = None,
) -> AgentCapabilityRegistry:
    """Build a complete bridge registry by loading config, scanning skills, probing MCP servers, and assigning dynamic names."""
    config_root = Path(config_dir)
    manifest = load_agent_manifest(config_root)
    probe_timeout = _probe_timeout_seconds(probe_timeout_s)
    if client_manager is None:
        from .agent_mcp import AgentMcpClientManager

        client_manager = AgentMcpClientManager(call_timeout_s=probe_timeout)

    skill_scan = SkillScanResult()
    mcp_servers: dict[str, AgentMcpServerRecord] = {}
    if manifest.status == "loaded":
        if manifest.data.skills.enabled:
            skill_scan = scan_agent_skills(config_root, manifest.data.skills.directory)

        for name, server in manifest.data.mcp_servers.items():
            if not server.enabled:
                mcp_servers[name] = AgentMcpServerRecord(
                    name=name,
                    config=server,
                    available=False,
                    error="disabled",
                )
                continue

            try:
                tools = _run_async_blocking(
                    asyncio.wait_for(
                        client_manager.list_tools(name, server),
                        timeout=probe_timeout,
                    ),
                    timeout_s=probe_timeout,
                )
            except Exception as exc:
                mcp_servers[name] = AgentMcpServerRecord(
                    name=name,
                    config=server,
                    available=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
                continue

            mcp_servers[name] = AgentMcpServerRecord(
                name=name,
                config=server,
                available=True,
                tools=tools,
            )

    effective_dynamic_skills = (
        manifest.data.dynamic_tools.skills if dynamic_skill_tools is None else dynamic_skill_tools
    )
    effective_dynamic_mcp = (
        manifest.data.dynamic_tools.mcp if dynamic_mcp_tools is None else dynamic_mcp_tools
    )

    seen_names: set[str] = set()
    skill_tool_map: dict[str, DynamicSkillToolRecord] = {}
    if effective_dynamic_skills:
        for skill_name in skill_scan.skills:
            dynamic_name = make_unique_tool_name("activate_skill", skill_name, seen_names)
            skill_tool_map[dynamic_name] = DynamicSkillToolRecord(dynamic_name, skill_name)

    mcp_tool_map: dict[str, DynamicMcpToolRecord] = {}
    if effective_dynamic_mcp:
        for server_name, record in mcp_servers.items():
            if not record.available:
                continue
            for tool in record.tools:
                display_server_name = str(
                    redact_configured_value_tree(
                        server_name,
                        record.config.env,
                        record.config.headers,
                    )
                )
                display_tool_name = str(
                    redact_configured_value_tree(
                        tool.name,
                        record.config.env,
                        record.config.headers,
                    )
                )
                dynamic_name = make_unique_tool_name(
                    f"agent_mcp__{display_server_name}", display_tool_name, seen_names
                )
                mcp_tool_map[dynamic_name] = DynamicMcpToolRecord(
                    dynamic_name, server_name, tool.name
                )

    return AgentCapabilityRegistry(
        config_dir=config_root,
        config_path=manifest.config_path,
        manifest_status=manifest.status,
        manifest_errors=manifest.errors,
        skills=skill_scan.skills,
        skill_warnings=skill_scan.warnings,
        mcp_servers=mcp_servers,
        dynamic_mcp_tools=effective_dynamic_mcp,
        dynamic_skill_tools=effective_dynamic_skills,
        dynamic_skill_tool_map=skill_tool_map,
        dynamic_mcp_tool_map=mcp_tool_map,
        client_manager=client_manager,
    )
