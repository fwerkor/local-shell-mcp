from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_shell_mcp import tmux_helper
from local_shell_mcp.settings import get_settings


def test_platform_tag_normalizes_supported_linux_architectures(monkeypatch):
    monkeypatch.setattr(tmux_helper.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tmux_helper.platform, "machine", lambda: "AMD64")

    assert tmux_helper._platform_tag() == "linux-x86_64"

    monkeypatch.setattr(tmux_helper.platform, "machine", lambda: "arm64")
    assert tmux_helper._platform_tag() == "linux-aarch64"


def test_resolve_tmux_prefers_system_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(tmux_helper.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(tmux_helper, "bundled_tmux_path", lambda: Path("/bundled/tmux"))

    selection = tmux_helper.resolve_tmux()

    assert selection == tmux_helper.TmuxSelection("/usr/bin/tmux", "system")


def test_resolve_tmux_uses_bundled_helper_when_system_binary_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(tmux_helper.shutil, "which", lambda name: None)
    monkeypatch.setattr(tmux_helper, "bundled_tmux_path", lambda: Path("/bundled/tmux"))

    selection = tmux_helper.resolve_tmux()

    assert selection == tmux_helper.TmuxSelection("/bundled/tmux", "bundled")


def test_backend_info_reports_native_fallback(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Unix backend selection test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(
        tmux_helper,
        "resolve_tmux",
        lambda: tmux_helper.TmuxSelection(None, "native"),
    )

    info = tmux_helper.persistent_shell_backend_info()

    assert info["backend"] == "native"
    assert info["durable_across_server_restart"] is False
    assert "tmux is unavailable" in str(info["warning"])
