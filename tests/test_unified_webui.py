"""The unified WebUI is a first-party React application backed by Python.

These tests replace old Node/Mongo/bridge contracts after deleting the entire
integrations directory. The frontend source and Controller routes now live in
LSM's UI and Python package respectively.
"""

from __future__ import annotations

from pathlib import Path

from local_shell_mcp.webui.agent_routes import agent_routes
from local_shell_mcp.webui.auth import auth_routes
from local_shell_mcp.webui.controller_routes import controller_routes
from local_shell_mcp.webui.generation_routes import generation_routes

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "ui" / "workspace"


def test_unified_react_workspace_is_first_party_and_vendored_backend_is_removed():
    assert not (ROOT / "integrations").exists()
    source = WORKSPACE / "client" / "src" / "routes" / "index.tsx"
    text = source.read_text(encoding="utf-8")
    assert text.count("path: 'control/:section?'") == 1
    assert 'Navigate to="/control/overview"' in text
    assert (WORKSPACE / "LICENSE").is_file()
    assert (WORKSPACE / "README.md").is_file()
    assert (WORKSPACE / "bun.lock").is_file()
    assert (WORKSPACE / "client" / "src" / "components" / "LSM" / "Control.tsx").is_file()
    assert not (WORKSPACE / "api").exists()
    assert not (WORKSPACE / "Dockerfile").exists()
    assert not (WORKSPACE / "compose.yaml").exists()


def test_native_python_login_agents_and_sse_are_routed_without_node(monkeypatch):
    from types import SimpleNamespace

    from local_shell_mcp import human_ui

    # Route registration must never try to initialize the default `/workspace`
    # state directory, which does not exist or is unwritable in some CI OSes.
    monkeypatch.setattr(human_ui, "get_settings", lambda: SimpleNamespace(ui_enabled=True, ui_path="/ui"))
    auth = {route.path for route in auth_routes()}
    assert {"/api/auth/lsm", "/api/auth/refresh", "/api/auth/logout"}.issubset(auth)
    agents = {route.path for route in agent_routes()}
    assert {"/api/agents", "/api/agents/{agent_id}", "/api/agents/{agent_id}/versions"}.issubset(agents)
    generation = {route.path for route in generation_routes()}
    assert {"/api/agents/chat", "/api/agents/chat/stream/{stream_id}",
            "/api/agents/chat/abort", "/api/agents/chat/resume"}.issubset(generation)
    ctl = {route.path: route.endpoint for route in controller_routes()}
    assert len(ctl) >= 20
    assert "/api/lsm/controller/gui/frame" in ctl
    assert "/api/lsm/controller/settings/{action}" in ctl
    assert all("hosted-chat" not in path and "librechat" not in path for path in ctl)


def test_native_control_pages_and_settings_source_are_retained():
    pages = WORKSPACE / "client" / "src" / "components" / "LSM"
    for name in ("Control.tsx", "Overview.tsx", "Files.tsx", "Operations.tsx", "Desktop.tsx", "Settings.tsx"):
        assert (pages / name).is_file()
    navigation = (pages / "Control.tsx").read_text(encoding="utf-8")
    settings = (pages / "Settings.tsx").read_text(encoding="utf-8")
    assert "/control/" in navigation
    assert "section === 'settings'" in navigation
    for action in ("view", "save", "restart"):
        assert action in settings
    assert "admin:config" in (ROOT / "src/local_shell_mcp/human_ui.py").read_text(encoding="utf-8")


def test_webui_binary_release_embeds_frontend_and_has_no_backend_node_dependency():
    package = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "--add-data ui/workspace/frontend.tar.gz:local_shell_mcp/webui" in package
    built = WORKSPACE / "frontend.tar.gz"
    assert built.is_file()
    assert built.stat().st_size < 40_000_000
