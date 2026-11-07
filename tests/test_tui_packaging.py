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


def test_webui_config_hides_tui_when_not_installed(monkeypatch):
    monkeypatch.setattr(ui, "get_settings", lambda: SimpleNamespace(ui_path="/ui"))
    monkeypatch.setattr(ui, "tui_runtime_available", lambda: False)
    html = ui._ui_index_html()
    assert '"tuiAvailable": false' in html
    monkeypatch.setattr(ui, "tui_runtime_available", lambda: True)
    assert '"tuiAvailable": true' in ui._ui_index_html()
