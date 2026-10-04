from __future__ import annotations

import asyncio
import time

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import local_shell_mcp.http_app as http_app_module
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.settings import get_settings


def _configure_http(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", raising=False)
    get_settings.cache_clear()


def test_watchdog_budgets_cover_registered_routes_and_are_tool_specific(tmp_path, monkeypatch):
    _configure_http(tmp_path, monkeypatch)
    app = build_http_app()

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/tools/"):
            continue
        for method in route.methods or ():
            assert (method, route.path) in http_app_module.HTTP_TOOL_WATCHDOG_TIMEOUTS_S

    budgets = http_app_module.HTTP_TOOL_WATCHDOG_TIMEOUTS_S
    assert budgets[("POST", "/tools/tree")] == 30
    assert budgets[("POST", "/tools/run_shell")] == 130
    assert budgets[("POST", "/tools/browser/capture")] == 75
    assert budgets[("POST", "/tools/browser/text")] == 75
    assert budgets[("POST", "/tools/playwright/run_script")] == 130
    assert budgets[("POST", "/tools/shell_send")] is None
    assert budgets[("POST", "/tools/write_file")] is None
    assert ("GET", "/healthz") not in budgets
    assert ("GET", "/version") not in budgets
    assert ("POST", "/tools/not_registered") not in budgets


def test_rest_tool_watchdog_times_out_registered_short_route(tmp_path, monkeypatch):
    _configure_http(tmp_path, monkeypatch)
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)

    async def hanging_tree(cwd: str = ".", depth: int = 3, max_entries: int = 500):  # noqa: ARG001
        await asyncio.sleep(5)

    monkeypatch.setattr(http_app_module, "tree", hanging_tree)
    response = TestClient(build_http_app()).post("/tools/tree", json={"cwd": "."})

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"
    assert "0.01 second" in response.json()["message"]


def test_watchdog_preserves_status_and_auth_behavior(tmp_path, monkeypatch):
    _configure_http(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    get_settings.cache_clear()
    client = TestClient(build_http_app())

    assert client.get("/healthz").status_code == 200
    assert client.get("/version").status_code == 401
    assert client.post("/tools/tree", json={"cwd": "."}).status_code == 401


def test_rest_shell_mutation_is_not_cancelled_by_watchdog(tmp_path, monkeypatch):
    _configure_http(tmp_path, monkeypatch)
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    finished = []

    async def delayed_send(
        session_id: str, input_text: str, enter: bool = True, idempotency_key=None
    ):  # noqa: ARG001
        await asyncio.sleep(0.05)
        finished.append(True)
        return {"session_id": session_id, "sent": True}

    monkeypatch.setattr(http_app_module, "send_shell", delayed_send)
    response = TestClient(build_http_app()).post(
        "/tools/shell_send",
        json={"session_id": "shell-1", "input_text": "echo done", "enter": True},
    )

    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert finished == [True]


def test_rest_file_mutation_is_not_cancelled_by_watchdog(tmp_path, monkeypatch):
    _configure_http(tmp_path, monkeypatch)
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    marker = tmp_path / "write-finished.txt"

    def delayed_write(path, content, overwrite=True):  # noqa: ANN001, ARG001
        time.sleep(0.05)
        marker.write_text(content, encoding="utf-8")
        return {"path": "target.txt", "bytes": len(content), "created": True}

    monkeypatch.setattr(http_app_module, "write_text", delayed_write)
    response = TestClient(build_http_app()).post(
        "/tools/write_file", json={"path": "target.txt", "content": "done"}
    )

    assert response.status_code == 200
    assert marker.read_text(encoding="utf-8") == "done"
