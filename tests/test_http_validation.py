import base64
import hashlib

from fastapi.testclient import TestClient

from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.settings import get_settings


def test_http_missing_required_argument_returns_validation_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()

    response = TestClient(build_http_app()).post("/tools/read_file", json={})

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "validation_error",
        "message": "Missing required argument: path",
    }


def test_http_exception_uses_consistent_error_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()

    response = TestClient(build_http_app()).post(
        "/tools/run_shell",
        json={"command": "echo ok", "timeout_s": 3600},
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert response.json()["error"] == "http_error"
    assert "timeout_s must be <= 120 seconds" in response.json()["message"]


def test_http_write_file_accepts_base64_binary_content(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    payload = b"\x89PNG\r\n\x1a\n\x00\xffbinary"

    response = TestClient(build_http_app()).post(
        "/tools/write_file",
        json={
            "path": "image.png",
            "content": base64.b64encode(payload).decode("ascii"),
            "encoding": "base64",
        },
    )

    assert response.status_code == 200
    assert response.json()["sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / "image.png").read_bytes() == payload


def test_http_request_body_limit_rejects_oversized_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", "64")
    get_settings.cache_clear()

    response = TestClient(build_http_app()).post(
        "/tools/write_file",
        content=b"x" * 65,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "ok": False,
        "error": "request_too_large",
        "message": "Request body exceeds the configured 64 byte limit",
    }


def test_http_remote_only_mode_omits_controller_local_tool_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
    get_settings.cache_clear()
    client = TestClient(build_http_app())

    for method, path, payload in (
        ("post", "/tools/run_shell", {"command": "echo nope"}),
        ("post", "/tools/read_file", {"path": "secret.txt"}),
        ("get", "/tools/skills_list", None),
        ("post", "/tools/browser/text", {"url": "https://example.com"}),
    ):
        response = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
        assert response.status_code == 404

    assert client.get("/tools/todo").status_code == 404
