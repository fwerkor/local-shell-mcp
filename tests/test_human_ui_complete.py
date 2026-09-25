from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

import local_shell_mcp.human_ui as ui
from local_shell_mcp.auth import AuthMiddleware, Principal
from local_shell_mcp.live_channel import get_live_channel_manager
from local_shell_mcp.oauth import ALL_OAUTH_SCOPES
from local_shell_mcp.settings import get_settings


def _configure(
    tmp_path,
    monkeypatch,
    *,
    remote: bool = False,
    auth: str = "none",
    disable_local: bool = False,
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", str(remote).lower())
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", str(disable_local).lower())
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_WALLPAPER", "none")
    get_settings.cache_clear()


def _stub_tmux_scrollback(monkeypatch, fake_state, pane_id: str = "%1") -> None:
    async def fake_baseline(process):
        return await fake_state(process, pane_id), pane_id

    monkeypatch.setattr(ui, "_tmux_scrollback_state", fake_state)
    monkeypatch.setattr(ui, "_tmux_scrollback_baseline", fake_baseline)


def _request(path: str = "/", *, query: bytes = b"", method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
    )


class FakeRemoteManager:
    def __init__(self):
        self.calls: list[tuple[str, str, dict, float | int | None]] = []
        self.call_options: list[dict[str, object]] = []
        self.response: dict = {"ok": True, "data": {}}
        self.machines = {
            "machines": [
                {
                    "name": "win-node",
                    "status": "online",
                    "info": {"platform": "Windows-11"},
                }
            ],
            "counts": {"online": 1, "offline": 0, "total": 1},
        }

    async def call(
        self,
        machine,
        tool,
        args,
        timeout_s=None,
        *,
        lane=None,
        execution_timeout_s=None,
        queue_timeout_s=None,
        rpc_timeout_s=None,
    ):
        self.calls.append(
            (machine, tool, args, timeout_s if timeout_s is not None else rpc_timeout_s)
        )
        self.call_options.append(
            {
                "lane": lane,
                "execution_timeout_s": execution_timeout_s,
                "queue_timeout_s": queue_timeout_s,
                "rpc_timeout_s": rpc_timeout_s,
            }
        )
        return self.response

    def list_machines(self):
        return self.machines

    async def create_invite(self, name=None, workdir=None, ttl_s=None, base_url=None):
        return {"name": name, "workdir": workdir, "ttl_s": ttl_s, "base_url": base_url}

    def rename(self, machine, new_name):
        return {"old_name": machine, "new_name": new_name}

    def revoke(self, machine):
        return {"machine": machine, "revoked": True}


def test_root_redirects_to_relative_ui_path_without_auth(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_PATH", "/console")
    get_settings.cache_clear()
    app = Starlette(routes=ui.ui_routes())
    app.add_middleware(AuthMiddleware)

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "./console/"


def test_audit_detail_missing_entry_returns_not_found(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    response = asyncio.run(ui.api_audit_detail(_request("/api/ui/audit/detail")))

    assert response.status_code == 404


def test_audit_detail_requires_scopes_before_materializing_payloads(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    calls: list[bool] = []
    preview = {
        "id": "call:write",
        "tool": "write_file",
        "operation": "files",
        "node": "local",
    }

    def fake_get_audit_entry(entry_id: str, *, full: bool = True):
        assert entry_id == "call:write"
        calls.append(full)
        return {**preview, "input": {"content": "secret"}} if full else preview

    monkeypatch.setattr(ui, "get_audit_entry", fake_get_audit_entry)
    limited = _request("/api/ui/audit/detail", query=b"id=call%3Awrite")
    limited.state.principal = Principal(
        email=None,
        subject="read-only",
        claims={"scope": "shell:read"},
    )

    denied = asyncio.run(ui.api_audit_detail(limited))

    assert denied.status_code == 403
    assert calls == [False]

    allowed = _request("/api/ui/audit/detail", query=b"id=call%3Awrite")
    allowed.state.principal = Principal(
        email=None,
        subject="writer",
        claims={"scope": "shell:read shell:write"},
    )

    response = asyncio.run(ui.api_audit_detail(allowed))

    assert response.status_code == 200
    assert calls == [False, False, True]
    assert "secret" in response.body.decode()
    assert set(ui._audit_detail_scopes({"operation": "browser", "node": "local"})) == {
        "shell:read",
        "browser:use",
    }
    assert set(ui._audit_detail_scopes({"tool": "job_start", "node": "local"})) == {
        "shell:read",
        "shell:execute",
    }
    assert set(ui._audit_detail_scopes({"tool": "create_file_link", "node": "local"})) == {
        "shell:read",
        "file:share",
    }
    assert set(ui._audit_detail_scopes({"operation": "other", "node": "worker"})) == set(
        ui.UI_FULL_SCOPES
    )


def test_audit_detail_renders_view_image_without_returning_raw_data(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    encoded = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    preview = {
        "id": "call:image",
        "tool": "view_image",
        "operation": "files",
        "node": "local",
    }
    detail = {
        **preview,
        "output": {
            "content": [
                {"type": "image", "data": encoded, "mimeType": "image/png"},
                {"type": "text", "text": "pixel.png (image/png, 68 bytes)"},
            ],
            "structuredContent": {
                "ok": True,
                "path": "pixel.png",
                "mime_type": "image/png",
                "bytes": len(base64.b64decode(encoded)),
            },
            "isError": False,
        },
    }

    def fake_get_audit_entry(entry_id: str, *, full: bool = True):
        assert entry_id == "call:image"
        return dict(detail if full else preview)

    monkeypatch.setattr(ui, "get_audit_entry", fake_get_audit_entry)
    request = _request(
        "/api/ui/audit/detail",
        query=b"id=call%3Aimage&columns=20&rows=10&cell_aspect=2",
    )
    request.state.principal = Principal(
        email=None,
        subject="reader",
        claims={"scope": "shell:read"},
    )

    response = asyncio.run(ui.api_audit_detail(request))
    payload = json.loads(response.body)["data"]

    assert response.status_code == 200
    assert payload["image_preview"]["kind"] == "image"
    assert payload["image_preview"]["path"] == "pixel.png"
    assert base64.b64decode(payload["image_preview"]["rgba"])
    assert "data" not in payload["output"]["content"][0]
    assert payload["output"]["content"][0]["bytes"] == len(base64.b64decode(encoded))
    assert encoded not in response.body.decode()


def test_audit_view_image_detail_keeps_non_images_and_sanitizes_invalid_data():
    ordinary = {"tool": "read_file", "output": {"content": []}}
    assert ui._audit_view_image_detail(ordinary, columns=20, rows=10, cell_aspect=2) is ordinary

    for incomplete in (
        {"tool": "view_image"},
        {"tool": "view_image", "output": "invalid"},
        {"tool": "view_image", "output": {"content": "invalid"}},
        {"tool": "view_image", "output": {"content": [{"type": "text", "text": "none"}]}},
    ):
        assert ui._audit_view_image_detail(incomplete, columns=20, rows=10, cell_aspect=2) is incomplete

    invalid = {
        "tool": "view_image",
        "output": {
            "content": [{"type": "image", "data": "not-base64", "mimeType": "image/png"}],
            "structured_content": {"path": "broken.png"},
        },
    }
    result = ui._audit_view_image_detail(invalid, columns=20, rows=10, cell_aspect=2)

    assert "data" not in result["output"]["content"][0]
    assert result["image_preview_error"]
    assert "image_preview" not in result


def test_index_assets_principal_and_basic_helpers(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    empty = tmp_path / "assets"
    empty.mkdir()
    monkeypatch.setattr(ui, "_assets_dir", lambda: empty)
    assert "assets are not built" in ui._ui_index_html()

    index = empty / "index.html"
    index.write_text("__LSM_UI_PATH__ __LSM_UI_CONFIG_JSON__", encoding="utf-8")
    rendered = ui._ui_index_html()
    assert "/ui" in rendered
    assert "apiPrefix" in rendered

    principal = Principal(email=None, subject="s", claims={"scope": "shell:read remote:use"})
    request = _request()
    request.state.principal = principal
    assert ui._request_principal(request) is principal
    ui._require_ui_scopes(request, "shell:read", machine="node")

    assert ui._bounded_int(None, default=7, minimum=1, maximum=10, label="x") == 7
    assert ui._bounded_int("", default=8, minimum=1, maximum=10, label="x") == 8
    assert ui._path_name(".") == "."
    assert ui._parent_path("") == "."

    assert ui._split_tui_command("echo hello", windows=False) == ["echo", "hello"]
    with pytest.raises(ValueError, match="empty"):
        ui._split_tui_command("   ", windows=False)


def test_wallpaper_disabled_returns_no_content(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    response = asyncio.run(ui.ui_wallpaper(_request()))

    assert response.status_code == 204


def test_wallpaper_rejects_invalid_bing_url(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_WALLPAPER", "bing")
    get_settings.cache_clear()

    class Response:
        content = b""

        def raise_for_status(self):
            return None

        def json(self):
            return {"images": [{"url": "https://invalid.example/wallpaper.jpg"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):  # noqa: ARG002
            return Response()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: Client())

    response = asyncio.run(ui.ui_wallpaper(_request()))

    assert response.status_code == 204


def test_wallpaper_rejects_oversized_bing_image(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_WALLPAPER", "bing")
    get_settings.cache_clear()

    class HugeContent:
        def __len__(self):
            return 20_000_001

    class Response:
        def __init__(self, *, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                return Response(payload={"images": [{"url": "/wallpaper.jpg"}]})
            return Response(content=HugeContent())

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: Client())

    response = asyncio.run(ui.ui_wallpaper(_request()))

    assert response.status_code == 204


def test_asset_cache_and_wallpaper_branches(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assets = tmp_path / "assets"
    assets.mkdir()
    immutable = assets / "app.123.js"
    immutable.write_text("js", encoding="utf-8")
    regular = assets / "app.js"
    regular.write_text("js", encoding="utf-8")
    directory = assets / "folder"
    directory.mkdir()
    monkeypatch.setattr(ui, "_assets_dir", lambda: assets)

    app = Starlette(routes=[Route("/assets/{path:path}", ui.ui_asset)])
    client = TestClient(app)
    assert client.get("/assets//etc/passwd").status_code == 404
    assert client.get("/assets/../secret").status_code == 404
    assert client.get("/assets/missing").status_code == 404
    assert client.get("/assets/folder").status_code == 404
    assert "31536000" in client.get("/assets/app.123.js").headers["cache-control"]
    assert "3600" in client.get("/assets/app.js").headers["cache-control"]

    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_WALLPAPER", "bing")
    get_settings.cache_clear()
    state_ui = tmp_path / ".state" / "ui"
    state_ui.mkdir(parents=True)
    image = state_ui / "wallpaper.jpg"
    stamp = state_ui / "wallpaper-date.txt"
    today = ui.time.strftime("%Y-%m-%d", ui.time.gmtime())
    stamp.write_text(today, encoding="utf-8")
    assert asyncio.run(ui.ui_wallpaper(_request())).status_code == 204
    image.write_bytes(b"cached")
    cached = asyncio.run(ui.ui_wallpaper(_request()))
    assert cached.status_code == 200

    stamp.unlink()

    class Response:
        def __init__(self, *, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Response(payload={"images": [{"url": "/image.jpg"}]})
            return Response(content=b"fresh")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    image.unlink()
    fetched = asyncio.run(ui.ui_wallpaper(_request()))
    assert fetched.status_code == 200
    assert image.read_bytes() == b"fresh"

    class InvalidClient(Client):
        async def get(self, url, **kwargs):
            return Response(payload={"images": []})

    monkeypatch.setattr(httpx, "AsyncClient", InvalidClient)
    stamp.unlink()
    image.write_bytes(b"stale")
    stale = asyncio.run(ui.ui_wallpaper(_request()))
    assert stale.status_code == 200
    assert stamp.read_text(encoding="utf-8") == today


def test_remote_dispatch_machine_rows_and_errors(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, remote=True)
    manager = FakeRemoteManager()
    monkeypatch.setattr(ui, "remote_manager", lambda: manager)

    rows = ui._machine_rows()
    assert rows["counts"] == {"online": 2, "offline": 0, "total": 2}
    assert rows["machines"][0]["name"] == "local"
    assert ui._machine_uses_windows_paths("win-node") is True
    assert ui._machine_uses_windows_paths("missing") is False

    async def local_coroutine():
        return {"async": True}

    assert asyncio.run(ui._machine_dispatch("local", lambda: {"sync": True}, "x", {})) == {
        "sync": True
    }
    assert asyncio.run(ui._machine_dispatch("local", local_coroutine, "x", {})) == {
        "async": True
    }

    manager.response = {"ok": True, "data": {"value": 1}}
    assert asyncio.run(ui._remote_call("win-node", "tool", {"a": 1})) == {"value": 1}
    assert manager.calls[-1][2]["_human"] is True
    assert manager.call_options[-1]["rpc_timeout_s"] == get_settings().ui_remote_request_timeout_s
    assert asyncio.run(
        ui._remote_call(
            "win-node", "run_shell_tool", {"command": "echo ok", "timeout_s": 10}
        )
    ) == {"value": 1}
    assert manager.call_options[-1]["execution_timeout_s"] == 10
    assert manager.call_options[-1]["rpc_timeout_s"] == ui.remote_execution_rpc_timeout_s(10)
    manager.response = {"ok": False, "message": "failed"}
    with pytest.raises(RuntimeError, match="failed"):
        asyncio.run(ui._remote_call("win-node", "tool", {}))
    manager.response = {
        "ok": True,
        "data": {"status": "error", "error_type": "Boom", "message": "bad"},
    }
    with pytest.raises(RuntimeError, match="bad"):
        asyncio.run(ui._remote_call("win-node", "tool", {}))

    def broken():
        raise RuntimeError("registry")

    monkeypatch.setattr(manager, "list_machines", broken)
    assert ui._machine_uses_windows_paths("win-node") is False


def test_disable_local_hides_controller_and_blocks_ui_dispatch(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, remote=True, disable_local=True)
    manager = FakeRemoteManager()
    monkeypatch.setattr(ui, "remote_manager", lambda: manager)

    rows = ui._machine_rows()
    assert all(machine["name"] != "local" for machine in rows["machines"])
    assert rows["counts"] == {"online": 1, "offline": 0, "total": 1}

    with pytest.raises(RuntimeError, match="Local access is disabled"):
        asyncio.run(ui._machine_dispatch("local", lambda: {"sync": True}, "x", {}))

    preview = TestClient(Starlette(routes=ui.ui_routes())).get(
        "/api/ui/files/preview", params={"machine": "local", "path": "."}
    )
    assert preview.status_code == 400
    assert "Local access is disabled" in preview.json()["message"]

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {}

        def __init__(self):
            self.closed = []

        async def close(self, code=1000, reason=""):
            self.closed.append((code, reason))

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    socket = Socket()
    asyncio.run(ui.ui_terminal_websocket(socket))
    assert socket.closed[0][0] == 4403
    assert "local access is disabled" in socket.closed[0][1].lower()

    monkeypatch.setattr(ui, "_live_websocket_credentials", lambda websocket: {"session": "live"})
    live_socket = Socket()
    asyncio.run(ui.ui_terminal_websocket(live_socket))
    assert live_socket.closed[0][0] == 4403
    assert "persistent shell sessions" in live_socket.closed[0][1]


def test_remote_file_terminal_audit_and_admin_routes(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, remote=True)
    manager = FakeRemoteManager()
    monkeypatch.setattr(ui, "remote_manager", lambda: manager)
    app = Starlette(routes=ui.ui_routes())
    client = TestClient(app)

    manager.response = {
        "ok": True,
        "data": [{"path": r"C:\work\folder", "type": "dir"}],
    }
    files = client.get("/api/ui/files", params={"machine": "win-node", "path": r"C:\work"})
    assert files.status_code == 200
    assert files.json()["data"]["entries"][0]["name"] == "folder"

    preview_dir = client.get(
        "/api/ui/files/preview", params={"machine": "win-node", "path": r"C:\work\folder"}
    )
    assert preview_dir.json()["data"]["kind"] == "directory"

    manager.response = {"ok": True, "data": {"preview": "00 ff", "binary": True}}
    preview_binary = client.get(
        "/api/ui/files/preview", params={"machine": "win-node", "path": "x.bin"}
    )
    assert preview_binary.json()["data"]["kind"] == "binary"

    manager.response = {"ok": True, "data": "plain"}
    preview_text = client.get(
        "/api/ui/files/preview", params={"machine": "win-node", "path": "x.txt"}
    )
    assert preview_text.json()["data"]["kind"] == "text"

    manager.response = {"ok": True, "data": {"binary": True}}
    assert client.get(
        "/api/ui/files/content", params={"machine": "win-node", "path": "x"}
    ).status_code == 400
    manager.response = {"ok": True, "data": "invalid"}
    assert client.get(
        "/api/ui/files/content", params={"machine": "win-node", "path": "x"}
    ).status_code == 400
    assert client.get(
        "/api/ui/files/content", params={"machine": "win-node", "path": ""}
    ).status_code == 400

    manager.response = {"ok": True, "data": {"done": True}}
    for action, body in (
        ("delete", {"path": "x"}),
        ("write", {"path": "x", "content": "data"}),
        ("mkdir", {"path": "x"}),
        ("touch", {"path": "x"}),
        ("rename", {"path": "x", "destination": "y"}),
        ("copy", {"path": "x", "destination": "y"}),
        ("move", {"path": "x", "destination": "y"}),
    ):
        response = client.post(
            f"/api/ui/files/{action}", json={"machine": "win-node", **body}
        )
        assert response.status_code == 200, action
    assert client.post(
        "/api/ui/files/unknown", json={"machine": "win-node", "path": "x"}
    ).status_code == 400
    assert client.post(
        "/api/ui/files/write", json={"machine": "win-node", "path": ""}
    ).status_code == 400

    manager.response = {"ok": True, "data": None}
    terminals = client.get("/api/ui/terminals", params={"machine": "win-node"})
    assert terminals.json()["data"]["sessions"] == []
    manager.response = {"ok": True, "data": {"output": "ok"}}
    assert client.get(
        "/api/ui/terminals/read",
        params={"machine": "win-node", "session_id": "s", "lines": 10},
    ).status_code == 200
    assert client.get(
        "/api/ui/terminals/read", params={"machine": "win-node", "session_id": ""}
    ).status_code == 400
    for action, body in (
        ("start", {}),
        ("send", {"session_id": "s", "input_text": "x"}),
        ("resize", {"session_id": "s", "cols": 132, "rows": 38}),
        ("kill", {"session_id": "s"}),
    ):
        assert client.post(
            f"/api/ui/terminals/{action}", json={"machine": "win-node", **body}
        ).status_code == 200
    assert client.post(
        "/api/ui/terminals/send", json={"machine": "win-node"}
    ).status_code == 400
    assert client.post(
        "/api/ui/terminals/resize",
        json={"machine": "win-node", "session_id": "s"},
    ).status_code == 400
    assert client.post(
        "/api/ui/terminals/resize",
        json={"machine": "win-node", "session_id": "s", "cols": "bad", "rows": 24},
    ).status_code == 400
    assert client.post(
        "/api/ui/terminals/kill", json={"machine": "win-node"}
    ).status_code == 400
    assert client.post(
        "/api/ui/terminals/unknown", json={"machine": "win-node"}
    ).status_code == 400

    assert client.get("/api/ui/audit", params={"limit": "bad"}).status_code == 400

    listing = client.get("/api/ui/remotes")
    assert listing.status_code == 200
    invite = client.post(
        "/api/ui/remotes", json={"name": "node", "workdir": "/w", "ttl_s": 90}
    )
    assert invite.status_code == 200
    assert invite.json()["data"]["base_url"] == "http://testserver"
    assert client.post(
        "/api/ui/remotes/rename", json={"machine": "node", "new_name": "new"}
    ).status_code == 200
    assert client.post(
        "/api/ui/remotes/revoke", json={"machine": "node"}
    ).status_code == 200
    assert client.post(
        "/api/ui/remotes/rename", json={"machine": ""}
    ).status_code == 400
    assert client.post(
        "/api/ui/remotes/unknown", json={"machine": "node"}
    ).status_code == 400


def test_local_preview_recovery_and_api_errors(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "child.txt").write_text("x", encoding="utf-8")
    (tmp_path / "text.txt").write_text("hello", encoding="utf-8")
    client = TestClient(Starlette(routes=ui.ui_routes()))

    directory = client.get("/api/ui/files/preview", params={"path": "folder"})
    assert directory.json()["data"]["kind"] == "directory"
    text = client.get("/api/ui/files/preview", params={"path": "text.txt"})
    assert text.json()["data"]["kind"] == "text"
    missing = client.get("/api/ui/files/preview", params={"path": "missing"})
    assert missing.status_code == 400

    monkeypatch.setattr(ui, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(IsADirectoryError()))
    monkeypatch.setattr(ui, "list_dir", lambda *args, **kwargs: [{"path": "folder/child", "type": "file"}])
    recovered = client.get("/api/ui/files/preview", params={"path": "text.txt"})
    assert recovered.json()["data"]["kind"] == "directory"

    monkeypatch.setattr(ui, "list_shells", lambda: (_ for _ in ()).throw(RuntimeError("shells")))
    assert client.get("/api/ui/terminals").status_code == 400


def test_resolve_spawn_and_tui_cli_branches(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TUI_COMMAND", '"/tmp/tui binary" --flag')
    get_settings.cache_clear()
    assert ui.resolve_tui_command() == ["/tmp/tui binary", "--flag"]

    monkeypatch.delenv("LOCAL_SHELL_MCP_UI_TUI_COMMAND")
    get_settings.cache_clear()
    sidecar_name = "local-shell-mcp-tui.exe" if ui.os.name == "nt" else "local-shell-mcp-tui"
    candidate = tmp_path / sidecar_name
    candidate.write_text("x", encoding="utf-8")
    monkeypatch.setattr(ui.sys, "executable", str(tmp_path / "python"))
    assert ui.resolve_tui_command() == [str(candidate)]
    candidate.unlink()

    def fail_materialize(_state_dir):
        raise PermissionError("denied")

    with monkeypatch.context() as scoped:
        scoped.setattr(ui.Path, "is_file", lambda self: False)
        scoped.setattr(ui, "materialize_embedded_tui", fail_materialize)
        with pytest.raises(RuntimeError, match="Unable to prepare embedded OpenTUI runtime"):
            ui.resolve_tui_command()

    source = tmp_path / "tui.tsx"
    source.write_text("x", encoding="utf-8")
    with monkeypatch.context() as scoped:
        scoped.setattr(ui.Path, "is_file", lambda self: False)
        scoped.setattr(ui, "_tui_source_path", lambda: source)
        scoped.setattr(ui.shutil, "which", lambda name: "/usr/bin/bun")
        assert ui.resolve_tui_command() == ["/usr/bin/bun", str(source)]
        scoped.setattr(ui.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError, match="Bun"):
            ui.resolve_tui_command()
        scoped.setattr(ui, "_tui_source_path", lambda: None)
        with pytest.raises(RuntimeError, match="runtime not found"):
            ui.resolve_tui_command()

    captured = {}

    class FakeUnix:
        def __init__(self, command, env, cols, rows):
            captured.update(command=command, env=env, cols=cols, rows=rows)

    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TUI_COMMAND", "/tmp/tui")
    get_settings.cache_clear()
    monkeypatch.setattr(ui, "_UnixPtyProcess", FakeUnix)
    os_proxy = SimpleNamespace(**{**vars(os), "name": "posix"})
    monkeypatch.setattr(ui, "os", os_proxy)
    monkeypatch.setattr(ui, "resolve_tui_command", lambda: ["/tmp/tui"])
    ui._spawn_tui_process(80, 24, 2.75)
    assert captured["env"]["LOCAL_SHELL_MCP_UI_MODE"] == "web"
    assert captured["env"]["TERM"] == "xterm-256color"
    assert captured["env"]["COLORTERM"] == "truecolor"
    assert captured["env"]["TERM_PROGRAM"] == "vscode"
    assert captured["env"]["TERM_PROGRAM_VERSION"] == "local-shell-mcp"
    assert captured["env"]["LOCAL_SHELL_MCP_UI_CELL_ASPECT"] == "2.7500"

    monkeypatch.setattr(ui, "resolve_tui_command", lambda: ["tui"])
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=7))
    with pytest.raises(SystemExit) as raised:
        ui.run_tui_cli(["--api-base", "http://localhost:8765/api/ui"])
    assert raised.value.code == 7

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "run", interrupted)
    with pytest.raises(SystemExit) as raised:
        ui.run_tui_cli([])
    assert raised.value.code == 130
    with pytest.raises(SystemExit):
        ui.run_tui_cli(["--api-base", "https://public.test/api/ui"])


def test_unix_and_windows_pty_edge_branches(monkeypatch):
    unix = ui._UnixPtyProcess.__new__(ui._UnixPtyProcess)
    unix.master_fd = 5
    reads = iter([BlockingIOError(), b"data"])

    def read(fd, size):
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(ui.os, "read", read)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(ui.asyncio, "sleep", lambda delay: real_sleep(0))
    assert asyncio.run(unix.read()) == b"data"
    monkeypatch.setattr(ui.os, "read", lambda *args: (_ for _ in ()).throw(OSError()))
    assert asyncio.run(unix.read()) == b""
    monkeypatch.setattr(ui.os, "write", lambda *args: 0)
    with pytest.raises(OSError, match="no progress"):
        unix._write_all(b"x")

    class FakeStruct:
        def pack(self, *args):
            return b"size"

    calls = []
    unix._struct = FakeStruct()
    unix._fcntl = SimpleNamespace(ioctl=lambda *args: calls.append(args))
    unix._termios = SimpleNamespace(TIOCSWINSZ=1)
    unix.process = SimpleNamespace(pid=12, poll=lambda: None)
    monkeypatch.setattr(ui.signal, "SIGWINCH", getattr(signal, "SIGWINCH", 28), raising=False)
    monkeypatch.setattr(ui.os, "killpg", lambda *args: calls.append(args), raising=False)
    unix.resize(80, 24)
    assert calls

    class Process:
        def __init__(self):
            self.polls = iter([None, None])
            self.pid = 12

        def poll(self):
            return next(self.polls)

        def wait(self):
            raise RuntimeError("wait")

    unix.process = Process()
    monkeypatch.setattr(ui.signal, "SIGTERM", signal.SIGTERM, raising=False)
    monkeypatch.setattr(ui.signal, "SIGKILL", getattr(signal, "SIGKILL", 9), raising=False)
    monkeypatch.setattr(ui.os, "close", lambda fd: None)
    kills = []
    monkeypatch.setattr(ui.os, "killpg", lambda pid, sig: kills.append(sig), raising=False)
    asyncio.run(unix.close())
    assert ui.signal.SIGTERM in kills and ui.signal.SIGKILL in kills

    fake_winpty = types.ModuleType("winpty")

    class Spawned:
        def __init__(self):
            self.read_calls = 0

        def setwinsize(self, rows, cols):
            self.size = (rows, cols)

        def read(self, *args):
            self.read_calls += 1
            if self.read_calls == 1:
                raise TypeError
            return "text"

        def write(self, text):
            return object()

        def terminate(self, force):
            self.terminated = force

    spawned = Spawned()

    class PtyProcess:
        calls = 0

        @classmethod
        def spawn(cls, command, **kwargs):
            cls.calls += 1
            if cls.calls == 1:
                raise TypeError
            return spawned

    fake_winpty.PtyProcess = PtyProcess
    monkeypatch.setitem(sys.modules, "winpty", fake_winpty)
    windows = ui._WindowsPtyProcess(["cmd", "/c", "echo"], {}, 80, 24)
    windows.resize(70, 20)
    assert spawned.size == (20, 70)
    assert asyncio.run(windows.read()) == b"text"
    with pytest.raises(OSError, match="Unexpected"):
        asyncio.run(windows.write(b"x"))
    asyncio.run(windows.close())
    assert spawned.terminated is True
    spawned.read = lambda *args: (_ for _ in ()).throw(RuntimeError("read"))
    assert asyncio.run(windows.read()) == b""


def test_websocket_control_flow_and_limits(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Process:
        def __init__(self, reads=None, *, exit_code=None):
            self.reads = list(reads or [b""])
            self.writes = []
            self.resizes = []
            self.closed = False
            self.return_code = exit_code

        async def read(self):
            if self.reads:
                return self.reads.pop(0)
            await asyncio.sleep(0.05)
            return b""

        async def write(self, data):
            self.writes.append(data)

        async def exit_code(self):
            return self.return_code

        def resize(self, cols, rows):
            self.resizes.append((cols, rows))

        async def close(self):
            self.closed = True

    class Socket:
        def __init__(self, messages=None, *, headers=None, query=None, fail_accept=False):
            self.headers = headers or {"sec-websocket-protocol": "lsm-ui"}
            self.query_params = query or {}
            self.messages = list(messages or [])
            self.closed = []
            self.sent = []
            self.accepted = None
            self.fail_accept = fail_accept

        async def accept(self, subprotocol=None):
            if self.fail_accept:
                raise RuntimeError("accept")
            self.accepted = subprotocol

        async def close(self, code=1000, reason=""):
            self.closed.append((code, reason))

        async def send_bytes(self, data):
            self.sent.append(data)

        async def receive(self):
            await asyncio.sleep(0)
            if self.messages:
                return self.messages.pop(0)
            return {"type": "websocket.disconnect"}

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: False)
    unauthorized = Socket()
    asyncio.run(ui.ui_terminal_websocket(unauthorized))
    assert unauthorized.closed[0][0] == 4401

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    ui._ACTIVE_UI_TERMINALS.clear()
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS", "1")
    get_settings.cache_clear()
    ui._ACTIVE_UI_TERMINALS.add(1)
    limited = Socket()
    asyncio.run(ui.ui_terminal_websocket(limited))
    assert limited.closed[0][0] == 4429
    ui._ACTIVE_UI_TERMINALS.clear()

    failed_accept = Socket(fail_accept=True)
    with pytest.raises(RuntimeError, match="accept"):
        asyncio.run(ui.ui_terminal_websocket(failed_accept))
    assert id(failed_accept) not in ui._ACTIVE_UI_TERMINALS

    monkeypatch.setattr(ui, "_spawn_tui_process", lambda *args: (_ for _ in ()).throw(RuntimeError("spawn")))
    spawn_failure = Socket()
    asyncio.run(ui.ui_terminal_websocket(spawn_failure))
    assert b"Unable to start the TUI" in spawn_failure.sent[0]
    assert spawn_failure.closed[-1][0] == 1011

    class WaitingSocket(Socket):
        async def receive(self):
            await asyncio.sleep(0.05)
            return {"type": "websocket.disconnect"}

    process = Process([b""], exit_code=0)
    monkeypatch.setattr(ui, "_spawn_tui_process", lambda *args: process)
    exited = WaitingSocket()
    asyncio.run(ui.ui_terminal_websocket(exited))
    assert any(code == ui.UI_TUI_EXIT_CODE for code, _ in exited.closed)

    process = Process([b""], exit_code=1)
    monkeypatch.setattr(ui, "_spawn_tui_process", lambda *args: process)
    crashed = WaitingSocket()
    asyncio.run(ui.ui_terminal_websocket(crashed))
    assert all(code != ui.UI_TUI_EXIT_CODE for code, _ in crashed.closed)

    process = Process([b"hello"])
    spawn_calls = []
    monkeypatch.setattr(
        ui,
        "_spawn_tui_process",
        lambda *args: spawn_calls.append(args) or process,
    )
    messages = [
        {"type": "websocket.receive", "bytes": b"bytes"},
        {"type": "websocket.receive", "text": "raw text"},
        {"type": "websocket.receive", "text": "[]"},
        {"type": "websocket.receive", "text": ""},
        {
            "type": "websocket.receive",
            "text": json.dumps({"type": "resize", "cols": 90, "rows": 30}),
        },
        {"type": "websocket.disconnect"},
    ]
    socket = Socket(messages, query={"cols": "80", "rows": "24", "cell_aspect": "2.75"})
    asyncio.run(ui.ui_terminal_websocket(socket))
    assert socket.accepted == "lsm-ui"
    assert spawn_calls == [(80, 24, 2.75)]
    assert b"hello" in socket.sent
    assert b"bytes" in process.writes
    assert b"raw text" in process.writes
    assert process.closed is True

    process = Process([b"keep-running"] * 10)
    monkeypatch.setattr(ui, "_spawn_tui_process", lambda *args: process)
    invalid_resize = Socket(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "resize", "cols": "wide", "rows": 30}),
            }
        ]
    )
    asyncio.run(ui.ui_terminal_websocket(invalid_resize))
    assert any(code == 4400 for code, _ in invalid_resize.closed)



def test_spawn_shell_process_selects_tmux_attachment_or_polling_bridge(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    spawned = []

    async def fake_dispatch(machine, local_call, remote_tool, remote_args):
        assert remote_tool == "shell_list"
        backend = "tmux-system" if machine == "local" else "tmux-worker"
        return {"sessions": [{"session_id": "demo", "backend": backend}]}

    class FakePty:
        def __init__(self, command, env, cols, rows):
            spawned.append((command, env, cols, rows))

    monkeypatch.setattr(ui, "_machine_dispatch", fake_dispatch)
    monkeypatch.setattr(ui, "resolve_tmux", lambda: SimpleNamespace(path="/usr/bin/tmux"))
    monkeypatch.setattr(ui, "tmux_socket_name", lambda: "lsm-test")
    monkeypatch.setattr(ui, "_UnixPtyProcess", FakePty)
    monkeypatch.setattr(ui, "os", SimpleNamespace(**{**vars(os), "name": "posix"}))

    local = asyncio.run(ui._spawn_shell_process("local", "demo", 100, 32))
    assert isinstance(local, FakePty)
    command, env, cols, rows = spawned[0]
    assert command == [
        "/usr/bin/tmux",
        "-L",
        "lsm-test",
        "attach-session",
        "-t",
        "=demo",
    ]
    assert env["TERM"] == "xterm-256color"
    assert (cols, rows) == (100, 32)

    remote = asyncio.run(ui._spawn_shell_process("worker", "demo", 80, 24))
    assert isinstance(remote, ui._PollingShellProcess)
    assert remote.machine == "worker"

    with pytest.raises(ValueError, match="not found"):
        async def missing(machine, local_call, remote_tool, remote_args):
            return {"sessions": []}

        monkeypatch.setattr(ui, "_machine_dispatch", missing)
        asyncio.run(ui._spawn_shell_process("local", "missing", 80, 24))


@pytest.mark.asyncio
async def test_tmux_scrollback_uses_copy_mode_without_replacing_terminal_stream(monkeypatch):
    process = SimpleNamespace(_tmux_session_id="demo.test")
    history = 900
    position = 0
    mode = ""
    calls = []

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        nonlocal position, mode
        calls.append(list(args))
        assert bypass_limit is True
        if args[0] == "display-message":
            return SimpleNamespace(ok=True, stdout=f"{history}\t{mode}\t{position if mode == 'copy-mode' else ''}\n", stderr="")
        if args[0] == "copy-mode":
            mode = "copy-mode"
            position = 0
            return SimpleNamespace(ok=True, stdout="", stderr="")
        if args[:2] == ["send-keys", "-X"] and args[-1] == "history-bottom":
            position = 0
            return SimpleNamespace(ok=True, stdout="", stderr="")
        if args[0] == "send-keys" and args[-1] == "scroll-up":
            position = int(args[args.index("-N") + 1])
            return SimpleNamespace(ok=True, stdout="", stderr="")
        if args[:2] == ["send-keys", "-X"] and args[-1] == "cancel":
            mode = ""
            position = 0
            return SimpleNamespace(ok=True, stdout="", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(ui, "tmux", fake_tmux)

    state = await ui._tmux_scrollback_state(process)
    assert state == {
        "type": "scrollback",
        "supported": True,
        "history": 900,
        "position": 0,
        "copy_mode": False,
    }

    state = await ui._tmux_scroll_to(process, 120)
    assert state["position"] == 120
    assert any(call[0] == "copy-mode" for call in calls)
    assert any(call[-1] == "history-bottom" for call in calls)
    assert any(call[-1] == "scroll-up" and call[call.index("-N") + 1] == "120" for call in calls)

    state = await ui._tmux_scroll_to(process, 0)
    assert state["position"] == 0
    assert any(call[-1] == "cancel" for call in calls)
    assert all(call[call.index("-t") + 1] == "=demo.test:" for call in calls if "-t" in call)

    unsupported = await ui._tmux_scrollback_state(SimpleNamespace())
    assert unsupported == {
        "type": "scrollback",
        "supported": False,
        "history": 0,
        "position": 0,
        "copy_mode": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "message"),
    [
        (SimpleNamespace(ok=False, stdout="", stderr="boom"), "boom"),
        (SimpleNamespace(ok=True, stdout="broken\n", stderr=""), "Unexpected tmux scrollback state"),
        (SimpleNamespace(ok=True, stdout="bad\tcopy-mode\t3\n", stderr=""), "Invalid tmux scrollback state"),
    ],
)
async def test_tmux_scrollback_state_rejects_invalid_tmux_results(monkeypatch, result, message):
    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        return result

    monkeypatch.setattr(ui, "tmux", fake_tmux)

    with pytest.raises(RuntimeError, match=message):
        await ui._tmux_scrollback_state(SimpleNamespace(_tmux_session_id="demo"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("cancel", "leave"),
        ("copy-mode", "enter"),
        ("history-bottom", "scroll"),
        ("scroll-up", "scroll"),
    ],
)
async def test_tmux_scroll_reports_control_failures(monkeypatch, failure, message):
    mode = "copy-mode" if failure == "cancel" else ""
    position = 3 if failure == "cancel" else 0

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        nonlocal mode, position
        if args[0] == "display-message":
            return SimpleNamespace(ok=True, stdout=f"20\t{mode}\t{position if mode else ''}\n", stderr="")
        action = "copy-mode" if args[0] == "copy-mode" else args[-1]
        if action == failure:
            return SimpleNamespace(ok=False, stdout="", stderr="")
        if args[0] == "copy-mode":
            mode = "copy-mode"
        return SimpleNamespace(ok=True, stdout="", stderr="")

    monkeypatch.setattr(ui, "tmux", fake_tmux)
    target = 0 if failure == "cancel" else 8

    with pytest.raises(RuntimeError, match=message):
        await ui._tmux_scroll_to(SimpleNamespace(_tmux_session_id="demo"), target)


@pytest.mark.asyncio
async def test_tmux_scroll_reuses_copy_mode_at_same_position(monkeypatch):
    calls = []

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        calls.append(list(args))
        return SimpleNamespace(ok=True, stdout="50\tcopy-mode\t12\n", stderr="")

    monkeypatch.setattr(ui, "tmux", fake_tmux)

    state = await ui._tmux_scroll_to(SimpleNamespace(_tmux_session_id="demo"), 12)

    assert state["position"] == 12
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tmux_scrollback_cleanup_waits_for_last_attachment(monkeypatch):
    copy_mode = False
    scroll_requests = []
    process = SimpleNamespace(_tmux_session_id="shared")

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 50,
            "position": 8 if copy_mode else 0,
            "copy_mode": copy_mode,
        }

    async def fake_scroll(process, position, pane_id=None):
        nonlocal copy_mode
        scroll_requests.append(position)
        copy_mode = position > 0
        return await fake_state(process)

    _stub_tmux_scrollback(monkeypatch, fake_state)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)

    first = await ui._register_tmux_scrollback_attachment(process, 1)
    second = await ui._register_tmux_scrollback_attachment(process, 2)
    copy_mode = True
    assert first is not None
    first[1].owned_copy_mode = True

    await ui._release_tmux_scrollback_attachment(process, 2, second)
    assert scroll_requests == []
    assert copy_mode is True

    await ui._release_tmux_scrollback_attachment(process, 1, first)
    assert scroll_requests == [0]
    assert copy_mode is False


@pytest.mark.asyncio
async def test_tmux_scrollback_cleanup_restores_preexisting_copy_position(monkeypatch):
    copy_mode = True
    position = 17
    calls = []
    process = SimpleNamespace(_tmux_session_id="shared")

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 50,
            "position": position if copy_mode else 0,
            "copy_mode": copy_mode,
        }

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        nonlocal copy_mode, position
        calls.append(list(args))
        assert bypass_limit is True
        if args[0] == "copy-mode":
            copy_mode = True
            position = 0
            return SimpleNamespace(ok=True, stdout="", stderr="")
        if args[:2] == ["send-keys", "-X"] and args[-1] == "history-bottom":
            position = 0
            return SimpleNamespace(ok=True, stdout="", stderr="")
        if args[0] == "send-keys" and args[-1] == "scroll-up":
            position = int(args[args.index("-N") + 1])
            return SimpleNamespace(ok=True, stdout="", stderr="")
        raise AssertionError(args)

    _stub_tmux_scrollback(monkeypatch, fake_state)
    monkeypatch.setattr(ui, "tmux", fake_tmux)

    registration = await ui._register_tmux_scrollback_attachment(process, 1)
    copy_mode = False
    position = 0

    await ui._release_tmux_scrollback_attachment(process, 1, registration)

    assert copy_mode is True
    assert position == 17
    assert ["copy-mode", "-t", "%1"] in calls
    assert ["send-keys", "-X", "-t", "%1", "history-bottom"] in calls
    assert ["send-keys", "-N", "17", "-X", "-t", "%1", "scroll-up"] in calls


@pytest.mark.asyncio
async def test_tmux_scrollback_attachment_coordination_error_paths(monkeypatch):
    assert await ui._register_tmux_scrollback_attachment(SimpleNamespace(), 1) is None
    await ui._release_tmux_scrollback_attachment(SimpleNamespace(), 1, None)

    process = SimpleNamespace(_tmux_session_id="error-case")

    async def failing_state(process):
        raise RuntimeError("state failed")

    monkeypatch.setattr(ui, "_tmux_scrollback_state", failing_state)
    registration = await ui._register_tmux_scrollback_attachment(process, 2)
    assert registration is None
    assert "error-case" not in ui._TMUX_SCROLLBACK_ATTACHMENTS

    stale_group = ui._TmuxScrollbackAttachmentGroup()
    await ui._release_tmux_scrollback_attachment(process, 3, ("missing", stale_group))

    cleanup_group = ui._TmuxScrollbackAttachmentGroup()
    cleanup_group.initial_copy_mode = False
    cleanup_group.members.add(4)
    ui._TMUX_SCROLLBACK_ATTACHMENTS["cleanup-error"] = cleanup_group
    cleanup_process = SimpleNamespace(_tmux_session_id="cleanup-error")
    await ui._release_tmux_scrollback_attachment(
        cleanup_process, 4, ("cleanup-error", cleanup_group)
    )
    assert "cleanup-error" not in ui._TMUX_SCROLLBACK_ATTACHMENTS


@pytest.mark.asyncio
async def test_tmux_scrollback_requests_are_serialized_per_session(monkeypatch):
    group = ui._TmuxScrollbackAttachmentGroup()
    group.initial_copy_mode = False
    registration = ("shared", group)
    process = SimpleNamespace(_tmux_session_id="shared")
    position = 0
    active = 0
    max_active = 0

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": position,
            "copy_mode": position > 0,
        }

    async def fake_scroll(process, requested, pane_id=None):
        nonlocal active, max_active, position
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        position = requested
        active -= 1
        return await fake_state(process)

    _stub_tmux_scrollback(monkeypatch, fake_state)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)

    await asyncio.gather(
        ui._tmux_apply_scrollback_request(process, registration, {"position": 20}),
        ui._tmux_apply_scrollback_request(process, registration, {"position": 35}),
    )

    assert max_active == 1
    assert position == 35
    assert group.owned_copy_mode is True


@pytest.mark.asyncio
async def test_tmux_scrollback_requests_retarget_after_active_pane_change(monkeypatch):
    group = ui._TmuxScrollbackAttachmentGroup()
    group.initial_copy_mode = False
    group.initial_position = 0
    group.owned_copy_mode = True
    group.pane_id = "%7"
    registration = ("shared", group)
    process = SimpleNamespace(_tmux_session_id="shared")
    targets = []

    async def fake_state(process, pane_id=None):
        targets.append(("state", pane_id))
        if pane_id == "%7":
            return {
                "type": "scrollback",
                "supported": True,
                "history": 100,
                "position": 9,
                "copy_mode": True,
            }
        return {
            "type": "scrollback",
            "supported": True,
            "history": 200,
            "position": 0,
            "copy_mode": False,
        }

    async def fake_baseline(process):
        return await fake_state(process, "%8"), "%8"

    async def fake_scroll(process, requested, pane_id=None):
        targets.append(("scroll", pane_id, requested))
        return {
            "type": "scrollback",
            "supported": True,
            "history": 200,
            "position": requested,
            "copy_mode": requested > 0,
        }

    monkeypatch.setattr(ui, "_tmux_scrollback_state", fake_state)
    monkeypatch.setattr(ui, "_tmux_scrollback_baseline", fake_baseline)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)

    await ui._tmux_apply_scrollback_request(process, registration, {"position": 12})

    assert ("state", "%7") in targets
    assert ("scroll", "%7", 0) in targets
    assert ("scroll", "%8", 12) in targets
    assert group.pane_id == "%8"
    assert group.initial_copy_mode is False
    assert group.owned_copy_mode is True


@pytest.mark.asyncio
async def test_tmux_terminal_input_leaves_webui_owned_copy_mode(monkeypatch):
    group = ui._TmuxScrollbackAttachmentGroup()
    group.initial_copy_mode = False
    group.owned_copy_mode = True
    group.pane_id = "%1"
    registration = ("shared", group)
    events = []

    class Process:
        _tmux_session_id = "shared"

        async def write(self, data):
            events.append(("write", data))

    async def fake_baseline(process):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 8,
            "copy_mode": True,
        }, "%1"

    async def fake_scroll(process, position, pane_id=None):
        events.append(("scroll", position))
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 0,
            "copy_mode": False,
        }

    monkeypatch.setattr(ui, "_tmux_scrollback_baseline", fake_baseline)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)

    await ui._tmux_write_terminal_input(Process(), registration, b"echo ok\r")

    assert events == [("scroll", 0), ("write", b"echo ok\r")]
    assert group.owned_copy_mode is False


