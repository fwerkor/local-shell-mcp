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
    monkeypatch.delenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED", raising=False)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_default_path_save_restart_loading_and_reset(configured):
    snapshot = config_snapshot()
    assert Path(snapshot["path"]) == configured / ".local-shell-mcp" / "config.yaml"
    assert len(snapshot["fields"]) >= 80
    initial = get_settings().hosted_chat_enabled
    changed = not initial

    saved = save_config({"hosted_chat_enabled": changed, "ui_wallpaper": "none"}, snapshot["revision"])
    assert saved["restart_required"]
    upcoming = next(field for field in config_snapshot()["fields"] if field["name"] == "hosted_chat_enabled")
    assert upcoming["value"] is changed and upcoming["pending"] is True
    assert stat.S_IMODE(config_file().stat().st_mode) == 0o600 if os.name != "nt" else config_file().exists()
    get_settings.cache_clear()
    assert get_settings().hosted_chat_enabled is changed
    assert get_settings().ui_wallpaper == "none"
    assert next(field for field in config_snapshot()["fields"] if field["name"] == "hosted_chat_enabled")["pending"] is False
    assert next(f for f in config_snapshot()["fields"] if f["name"] == "hosted_chat_enabled")["source"] == "config"

    save_config({"hosted_chat_enabled": None}, saved["revision"])
    get_settings.cache_clear()
    assert get_settings().hosted_chat_enabled is initial


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


