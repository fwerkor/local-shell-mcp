from __future__ import annotations

from types import SimpleNamespace

import local_shell_mcp.human_ui as ui


def test_tui_availability_is_false_for_web_only_release(monkeypatch):
    monkeypatch.setattr(ui, "get_settings", lambda: SimpleNamespace(ui_tui_command=None))
    monkeypatch.setattr(ui, "embedded_tui_payload", lambda: None)
    monkeypatch.setattr(ui, "_tui_sidecar_candidates", lambda: [])
    monkeypatch.setattr(ui, "_tui_source_path", lambda: None)
    assert ui.tui_runtime_available() is False


def test_tui_availability_detects_external_and_embedded_runtimes(monkeypatch, tmp_path):
    settings = SimpleNamespace(ui_tui_command=None)
    monkeypatch.setattr(ui, "get_settings", lambda: settings)
    monkeypatch.setattr(ui, "embedded_tui_payload", lambda: None)
    monkeypatch.setattr(ui, "_tui_source_path", lambda: None)
    sidecar = tmp_path / "local-shell-mcp-tui"
    monkeypatch.setattr(ui, "_tui_sidecar_candidates", lambda: [sidecar])
    assert ui.tui_runtime_available() is False
    sidecar.touch()
    assert ui.tui_runtime_available() is True
    sidecar.unlink()
    settings.ui_tui_command = "/nonexistent/local-shell-mcp-tui"
    assert ui.tui_runtime_available() is False
    sidecar.touch(mode=0o755)
    sidecar.chmod(0o755)
    settings.ui_tui_command = str(sidecar)
    assert ui.tui_runtime_available() is True
    settings.ui_tui_command = "   "
    assert ui.tui_runtime_available() is False
    settings.ui_tui_command = None
    sidecar.unlink()
    monkeypatch.setattr(ui, "_tui_source_path", lambda: tmp_path / "tui.tsx")
    monkeypatch.setattr(ui.shutil, "which", lambda _: "/usr/bin/bun")
    assert ui.tui_runtime_available() is True
    monkeypatch.setattr(ui, "_tui_source_path", lambda: None)
    monkeypatch.setattr(ui, "embedded_tui_payload", lambda: sidecar)
    assert ui.tui_runtime_available() is True


def test_webui_bootstrap_reports_tui_availability(monkeypatch):
    import asyncio
    import json

    from starlette.requests import Request

    settings = SimpleNamespace(remote_enabled=False, state_backend="sqlite",
                               live_workspace_enabled=False, ui_wallpaper="none")
    monkeypatch.setattr(ui, "get_settings", lambda: settings)
    monkeypatch.setattr(ui, "_require_ui_scopes", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui, "_machine_rows", lambda: [])
    request = Request({"type": "http", "method": "GET", "path": "/api/ui/bootstrap", "headers": []})
    for available in (False, True):
        monkeypatch.setattr(ui, "tui_runtime_available", lambda value=available: value)
        response = asyncio.run(ui.api_bootstrap(request))
        assert response.status_code == 200
        assert json.loads(response.body)["data"]["features"]["tui"] is available