@pytest.mark.asyncio
async def test_tmux_mouse_sync_claims_copy_mode_before_next_input(monkeypatch):
    group = ui._TmuxScrollbackAttachmentGroup()
    group.initial_copy_mode = False
    group.pane_id = "%1"
    registration = ("shared", group)
    copy_mode = True
    events = []

    class Process:
        _tmux_session_id = "shared"

        async def write(self, data):
            events.append(("write", data))

    async def fake_baseline(process):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 6 if copy_mode else 0,
            "copy_mode": copy_mode,
        }, "%1"

    async def fake_scroll(process, position, pane_id=None):
        nonlocal copy_mode
        events.append(("scroll", position))
        copy_mode = position > 0
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": position,
            "copy_mode": copy_mode,
        }

    monkeypatch.setattr(ui, "_tmux_scrollback_baseline", fake_baseline)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)

    state = await ui._tmux_claim_scrollback_state(Process(), registration)
    assert state["copy_mode"] is True
    assert group.owned_copy_mode is True

    await ui._tmux_write_terminal_input(Process(), registration, b"echo ok\r")

    assert events == [("scroll", 0), ("write", b"echo ok\r")]
    assert group.owned_copy_mode is False


@pytest.mark.asyncio
async def test_tmux_keyboard_binding_claims_copy_mode_before_following_input(monkeypatch):
    group = ui._TmuxScrollbackAttachmentGroup()
    group.initial_copy_mode = False
    group.pane_id = "%1"
    registration = ("shared", group)
    copy_mode = False
    events = []

    class Process:
        _tmux_session_id = "shared"

        async def write(self, data):
            nonlocal copy_mode
            events.append(("write", data))
            if data == b"[":
                copy_mode = True

    async def fake_baseline(process):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 5 if copy_mode else 0,
            "copy_mode": copy_mode,
        }, "%1"

    async def fake_scroll(process, position, pane_id=None):
        nonlocal copy_mode
        events.append(("scroll", position))
        copy_mode = position > 0
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": position,
            "copy_mode": copy_mode,
        }

    monkeypatch.setattr(ui, "_tmux_scrollback_baseline", fake_baseline)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)

    process = Process()
    await ui._tmux_write_terminal_input(process, registration, b"\x02")
    assert group.prefix_pending is True
    await ui._tmux_write_terminal_input(process, registration, b"[")
    assert group.binding_sync_pending is True
    await ui._tmux_write_terminal_input(process, registration, b"x")

    assert events == [
        ("write", b"\x02"),
        ("write", b"["),
        ("scroll", 0),
        ("write", b"x"),
    ]
    assert copy_mode is False
    assert group.owned_copy_mode is False
    assert group.binding_sync_pending is False