def test_direct_localhost_config_writes_with_public_url(configured, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://controller.example.test")
    get_settings.cache_clear()
    with TestClient(
        build_http_app(), base_url="http://127.0.0.1:8765", client=("127.0.0.1", 43561)
    ) as client:
        snapshot = client.get("/api/ui/settings/view")
        assert snapshot.status_code == 200
        params = {"revision": snapshot.json()["data"]["revision"], "changes": {"max_jobs": 36}}
        path = "/api/ui/settings/save"
        assert client.post(path, headers={"Origin": "http://127.0.0.1:8765"}, json=params).status_code == 200
        assert client.post(path, headers={"Origin": "https://evil.example.test"}, json=params).status_code in {401, 403}


def test_proxy_origin_requires_same_host_even_with_advertised_https(configured, monkeypatch):
    from starlette.requests import Request

    from local_shell_mcp.human_ui import _settings_same_origin

    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://controller.example.test")
    get_settings.cache_clear()

    def request(host: str, origin: str) -> Request:
        return Request({
            "type": "http", "method": "POST", "scheme": "http", "path": "/api/ui/settings/save",
            "headers": [(b"host", host.encode()), (b"origin", origin.encode())],
            "server": (host, 80), "query_string": b"",
        })

    assert _settings_same_origin(request("controller.example.test", "https://controller.example.test"))
    assert not _settings_same_origin(request("localhost:8765", "https://controller.example.test"))
    assert not _settings_same_origin(request("controller.example.test", "https://attacker.example.test"))


def test_yaml_state_dir_does_not_anchor_default_subpaths(configured):
    chosen_state = configured / "separate-state"
    config_file().parent.mkdir(parents=True, exist_ok=True)
    config_file().write_text(f"state_dir: {chosen_state}\n")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.state_dir == chosen_state
    assert settings.audit_log_path == chosen_state / "audit.jsonl"
    assert settings.agent_config_dir == chosen_state / "agent_config"
    fields = {row["name"]: row for row in config_snapshot()["fields"]}
    assert fields["audit_log_path"]["value"] == str(chosen_state / "audit.jsonl")


def test_stateless_oauth_requires_explicit_secret_before_saving(configured, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    initial = config_snapshot()
    with pytest.raises(ValueError, match="explicit strong oauth_jwt_secret"):
        save_config({"stateless_controller": True}, initial["revision"])
    assert config_snapshot()["revision"] == initial["revision"]
    secret = "valid-saved-jwt-secret-with-at-least-32-bytes"
    save_config({"stateless_controller": True, "oauth_jwt_secret": secret}, initial["revision"])
    get_settings.cache_clear()
    assert get_settings().stateless_controller
    assert get_settings().oauth_jwt_secret == secret


def test_cli_and_tui_discover_default_yaml_endpoint(configured):
    from local_shell_mcp.cli_call import _apply_yaml_controller_values
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("port: 18899\nmax_timeout_s: 120\n")
    values = {"LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(configured)}
    resolved = _apply_yaml_controller_values(values)
    assert resolved["LOCAL_SHELL_MCP_PORT"] == "18899"
    assert resolved["LOCAL_SHELL_MCP_MAX_TIMEOUT_S"] == "120"
    assert resolved["LOCAL_SHELL_MCP_STATE_DIR"] == str(configured / ".local-shell-mcp")
    assert _apply_yaml_controller_values({**values, "LOCAL_SHELL_MCP_PORT": "19991"})["LOCAL_SHELL_MCP_PORT"] == "19991"


def test_invalid_config_formats_and_size(configured, monkeypatch):
    from local_shell_mcp import config_management as cfg

    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        config_snapshot()
    path.rmdir()
    for content in ("[]", "- not: a mapping", "3", "null: value"):
        path.write_text(content)
        with pytest.raises(ValueError, match="YAML mapping"):
            config_snapshot()
    path.write_text("null\n")
    assert config_snapshot()["fields"]
    path.write_text("max_jobs: 12\n")
    monkeypatch.setattr(cfg, "_MAX_CONFIG_BYTES", 8)
    with pytest.raises(ValueError, match="256 KiB"):
        config_snapshot()


def test_reject_invalid_changes_and_preserve_file_on_write_failure(configured, monkeypatch):
    from local_shell_mcp import config_management as cfg

    data = config_snapshot()
    for changes, message in (
        ({}, "one or more"),
        ({"unknown_key": "x"}, "Unknown"),
        ({"max_jobs": {}}, "Unsupported"),
        ({"command_denylist": [12]}, "list of strings"),
    ):
        with pytest.raises(ValueError, match=message):
            save_config(changes, data["revision"])

    def refuse_replace(*args):
        raise OSError("write blocked")

    monkeypatch.setattr(cfg.os, "replace", refuse_replace)
    with pytest.raises(OSError, match="write blocked"):
        save_config({"max_jobs": 11}, data["revision"])
    assert not config_file().exists()
    assert not list(config_file().parent.glob(".config-*.tmp"))


def test_reject_oversized_config_write(configured, monkeypatch):
    from local_shell_mcp import config_management as cfg

    path = config_file()
    data = config_snapshot()
    monkeypatch.setattr(cfg, "_MAX_CONFIG_BYTES", 30)
    with pytest.raises(ValueError, match="256 KiB"):
        save_config({"state_backend_prefix": "a" * 50}, data["revision"])
    assert not path.exists()


def test_nested_yaml_reset_and_update(configured):
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("oauth:\n  admin_pin: original\n  code_ttl_s: 300\n")
    data = config_snapshot()
    saved = save_config({"oauth_admin_pin": "replacement"}, data["revision"])
    assert "admin_pin: replacement" in path.read_text()
    saved = save_config({"oauth_admin_pin": None}, saved["revision"])
    assert "admin_pin:" not in path.read_text()
    assert "code_ttl_s:" in path.read_text()
    save_config({"ui_tui_command": None}, saved["revision"])


def test_stateful_oauth_can_be_enabled_without_an_explicit_secret(configured, monkeypatch):
    monkeypatch.delenv("LOCAL_SHELL_MCP_AUTH_MODE", raising=False)
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("auth_mode: none\n")
    get_settings.cache_clear()
    assert get_settings().auth_mode == "none"
    initial = config_snapshot()
    save_config({"auth_mode": "oauth"}, initial["revision"])
    secret_path = get_settings().state_dir / "oauth-jwt-secret"
    assert not secret_path.exists()
    get_settings.cache_clear()
    assert get_settings().auth_mode == "oauth"
    assert len(get_settings().oauth_jwt_secret.encode("utf-8")) >= 32
    assert secret_path.is_file()


def test_default_config_path_expands_environment_variables(configured, monkeypatch):
    from local_shell_mcp.settings import controller_config_path

    monkeypatch.setenv("CONFIG_TEST_BASE", str(configured))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", "$CONFIG_TEST_BASE/state")
    assert controller_config_path() == configured / "state" / "config.yaml"
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_DIR")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", "$CONFIG_TEST_BASE/workspace")
    assert controller_config_path() == configured / "workspace" / ".local-shell-mcp" / "config.yaml"
    monkeypatch.setenv("LOCAL_SHELL_MCP_CONFIG", "$CONFIG_TEST_BASE/custom.yaml")
    assert controller_config_path() == configured / "custom.yaml"
