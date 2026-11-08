"""Existing LSM PIN/OAuth portal uses native SQLite session handoff."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from local_shell_mcp.webui.auth import WebAuthStore


@pytest.mark.asyncio
async def test_existing_login_portal_issues_sqlite_workspace_ticket(tmp_path, monkeypatch):
    from local_shell_mcp import human_ui

    settings = SimpleNamespace(state_dir=tmp_path, state_backend="sqlite",
                               public_base_url="https://lsm.example.invalid")
    monkeypatch.setattr(human_ui, "get_settings", lambda: settings)
    monkeypatch.setattr(human_ui, "_require_ui_scopes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(human_ui, "_logical_session_subject", lambda _request, **_kw: "alice")
    monkeypatch.setattr(human_ui, "_request_principal", lambda _request: SimpleNamespace(
        subject="alice", claims={"scope": "shell:read remote:use", "auth": "oauth",
                                  "exp": int(time.time()) + 3600},
    ))
    req = Request({"type": "http", "method": "POST", "path": "/api/ui/librechat/ticket",
                   "scheme": "https", "server": ("lsm.example.invalid", 443), "headers": []})
    response = await human_ui.api_librechat_ticket(req)
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["ok"] is True
    assert body["data"]["url"] == "https://lsm.example.invalid"
    raw_session, redeemed = WebAuthStore(tmp_path).redeem(body["data"]["ticket"])
    assert redeemed.owner == "alice"
    assert redeemed.scopes == "remote:use shell:read"
    assert raw_session