@pytest.mark.asyncio
async def test_tmux_failed_scroll_rolls_back_owned_copy_mode(monkeypatch):
    group = ui._TmuxScrollbackAttachmentGroup()
    group.initial_copy_mode = False
    group.pane_id = "%1"
    registration = ("shared", group)
    copy_mode = False
    requests = []

    async def fake_baseline(process):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 4 if copy_mode else 0,
            "copy_mode": copy_mode,
        }, "%1"

    async def fake_state(process, pane_id=None):
        return (await fake_baseline(process))[0]

    async def fake_scroll(process, position, pane_id=None):
        nonlocal copy_mode
        requests.append(position)
        if position:
            copy_mode = True
            raise RuntimeError("partial scroll failure")
        copy_mode = False
        return await fake_state(process, pane_id)

    monkeypatch.setattr(ui, "_tmux_scrollback_baseline", fake_baseline)
    monkeypatch.setattr(ui, "_tmux_scrollback_state", fake_state)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)

    with pytest.raises(RuntimeError, match="partial scroll failure"):
        await ui._tmux_apply_scrollback_request(
            SimpleNamespace(_tmux_session_id="shared"), registration, {"position": 20}
        )

    assert requests == [20, 0]
    assert copy_mode is False
    assert group.owned_copy_mode is False


