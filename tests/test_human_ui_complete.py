from __future__ import annotations

import asyncio
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
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch, *, remote: bool = False, auth: str = "none"):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", str(remote).lower())
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_WALLPAPER", "none")
    get_settings.cache_clear()


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
        self.calls: list[tuple[str, str, dict, int | None]] = []
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

    async def call(self, machine, tool, args, timeout_s=None):
        self.calls.append((machine, tool, args, timeout_s))
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
    assert set(ui._audit_detail_scopes({"operation": "other", "node": "worker"})) == set(
        ui.UI_FULL_SCOPES
    )


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


def test_remote_file_terminal_todo_audit_and_admin_routes(tmp_path, monkeypatch):
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
        ("kill", {"session_id": "s"}),
    ):
        assert client.post(
            f"/api/ui/terminals/{action}", json={"machine": "win-node", **body}
        ).status_code == 200
    assert client.post(
        "/api/ui/terminals/send", json={"machine": "win-node"}
    ).status_code == 400
    assert client.post(
        "/api/ui/terminals/kill", json={"machine": "win-node"}
    ).status_code == 400
    assert client.post(
        "/api/ui/terminals/unknown", json={"machine": "win-node"}
    ).status_code == 400

    monkeypatch.setattr(ui, "todo_read", lambda: (_ for _ in ()).throw(RuntimeError("todo")))
    assert client.get("/api/ui/todos").status_code == 400
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
    ui._spawn_tui_process(80, 24)
    assert captured["env"]["LOCAL_SHELL_MCP_UI_MODE"] == "web"
    assert captured["env"]["TERM"] == "xterm-256color"
    assert captured["env"]["COLORTERM"] == "truecolor"
    assert captured["env"]["TERM_PROGRAM"] == "vscode"
    assert captured["env"]["TERM_PROGRAM_VERSION"] == "local-shell-mcp"

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
        def __init__(self, reads=None):
            self.reads = list(reads or [b""])
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

    process = Process([b"hello"])
    monkeypatch.setattr(ui, "_spawn_tui_process", lambda *args: process)
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
    socket = Socket(messages)
    asyncio.run(ui.ui_terminal_websocket(socket))
    assert socket.accepted == "lsm-ui"
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


def test_ui_routes_disabled(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "false")
    get_settings.cache_clear()
    assert ui.ui_routes() == []
