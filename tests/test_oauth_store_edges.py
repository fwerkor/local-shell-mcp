from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from edge_case_support import _MemoryStateStore

import local_shell_mcp.oauth as oauth_module


def test_oauth_client_store_loader_handles_bad_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = SimpleNamespace(
        state_backend="memory",
        state_backend_url=None,
        state_backend_prefix="test",
        state_dir=tmp_path,
    )
    monkeypatch.setattr(oauth_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oauth_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(oauth_module, "_CLIENTS", {})
    monkeypatch.setattr(oauth_module, "_LOADED_CLIENT_STORE_SIGNATURE", None)
    payload = {
        "version": oauth_module.OAUTH_CLIENT_STORE_VERSION,
        "clients": {
            "good": {
                "redirect_uris": ["https://example/callback"],
                "client_name": 123,
                "created_at": "bad",
            },
            "bad-redirect": {"redirect_uris": "nope"},
            3: {"redirect_uris": []},
        },
    }
    store = _MemoryStateStore(
        {oauth_module.OAUTH_CLIENT_STORE_FILE_NAME: __import__("json").dumps(payload).encode()}
    )
    monkeypatch.setattr(oauth_module, "get_state_store", lambda: store)
    oauth_module._load_clients_locked()
    assert set(oauth_module._CLIENTS) == {"good", "3"}
    assert oauth_module._CLIENTS["good"].client_name is None
    assert oauth_module._CLIENTS["good"].created_at > 0

    store.values[oauth_module.OAUTH_CLIENT_STORE_FILE_NAME] = b'{"version":999}'
    oauth_module._load_clients_locked()
    assert oauth_module._CLIENTS == {}

def test_oauth_code_store_loader_handles_rows_and_invalid_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(state_backend="memory")
    monkeypatch.setattr(oauth_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oauth_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(oauth_module, "_CODES", {})
    payload = {
        "version": oauth_module.OAUTH_CODE_STORE_VERSION,
        "codes": [
            "bad",
            {"code": ""},
            {
                "code": "code",
                "client_id": "client",
                "redirect_uri": "https://example/callback",
                "scope": "shell:read",
                "resource": "resource",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
                "created_at": 1,
                "used": True,
            },
        ],
    }
    store = _MemoryStateStore(
        {oauth_module.OAUTH_CODE_STORE_FILE_NAME: __import__("json").dumps(payload).encode()}
    )
    monkeypatch.setattr(oauth_module, "get_state_store", lambda: store)
    oauth_module._load_codes_locked()
    assert set(oauth_module._CODES) == {"code"}
    assert oauth_module._CODES["code"].used is True

    store.values[oauth_module.OAUTH_CODE_STORE_FILE_NAME] = b'{"version":1,"codes":"bad"}'
    oauth_module._load_codes_locked()
    assert oauth_module._CODES == {}

def test_oauth_invalid_top_level_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        state_backend="memory",
        state_backend_url=None,
        state_backend_prefix="test",
        state_dir=tmp_path,
    )
    monkeypatch.setattr(oauth_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oauth_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(oauth_module, "_CLIENTS", {})
    monkeypatch.setattr(oauth_module, "_CODES", {})
    monkeypatch.setattr(oauth_module, "_LOADED_CLIENT_STORE_SIGNATURE", None)
    store = _MemoryStateStore(
        {
            oauth_module.OAUTH_CLIENT_STORE_FILE_NAME: (
                '{"version":' + str(oauth_module.OAUTH_CLIENT_STORE_VERSION) + ',"clients":[]}'
            ).encode(),
            oauth_module.OAUTH_CODE_STORE_FILE_NAME: b'{"version":999,"codes":[]}',
        }
    )
    monkeypatch.setattr(oauth_module, "get_state_store", lambda: store)
    oauth_module._load_clients_locked()
    oauth_module._load_codes_locked()
    assert oauth_module._CLIENTS == {}
    assert oauth_module._CODES == {}