@pytest.mark.asyncio
async def test_tmux_scrollback_state_suppresses_internal_audit(monkeypatch):
    active = False

    class AuditContext:
        def __enter__(self):
            nonlocal active
            active = True

        def __exit__(self, exc_type, exc, tb):
            nonlocal active
            active = False

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        assert active is True
        return SimpleNamespace(ok=True, stdout="10\t\t\n", stderr="")

    monkeypatch.setattr(ui, "suppress_audit", lambda: AuditContext())
    monkeypatch.setattr(ui, "tmux", fake_tmux)

    state = await ui._tmux_scrollback_state(SimpleNamespace(_tmux_session_id="demo"))

    assert state["history"] == 10
    assert active is False


@pytest.mark.asyncio
async def test_tmux_scroll_mutations_suppress_internal_audit(monkeypatch):
    active = False
    calls = []

    class AuditContext:
        def __enter__(self):
            nonlocal active
            active = True

        def __exit__(self, exc_type, exc, tb):
            nonlocal active
            active = False

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 0,
            "copy_mode": False,
        }

    async def fake_tmux(args, timeout_s=10, *, bypass_limit=False):
        assert active is True
        assert bypass_limit is True
        calls.append(list(args))
        return SimpleNamespace(ok=True, stdout="", stderr="")

    monkeypatch.setattr(ui, "suppress_audit", lambda: AuditContext())
    monkeypatch.setattr(ui, "_tmux_scrollback_state", fake_state)
    monkeypatch.setattr(ui, "tmux", fake_tmux)

    await ui._tmux_scroll_to(SimpleNamespace(_tmux_session_id="demo"), 5, "%9")

    assert ["copy-mode", "-t", "%9"] in calls
    assert ["send-keys", "-X", "-t", "%9", "history-bottom"] in calls
    assert ["send-keys", "-N", "5", "-X", "-t", "%9", "scroll-up"] in calls
    assert active is False


