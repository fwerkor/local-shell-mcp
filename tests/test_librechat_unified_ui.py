"""Regression checks for LibreChat's unified LSM control plane."""
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

from local_shell_mcp.auth import verify_request

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations" / "librechat"


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
    with patch("local_shell_mcp.librechat_integration.is_bridge_service", return_value=False):
        with pytest.raises(HTTPException) as captured:
            verify_request(_request(path, service=False))
    assert captured.value.status_code == 401


def test_lsm_proxy_denies_expired_identity():
    with (
        patch("local_shell_mcp.librechat_integration.is_bridge_service", return_value=True),
        patch("local_shell_mcp.librechat_integration.principal_for_chat_user",
              side_effect=PermissionError("expired")),
    ):
        with pytest.raises(HTTPException) as captured:
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


def test_unified_ui_native_pages_present():
    pages = INTEGRATION / "app/client/src/components/LSM"
    for name in ("Control.tsx", "Overview.tsx", "Files.tsx", "Operations.tsx", "Desktop.tsx"):
        assert (pages / name).is_file()
