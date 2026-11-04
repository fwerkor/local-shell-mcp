from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_shell_mcp.config_management import config_file, config_snapshot, save_config
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.settings import get_settings


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LOCAL_SHELL_MCP_CONFIG", raising=False)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_default_path_save_restart_loading_and_reset(configured):
    snapshot = config_snapshot()
    assert Path(snapshot["path"]) == configured / ".local-shell-mcp" / "config.yaml"
    assert len(snapshot["fields"]) >= 80
    assert not get_settings().hosted_chat_enabled

    saved = save_config({"hosted_chat_enabled": True, "ui_wallpaper": "none"}, snapshot["revision"])
    assert saved["restart_required"]
    upcoming = next(field for field in config_snapshot()["fields"] if field["name"] == "hosted_chat_enabled")
    assert upcoming["value"] is True and upcoming["pending"] is True
    assert stat.S_IMODE(config_file().stat().st_mode) == 0o600 if os.name != "nt" else config_file().exists()
    get_settings.cache_clear()
    assert get_settings().hosted_chat_enabled
    assert get_settings().ui_wallpaper == "none"
    assert next(field for field in config_snapshot()["fields"] if field["name"] == "hosted_chat_enabled")["pending"] is False
    assert next(f for f in config_snapshot()["fields"] if f["name"] == "hosted_chat_enabled")["source"] == "config"

    save_config({"hosted_chat_enabled": None}, saved["revision"])
    get_settings.cache_clear()
    assert not get_settings().hosted_chat_enabled


def test_validation_failure_does_not_write(configured):
    before = config_snapshot()
    for changes in ({"port": -1}, {"ui_path": "/api"}, {"mode": "both"}, {"remote_enabled": "not-bool"}):
        with pytest.raises(ValueError):
            save_config(changes, before["revision"])
        assert config_snapshot()["revision"] == before["revision"]
        assert not config_file().exists()


def test_env_lock_and_optimistic_revision(configured, monkeypatch):
    original = config_snapshot()
    monkeypatch.setenv("LOCAL_SHELL_MCP_PORT", "8899")
    with pytest.raises(ValueError, match="environment"):
        save_config({"port": 8900}, original["revision"])
    assert next(f for f in config_snapshot()["fields"] if f["name"] == "port")["locked"]
    saved = save_config({"max_jobs": 9}, original["revision"])
    with pytest.raises(RuntimeError, match="refresh"):
        save_config({"max_jobs": 10}, original["revision"])
    assert config_snapshot()["revision"] == saved["revision"]


def test_secret_never_returned_and_yaml_sections(configured):
    document = config_file()
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("oauth:\n  admin_pin: top-secret-pin\nui_wallpaper: aurora\n")
    get_settings.cache_clear()
    snapshot = config_snapshot()
    secret = next(f for f in snapshot["fields"] if f["name"] == "oauth_admin_pin")
    assert secret["sensitive"] and secret["configured"] and secret["value"] is None
    assert "top-secret-pin" not in str(snapshot)
    save_config({"oauth_admin_pin": "new-top-secret-pin"}, snapshot["revision"])
    assert "admin_pin: new-top-secret-pin" in document.read_text()
    assert "ui_wallpaper: aurora" in document.read_text()


def test_explicit_config_and_symbolic_link_rejected(configured, monkeypatch):
    path = configured / "custom.yaml"
    path.write_text("max_jobs: 17\n")
    monkeypatch.setenv("LOCAL_SHELL_MCP_CONFIG", str(path))
    get_settings.cache_clear()
    assert config_snapshot()["path"] == str(path)
    assert get_settings().max_jobs == 17
    link = configured / "link.yaml"
    link.symlink_to(path)
    monkeypatch.setenv("LOCAL_SHELL_MCP_CONFIG", str(link))
    with pytest.raises(ValueError, match="symbolic"):
        config_snapshot()


def test_anonymous_remote_cannot_manage_config(configured):
    with TestClient(build_http_app()) as client:
        result = client.get("/api/ui/settings/view")
        assert result.status_code == 403
        result = client.post("/api/ui/settings/save", json={"revision": hashlib.sha256(b"").hexdigest(), "changes": {"max_jobs": 1}})
        assert result.status_code == 403


def test_oauth_management_scope_and_same_origin(configured, monkeypatch):
    from local_shell_mcp.oauth import issue_access_token

    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "a-valid-controller-test-secret-of-40-chars")
    get_settings.cache_clear()
    client = TestClient(build_http_app(), client=("203.0.113.77", 4321))
    token_args = {"client_id": "test", "resource": "http://testserver", "issuer": "http://testserver"}
    ordinary = issue_access_token(scope="shell:read shell:write", **token_args)
    admin = issue_access_token(scope="shell:read admin:config", **token_args)
    assert client.get("/api/ui/settings/view", headers={"Authorization": f"Bearer {ordinary}"}).status_code == 403
    headers = {"Authorization": f"Bearer {admin}"}
    assert client.get("/api/ui/settings/view", headers=headers).status_code == 200
    snapshot = config_snapshot()
    params = {"revision": snapshot["revision"], "changes": {"max_jobs": 35}}
    cross_origin = {**headers, "Origin": "https://attacker.invalid"}
    assert client.post("/api/ui/settings/save", headers=cross_origin, json=params).status_code == 403
    same_origin = {**headers, "Origin": "http://testserver"}
    assert client.post("/api/ui/settings/save", headers=same_origin, json=params).status_code == 200
    assert config_snapshot()["fields"]