@pytest.mark.asyncio
async def test_polling_shell_process_streams_snapshots_and_forwards_input(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    outputs = ["first screen", "first screen", "second screen"]
    calls = []

    async def fake_dispatch(machine, local_call, remote_tool, remote_args):
        calls.append((machine, remote_tool, remote_args))
        if remote_tool == "shell_read":
            return {"output": outputs.pop(0)}
        return {"ok": True}

    monkeypatch.setattr(ui, "_machine_dispatch", fake_dispatch)
    process = ui._PollingShellProcess("worker", "demo", 80, 24)

    first = await process.read()
    second = await process.read()
    await process.write(b"echo ok\r")
    await process.resize(120, 40)
    await process.close()

    assert first.startswith(b"\x1b[?25l\x1b[3J\x1b[H\x1b[2J")
    assert b"first screen" in first
    assert b"second screen" in second
    assert ("worker", "shell_send", {"session_id": "demo", "input_text": "echo ok\r", "enter": False}) in calls
    assert ("worker", "shell_resize", {"session_id": "demo", "cols": 120, "rows": 40}) in calls
    assert await process.read() == b""


@pytest.mark.asyncio
async def test_polling_shell_process_stops_after_repeated_read_failures(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    attempts = 0

    async def failing_dispatch(machine, local_call, remote_tool, remote_args):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(ui, "_machine_dispatch", failing_dispatch)
    process = ui._PollingShellProcess("worker", "demo", 80, 24)

    message = await process.read()
    await process.write(b"ignored after close")

    assert attempts == 3
    assert b"Persistent terminal stream stopped" in message
    assert b"worker unavailable" in message
    assert await process.exit_code() == 1


@pytest.mark.asyncio
async def test_native_shell_websocket_forwards_stream_input_and_resize(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Process:
        def __init__(self):
            self.reads = [b"hello"]
            self.writes = []
            self.resizes = []
            self.closed = False

        async def read(self):
            if self.reads:
                return self.reads.pop(0)
            await asyncio.sleep(0.05)
            return b""

        async def write(self, data):
            self.writes.append(data)

        async def resize(self, cols, rows):
            self.resizes.append((cols, rows))

        async def exit_code(self):
            return None

        async def close(self):
            self.closed = True

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {"machine": "worker", "session_id": "demo", "cols": "90", "rows": "30"}

        def __init__(self):
            self.messages = [
                {"type": "websocket.receive", "bytes": b"raw"},
                {"type": "websocket.receive", "text": "plain"},
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "resize", "cols": 100, "rows": 35}),
                },
                {"type": "websocket.disconnect"},
            ]
            self.sent = []
            self.closed = []
            self.accepted = None

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def close(self, code=1000, reason=""):
            self.closed.append((code, reason))

        async def send_bytes(self, data):
            self.sent.append(data)

        async def receive(self):
            await asyncio.sleep(0)
            return self.messages.pop(0)

    process = Process()
    spawn_calls = []

    async def fake_spawn(*args):
        spawn_calls.append(args)
        return process

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    ui._ACTIVE_UI_TERMINALS.clear()
    socket = Socket()

    await ui.ui_shell_websocket(socket)

    assert socket.accepted == "lsm-ui"
    assert spawn_calls == [("worker", "demo", 90, 30)]
    assert b"hello" in socket.sent
    assert b"raw" in process.writes
    assert b"plain" in process.writes
    assert process.resizes == [(100, 35)]
    assert process.closed is True
    assert id(socket) not in ui._ACTIVE_UI_TERMINALS


