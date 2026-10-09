from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

import local_shell_mcp.human_ui as ui


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_enabled", [False, True])
async def test_machine_listing_requires_remote_scope_when_workers_enabled(
    monkeypatch: pytest.MonkeyPatch, remote_enabled: bool
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(ui, "get_settings", lambda: SimpleNamespace(remote_enabled=remote_enabled))
    monkeypatch.setattr(
        ui, "_require_ui_scopes", lambda request, *scopes: calls.append(scopes)
    )
    monkeypatch.setattr(ui, "_machine_rows", lambda: [{"name": "local"}])

    response = await ui.api_machines(object())
    assert json.loads(response.body)["data"] == [{"name": "local"}]
    expected = ("shell:read", "remote:use") if remote_enabled else ("shell:read",)
    assert calls == [expected]


def test_invalid_utf8_websocket_bearer_token_is_rejected() -> None:
    invalid_utf8 = base64.urlsafe_b64encode(b"\xff\xfe").decode().rstrip("=")
    websocket = SimpleNamespace(
        headers={"sec-websocket-protocol": f"lsm-ui,bearer.{invalid_utf8}"}
    )
    assert ui._websocket_token(websocket) is None
