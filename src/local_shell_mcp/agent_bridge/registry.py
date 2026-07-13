"""Build agent bridge capability registries from manifests, skills, and MCP probes."""

import asyncio
import hashlib
import queue
import re
import threading
from pathlib import Path
from typing import Any

from .models import (
    AgentCapabilityRegistry,
    AgentMcpServerRecord,
    DynamicMcpToolRecord,
    SkillScanResult,
)
from .redaction import redact_configured_value_tree
from .skills import scan_agent_skills
from .state import load_agent_manifest


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
        raise TimeoutError(
            f"operation timed out after {timeout_s:g}s"
        ) from None
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
) -> AgentCapabilityRegistry:
    """Build a bridge registry by loading config, scanning skills, probing MCP servers, and assigning dynamic MCP names."""
    config_root = Path(config_dir)
    manifest = load_agent_manifest(config_root)
    probe_timeout = _probe_timeout_seconds(probe_timeout_s)
    if client_manager is None:
        from .mcp import AgentMcpClientManager

        client_manager = AgentMcpClientManager(call_timeout_s=probe_timeout)

    skill_scan = SkillScanResult()
    mcp_servers: dict[str, AgentMcpServerRecord] = {}
    if manifest.status == "loaded":
        if manifest.data.skills.enabled:
            skill_scan = scan_agent_skills(
                config_root, manifest.data.skills.directory
            )

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

    effective_dynamic_mcp = (
        manifest.data.dynamic_tools.mcp
        if dynamic_mcp_tools is None
        else dynamic_mcp_tools
    )

    seen_names: set[str] = set()
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
                    f"agent_mcp__{display_server_name}",
                    display_tool_name,
                    seen_names,
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
        dynamic_mcp_tool_map=mcp_tool_map,
        client_manager=client_manager,
    )