@pytest.mark.asyncio
async def test_native_shell_websocket_exposes_opt_in_tmux_scrollback(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Process:
        _tmux_session_id = "demo"

        async def read(self):
            await asyncio.sleep(0.05)
            return b""

        async def write(self, data):
            raise AssertionError(data)

        async def resize(self, cols, rows):
            return None

        async def exit_code(self):
            return None

        async def close(self):
            return None

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {
            "machine": "local",
            "session_id": "demo",
            "cols": "90",
            "rows": "30",
            "scrollback": "1",
        }

        def __init__(self):
            self.messages = [
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "scrollback", "offset": 5}),
                },
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "scrollback", "position": 42, "request_id": 7}),
                },
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "scrollback-sync"}),
                },
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "resize", "cols": 100, "rows": 35}),
                },
                {"type": "websocket.disconnect"},
            ]
            self.sent_text = []

        async def accept(self, subprotocol=None):
            return None

        async def close(self, code=1000, reason=""):
            return None

        async def send_bytes(self, data):
            raise AssertionError(data)

        async def send_text(self, data):
            self.sent_text.append(json.loads(data))

        async def receive(self):
            await asyncio.sleep(0)
            return self.messages.pop(0)

    async def fake_spawn(*args):
        return Process()

    requested = []
    syncs = []

    async def fake_state(process, pane_id=None):
        position = requested[-1] if requested else 10
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": position,
            "copy_mode": bool(requested and position > 0),
        }

    async def fake_scroll(process, position, pane_id=None):
        requested.append(position)
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": position,
            "copy_mode": position > 0,
        }

    async def fake_claim(process, registration):
        syncs.append(registration[1].pane_id)
        return await fake_state(process, registration[1].pane_id)

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    _stub_tmux_scrollback(monkeypatch, fake_state)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)
    monkeypatch.setattr(ui, "_tmux_claim_scrollback_state", fake_claim)
    ui._ACTIVE_UI_TERMINALS.clear()
    socket = Socket()

    await ui.ui_shell_websocket(socket)

    assert requested == [15, 42, 0]
    assert syncs == ["%1"]
    assert socket.sent_text[0] == {
        "type": "scrollback",
        "supported": True,
        "history": 100,
        "position": 10,
        "copy_mode": False,
    }
    assert any(message["position"] == 15 for message in socket.sent_text)
    assert any(message["position"] == 42 for message in socket.sent_text)
    assert any(message.get("request_id") == 7 for message in socket.sent_text)


