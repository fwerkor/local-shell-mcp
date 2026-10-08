from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from edge_case_support import _MemoryStateStore

import local_shell_mcp.dynamic_mcp as dynamic_mcp


def test_dynamic_mcp_memory_load_save_and_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = SimpleNamespace(state_backend="memory", disable_local=False)
    monkeypatch.setattr(dynamic_mcp, "get_settings", lambda: settings)
    store = _MemoryStateStore()
    monkeypatch.setattr(dynamic_mcp, "get_state_store", lambda: store)
    monkeypatch.setattr(dynamic_mcp, "resolve_path", lambda path: tmp_path)
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)

    assert manager._load() == {}
    payload = {
        "version": dynamic_mcp._REGISTRY_VERSION,
        "servers": [
            "bad",
            {
                "name": "stdio",
                "transport": "stdio",
                "command": "tool",
                "cwd": None,
            },
        ],
    }
    store.values["dynamic-mcp.json"] = __import__("json").dumps(payload).encode()
    loaded = manager._load()
    assert loaded["stdio"].cwd == str(tmp_path)
    manager._save(loaded)
    assert store.values["dynamic-mcp.json"].endswith(b"\n")

    with pytest.raises(ValueError, match="url is only valid"):
        manager._validate_config(
            dynamic_mcp.DynamicMCPServer(
                name="bad", transport="stdio", command="tool", url="https://example"
            )
        )

@pytest.mark.asyncio
async def test_dynamic_mcp_search_scoring_and_disabled_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)
    enabled = dynamic_mcp.DynamicMCPServer(
        name="alpha",
        transport="streamable_http",
        url="https://example",
        tools=[
            {"name": "find", "title": "Search Docs", "description": "lookup"},
            {"name": "other", "title": "Misc", "description": "search docs"},
        ],
    )
    empty = dynamic_mcp.DynamicMCPServer(
        name="empty", transport="streamable_http", url="https://empty", tools=[]
    )
    disabled = dynamic_mcp.DynamicMCPServer(
        name="off",
        transport="streamable_http",
        url="https://off",
        enabled=False,
        tools=[{"name": "hidden"}],
    )
    monkeypatch.setattr(
        manager, "_load", lambda: {"alpha": enabled, "empty": empty, "off": disabled}
    )
    result = await manager.search("search docs")
    assert [item["name"] for item in result["tools"]] == ["alpha:find", "alpha:other"]
    assert result["unrefreshed_servers"] == ["empty"]
    assert (await manager.search("", server="off"))["count"] == 0
    with pytest.raises(ValueError, match="unknown"):
        await manager.search("", server="missing")

@pytest.mark.asyncio
async def test_dynamic_mcp_local_disable_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)
    server = dynamic_mcp.DynamicMCPServer(
        name="stdio",
        transport="stdio",
        command="tool",
        tools=[{"name": "run"}],
    )
    monkeypatch.setattr(manager, "_load", lambda: {"stdio": server})
    monkeypatch.setattr(
        dynamic_mcp,
        "get_settings",
        lambda: SimpleNamespace(disable_local=True),
    )
    with pytest.raises(ValueError, match="local access is disabled"):
        await manager.refresh("stdio")
    with pytest.raises(ValueError, match="local access is disabled"):
        await manager.call("stdio:run")

@pytest.mark.asyncio
async def test_dynamic_mcp_search_filter_and_inspect_continuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)
    server = dynamic_mcp.DynamicMCPServer(
        name="alpha",
        transport="streamable_http",
        url="https://example",
        tools=[{"name": "first"}, {"name": "second", "description": "target"}],
    )
    monkeypatch.setattr(manager, "_load", lambda: {"alpha": server})
    assert (await manager.search("not-present"))["count"] == 0
    inspected = await manager.inspect("alpha:second")
    assert inspected["tool"]["name"] == "second"
