"""Regression checks for LibreChat's unified LSM control plane."""
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

from local_shell_mcp.auth import verify_request

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations" / "librechat"


@pytest.fixture(autouse=True)
def isolated_controller_settings(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request(path: str, *, service: bool = True) -> Request:
    headers = [(b"x-lsm-chat-user-id", b"0123456789abcdef01234567")]
    if service:
        headers.append((b"authorization", b"Bearer integration-secret"))
    return Request({
        "type": "http",
        "scheme": "http",
        "server": ("localhost", 8765),
        "client": ("127.0.0.1", 9999),
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
    })


def test_lsm_proxy_uses_identity_mapping_and_original_scopes():
    with (
        patch("local_shell_mcp.librechat_integration.is_bridge_service", return_value=True),
        patch("local_shell_mcp.librechat_integration.principal_for_chat_user",
              return_value={"subject": "owner", "auth_mode": "oauth", "scopes": "shell:read remote:use"}),
    ):
        principal = verify_request(_request("/api/ui/files"))
    assert principal.subject == "owner"
    assert principal.claims["scope"] == "shell:read remote:use"
    assert principal.claims["auth"] == "librechat-bridge"


@pytest.mark.parametrize("path", ["/api/ui/files", "/api/ui/librechat/upload"])
def test_lsm_proxy_rejects_missing_service_credential(path):
    with (
        patch("local_shell_mcp.librechat_integration.is_bridge_service", return_value=False),
        pytest.raises(HTTPException) as captured,
    ):
        verify_request(_request(path, service=False))
    assert captured.value.status_code == 401


def test_lsm_proxy_denies_expired_identity():
    with (
        patch("local_shell_mcp.librechat_integration.is_bridge_service", return_value=True),
        patch("local_shell_mcp.librechat_integration.principal_for_chat_user",
              side_effect=PermissionError("expired")),
        pytest.raises(HTTPException) as captured,
    ):
        verify_request(_request("/api/ui/terminals"))
    assert captured.value.status_code == 401


def test_vendored_librechat_is_self_contained():
    source = INTEGRATION / "app"
    index = (source / "client/src/routes/index.tsx").read_text()
    assert index.count("path: 'control/:section?'") == 1
    assert 'Navigate to="/control/overview"' in index
    assert "app.use('/api/lsm/controller'" in (source / "api/server/index.js").read_text()
    assert (source / "LICENSE").is_file()
    assert (source / "Dockerfile").is_file()
    assert not (source / ".git").exists()
    assert not (INTEGRATION / "prepare.py").exists()
    compose = (INTEGRATION / "compose.yaml").read_text()
    assert "context: ./app" in compose
    assert "upstream-src" not in compose


def test_single_user_auth_routes_and_gui_proxy_contract():
    app = INTEGRATION / "app"
    auth = (app / "api/server/routes/auth.js").read_text()
    assert "router.post(\'/refresh\'" in auth
    assert "router.post(\'/logout\'" in auth
    for disabled in ("/login", "/register", "/resetPassword", "/2fa"):
        assert disabled not in auth
    login = (app / "api/server/routes/lsm-auth.js").read_text()
    assert "createLsmAuthHandler" in login
    auth_store = (app / "packages/data-schemas/src/methods/lsmAuth.ts").read_text()
    assert "workspace@local-shell-mcp.invalid" in auth_store
    proxy = (app / "api/server/routes/lsm-controller.js").read_text()
    assert "makeLsmControllerProxy" in proxy
    transport = (app / "packages/api/src/lsm/controller.ts").read_text()
    assert "x-lsm-gui-observation-id" in transport
    assert "x-lsm-gui-coordinate-input" in transport


def test_unified_ui_native_pages_present():
    pages = INTEGRATION / "app/client/src/components/LSM"
    for name in ("Control.tsx", "Overview.tsx", "Files.tsx", "Operations.tsx", "Desktop.tsx", "Settings.tsx"):
        assert (pages / name).is_file()
    navigation = (pages / "Control.tsx").read_text()
    settings = (pages / "Settings.tsx").read_text()
    proxy = (INTEGRATION / "app/packages/api/src/lsm/controller.ts").read_text()
    assert "/control/" in navigation and "section === 'settings'" in navigation
    for route in ("settings/view", "settings/save", "settings/restart"):
        assert route in settings or route.split("/")[-1] in proxy
    assert "admin:config" in (INTEGRATION / "README.md").read_text()
    assert "isLsmSettingsOriginAllowed" in proxy