@pytest.mark.asyncio
async def test_native_shell_websocket_acks_failed_scrollback_request(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Process:
        _tmux_session_id = "demo"

        async def read(self):
            await asyncio.sleep(0.05)
            return b""

        async def write(self, data):
            return None

        async def resize(self, cols, rows):
            return None

        async def exit_code(self):
            return None

        async def close(self):
            return None

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {"machine": "local", "session_id": "demo", "scrollback": "1"}

        def __init__(self):
            self.messages = [
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {"type": "scrollback", "position": 25, "request_id": 9}
                    ),
                },
                {"type": "websocket.disconnect"},
            ]
            self.sent_text = []

        async def accept(self, subprotocol=None):
            return None

        async def close(self, code=1000, reason=""):
            return None

        async def send_bytes(self, data):
            return None

        async def send_text(self, data):
            self.sent_text.append(json.loads(data))

        async def receive(self):
            await asyncio.sleep(0)
            return self.messages.pop(0)

    async def fake_spawn(*args):
        return Process()

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 0,
            "copy_mode": False,
        }

    async def failing_scroll(process, position, pane_id=None):
        raise RuntimeError("tmux mutation failed")

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    _stub_tmux_scrollback(monkeypatch, fake_state)
    monkeypatch.setattr(ui, "_tmux_scroll_to", failing_scroll)
    ui._ACTIVE_UI_TERMINALS.clear()
    socket = Socket()

    await ui.ui_shell_websocket(socket)

    assert {"type": "scrollback-ack", "request_id": 9} in socket.sent_text


@pytest.mark.asyncio
async def test_native_shell_websocket_sends_trailing_scrollback_refresh(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    history = 0

    class Process:
        _tmux_session_id = "demo"

        def __init__(self):
            self.reads = 0

        async def read(self):
            nonlocal history
            self.reads += 1
            if self.reads == 1:
                history = 12
                return b"fast output"
            await asyncio.sleep(2)
            return b""

        async def write(self, data):
            return None

        async def resize(self, cols, rows):
            return None

        async def exit_code(self):
            return None

        async def close(self):
            return None

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {"machine": "local", "session_id": "demo", "scrollback": "1"}

        def __init__(self):
            self.sent_text = []

        async def accept(self, subprotocol=None):
            return None

        async def close(self, code=1000, reason=""):
            return None

        async def send_bytes(self, data):
            return None

        async def send_text(self, data):
            self.sent_text.append(json.loads(data))

        async def receive(self):
            await asyncio.sleep(0.85)
            return {"type": "websocket.disconnect"}

    async def fake_spawn(*args):
        return Process()

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": history,
            "position": 0,
            "copy_mode": False,
        }

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    _stub_tmux_scrollback(monkeypatch, fake_state)
    ui._ACTIVE_UI_TERMINALS.clear()
    socket = Socket()

    await ui.ui_shell_websocket(socket)

    histories = [message["history"] for message in socket.sent_text]
    assert histories[0] == 0
    assert 12 in histories[1:]


@pytest.mark.asyncio
async def test_native_shell_websocket_preserves_preexisting_tmux_copy_mode(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Process:
        _tmux_session_id = "demo"

        async def read(self):
            await asyncio.sleep(0.05)
            return b""

        async def write(self, data):
            return None

        async def resize(self, cols, rows):
            return None

        async def exit_code(self):
            return None

        async def close(self):
            return None

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {"machine": "local", "session_id": "demo", "scrollback": "1"}

        def __init__(self):
            self.messages = [
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "scrollback", "position": 20}),
                },
                {"type": "websocket.disconnect"},
            ]

        async def accept(self, subprotocol=None):
            return None

        async def close(self, code=1000, reason=""):
            return None

        async def send_bytes(self, data):
            return None

        async def send_text(self, data):
            return None

        async def receive(self):
            await asyncio.sleep(0)
            return self.messages.pop(0)

    async def fake_spawn(*args):
        return Process()

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 10,
            "copy_mode": True,
        }

    requested = []

    async def fake_scroll(process, position, pane_id=None):
        requested.append(position)
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": position,
            "copy_mode": True,
        }

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    _stub_tmux_scrollback(monkeypatch, fake_state)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)
    ui._ACTIVE_UI_TERMINALS.clear()

    await ui.ui_shell_websocket(Socket())

    assert requested == [20]


@pytest.mark.asyncio
async def test_native_shell_websocket_cleans_up_tmux_mouse_copy_mode(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    copy_mode = False
    requested = []

    class Process:
        _tmux_session_id = "demo"

        async def read(self):
            await asyncio.sleep(0.05)
            return b""

        async def write(self, data):
            nonlocal copy_mode
            assert data == b"mouse-wheel"
            copy_mode = True

        async def resize(self, cols, rows):
            return None

        async def exit_code(self):
            return None

        async def close(self):
            return None

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {"machine": "local", "session_id": "demo", "scrollback": "1"}

        def __init__(self):
            self.messages = [
                {"type": "websocket.receive", "bytes": b"mouse-wheel"},
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "scrollback-sync"}),
                },
                {"type": "websocket.disconnect"},
            ]

        async def accept(self, subprotocol=None):
            return None

        async def close(self, code=1000, reason=""):
            return None

        async def send_bytes(self, data):
            return None

        async def send_text(self, data):
            return None

        async def receive(self):
            await asyncio.sleep(0)
            return self.messages.pop(0)

    async def fake_spawn(*args):
        return Process()

    async def fake_state(process, pane_id=None):
        return {
            "type": "scrollback",
            "supported": True,
            "history": 100,
            "position": 12 if copy_mode else 0,
            "copy_mode": copy_mode,
        }

    async def fake_scroll(process, position, pane_id=None):
        nonlocal copy_mode
        requested.append(position)
        copy_mode = position > 0
        return await fake_state(process)

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    _stub_tmux_scrollback(monkeypatch, fake_state)
    monkeypatch.setattr(ui, "_tmux_scroll_to", fake_scroll)
    ui._ACTIVE_UI_TERMINALS.clear()

    await ui.ui_shell_websocket(Socket())

    assert requested == [0]
    assert copy_mode is False


@pytest.mark.asyncio
async def test_native_shell_websocket_rejects_invalid_scrollback_request(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Process:
        _tmux_session_id = "demo"

        async def read(self):
            await asyncio.sleep(0.05)
            return b""

        async def write(self, data):
            return None

        async def resize(self, cols, rows):
            return None

        async def exit_code(self):
            return None

        async def close(self):
            return None

    class Socket:
        headers = {"sec-websocket-protocol": "lsm-ui"}
        query_params = {"machine": "local", "session_id": "demo", "scrollback": "1"}

        def __init__(self):
            self.messages = [
                {
                    "type": "websocket.receive",
                    "text": '{"type":"scrollback","position":1e309}',
                }
            ]
            self.closed = []
            self.sent_text = []

        async def accept(self, subprotocol=None):
            return None

        async def close(self, code=1000, reason=""):
            self.closed.append((code, reason))

        async def send_bytes(self, data):
            return None

        async def send_text(self, data):
            self.sent_text.append(json.loads(data))

        async def receive(self):
            await asyncio.sleep(0)
            return self.messages.pop(0)

    async def fake_spawn(*args):
        return Process()

    async def fake_state(process, pane_id=None):
        return {"type": "scrollback", "supported": True, "history": 100, "position": 10}

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    _stub_tmux_scrollback(monkeypatch, fake_state)
    ui._ACTIVE_UI_TERMINALS.clear()
    socket = Socket()

    await ui.ui_shell_websocket(socket)

    assert (4400, "Invalid scrollback request") in socket.closed


@pytest.mark.asyncio
async def test_native_shell_websocket_rejects_unauthorized_full_and_invalid_requests(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch)

    class Socket:
        headers = {}

        def __init__(self, query=None):
            self.query_params = query or {}
            self.accepted = False
            self.sent = []
            self.closed = []

        async def accept(self, subprotocol=None):
            self.accepted = True

        async def close(self, code=1000, reason=""):
            self.closed.append((code, reason))

        async def send_bytes(self, data):
            self.sent.append(data)

    unauthorized = Socket()
    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: False)
    await ui.ui_shell_websocket(unauthorized)
    assert unauthorized.closed == [(4401, "OAuth authentication required")]

    monkeypatch.setattr(ui, "_authorize_websocket", lambda websocket: True)
    monkeypatch.setattr(
        ui,
        "get_settings",
        lambda: SimpleNamespace(ui_terminal_max_sessions=1),
    )
    ui._ACTIVE_UI_TERMINALS.clear()
    ui._ACTIVE_UI_TERMINALS.add(-1)
    full = Socket()
    await ui.ui_shell_websocket(full)
    assert full.closed == [(4429, "Too many active WebUI terminal sessions")]

    ui._ACTIVE_UI_TERMINALS.clear()
    invalid = Socket()
    await ui.ui_shell_websocket(invalid)
    assert invalid.accepted is True
    assert any(b"session_id is required" in data for data in invalid.sent)
    assert invalid.closed[-1][0] == 1011
    assert id(invalid) not in ui._ACTIVE_UI_TERMINALS


@pytest.mark.asyncio
async def test_native_shell_websocket_rejects_rotated_live_token(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="oauth")
    manager = get_live_channel_manager()
    logical_session_id = "s_websocket_rotation"
    workspace, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=logical_session_id,
    )
    encoded = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")

    class Process:
        def __init__(self):
            self.writes = []
            self.closed = False

        async def read(self):
            await asyncio.sleep(0.2)
            return b"late output"

        async def write(self, data):
            self.writes.append(data)

        async def resize(self, cols, rows):  # noqa: ARG002
            return None

        async def exit_code(self):
            return None

        async def close(self):
            self.closed = True

    class Socket:
        headers = {"sec-websocket-protocol": f"lsm-ui, bearer.{encoded}"}
        query_params = {"machine": "local", "session_id": "demo"}

        def __init__(self):
            self.closed = []
            self.sent = []
            self.rotated = False

        async def accept(self, subprotocol=None):  # noqa: ARG002
            return None

        async def close(self, code=1000, reason=""):
            self.closed.append((code, reason))

        async def send_bytes(self, data):
            self.sent.append(data)

        async def receive(self):
            if not self.rotated:
                self.rotated = True
                same_workspace, replacement = manager.open(
                    subject="user",
                    scopes=tuple(ALL_OAUTH_SCOPES),
                    logical_session_id=logical_session_id,
                )
                assert same_workspace is workspace
                assert replacement != token
            return {"type": "websocket.receive", "bytes": b"should-not-run"}

    process = Process()

    async def fake_spawn(*args):  # noqa: ARG001
        return process

    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    ui._ACTIVE_UI_TERMINALS.clear()
    socket = Socket()

    await ui.ui_shell_websocket(socket)

    assert any(code == 4401 and "rotated" in reason for code, reason in socket.closed)
    assert process.writes == []
    assert process.closed is True


def test_websocket_auth_none_rejects_rotated_live_bearer(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = get_live_channel_manager()
    logical_session_id = "s_websocket_auth_none"
    _, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=logical_session_id,
    )
    manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=logical_session_id,
    )
    encoded = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")

    class StaleSocket:
        headers = {"sec-websocket-protocol": f"lsm-ui, bearer.{encoded}"}

    class AnonymousSocket:
        headers = {"sec-websocket-protocol": "lsm-ui"}

    assert ui._authorize_websocket(StaleSocket()) is False
    assert ui._authorize_websocket(AnonymousSocket()) is True


@pytest.mark.asyncio
async def test_shell_websocket_retains_live_identity_when_token_rotates_during_auth(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = get_live_channel_manager()
    logical_session_id = "s_websocket_auth_race"
    _, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=logical_session_id,
    )
    encoded = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")

    class Process:
        def __init__(self):
            self.writes = []
            self.closed = False

        async def read(self):
            await asyncio.sleep(0.2)
            return b"late"

        async def write(self, data):
            self.writes.append(data)

        async def resize(self, cols, rows):  # noqa: ARG002
            return None

        async def exit_code(self):
            return None

        async def close(self):
            self.closed = True

    class Socket:
        headers = {"sec-websocket-protocol": f"lsm-ui, bearer.{encoded}"}
        query_params = {"machine": "local", "session_id": "demo"}

        def __init__(self):
            self.closed = []
            self.sent = []

        async def accept(self, subprotocol=None):  # noqa: ARG002
            return None

        async def close(self, code=1000, reason=""):
            self.closed.append((code, reason))

        async def send_bytes(self, data):
            self.sent.append(data)

        async def receive(self):
            return {"type": "websocket.receive", "bytes": b"should-not-run"}

    def rotate_during_authorization(websocket):  # noqa: ARG001
        manager.open(
            subject="user",
            scopes=tuple(ALL_OAUTH_SCOPES),
            logical_session_id=logical_session_id,
        )
        return True

    process = Process()

    async def fake_spawn(*args):  # noqa: ARG001
        return process

    monkeypatch.setattr(ui, "_authorize_websocket", rotate_during_authorization)
    monkeypatch.setattr(ui, "_spawn_shell_process", fake_spawn)
    ui._ACTIVE_UI_TERMINALS.clear()
    socket = Socket()

    await ui.ui_shell_websocket(socket)

    assert any(code == 4401 and "rotated" in reason for code, reason in socket.closed)
    assert process.writes == []
    assert process.closed is True


@pytest.mark.asyncio
async def test_dashboard_dispatches_workloads_to_selected_remote(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, remote=True, auth="none")
    calls = []

    async def fake_dispatch(machine, local_call, remote_tool, remote_args):  # noqa: ARG001
        calls.append((machine, remote_tool, remote_args))
        if remote_tool == "shell_list":
            return {"sessions": [{"session_id": "remote-shell", "backend": "tmux"}]}
        if remote_tool == "job_list":
            return {
                "jobs": [
                    {
                        "job_id": "remote-job",
                        "session_id": "remote-job-shell",
                        "status": "running",
                    }
                ],
                "counts": {"running": 1},
            }
        raise AssertionError(remote_tool)

    monkeypatch.setattr(ui, "_machine_dispatch", fake_dispatch)
    monkeypatch.setattr(ui, "_machine_rows", lambda: {"machines": []})
    monkeypatch.setattr(ui, "_local_system_snapshot", lambda: {})
    monkeypatch.setattr(
        ui,
        "query_audit",
        lambda **kwargs: {"entries": [], "count": 0, "total_matched": 0},  # noqa: ARG005
    )
    monkeypatch.setattr(ui, "_dashboard_alerts", lambda *args: [])
    monkeypatch.setattr(ui, "_dashboard_activity", lambda entries: [])
    monkeypatch.setattr(ui, "version_info", lambda: {"version": "test"})

    response = await ui.api_dashboard(
        _request("/api/ui/dashboard", query=b"machine=worker")
    )
    payload = json.loads(response.body)["data"]

    assert calls == [
        ("worker", "shell_list", {}),
        ("worker", "job_list", {"include_finished": True}),
    ]
    assert payload["selected_machine"] == "worker"
    assert payload["jobs"][0]["machine"] == "worker"
    assert payload["sessions"][0]["machine"] == "worker"


def test_ui_routes_disabled(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "false")
    get_settings.cache_clear()
    assert ui.ui_routes() == []
