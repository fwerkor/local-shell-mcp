import asyncio
from types import SimpleNamespace

import pytest

import local_shell_mcp.conpty_ops as conpty_ops
import local_shell_mcp.shell_ops as ops
from local_shell_mcp.errors import ShellExecutableNotFoundError
from local_shell_mcp.settings import get_settings


class FakePtyProcess:
    spawned = []

    def __init__(self, argv, cwd, env):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.alive = True
        self.output = [b"ready\r\n"]
        self.writes = []
        self.close_calls = []
        self.sizes = []
        FakePtyProcess.spawned.append(self)

    @classmethod
    def spawn(cls, argv, cwd=None, env=None):
        return cls(argv, cwd, env)

    def isalive(self):
        return self.alive

    def read(self, size=None):  # noqa: ARG002
        if self.output:
            return self.output.pop(0)
        return b""

    def write(self, data):
        self.writes.append(data)
        self.output.append(f"wrote:{data}\r\n".encode())

    def setwinsize(self, rows, cols):
        self.sizes.append((rows, cols))

    def terminate(self, force=False):  # noqa: ARG002
        self.alive = False

    def close(self, force=False):
        self.close_calls.append(force)
        self.alive = False


@pytest.fixture(autouse=True)
async def clear_conpty_sessions():
    conpty_ops._CONPTY_SHELL_SESSIONS.clear()
    FakePtyProcess.spawned.clear()
    yield
    for session_id in list(conpty_ops._CONPTY_SHELL_SESSIONS):
        await conpty_ops.kill_shell(session_id)
    conpty_ops._CONPTY_SHELL_SESSIONS.clear()
    FakePtyProcess.spawned.clear()


@pytest.mark.asyncio
async def test_windows_prefers_conpty_and_supports_session_ops(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(ops, "_use_native_persistent_shell_backend", lambda: True)
    monkeypatch.setattr(conpty_ops, "winpty", SimpleNamespace(PtyProcess=FakePtyProcess))

    async def fail_native_start(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("native backend should not be used when pywinpty is available")

    monkeypatch.setattr(ops, "_native_start_shell", fail_native_start)

    session = await ops.start_shell(name="conpty-test")

    assert session["backend"] == "conpty"
    assert FakePtyProcess.spawned

    resized = await ops.resize_shell(session["session_id"], 132, 38)
    await ops.send_shell(session["session_id"], "echo ok")
    data = {"output": ""}
    for _ in range(20):
        data = await ops.read_shell(session["session_id"], lines=10)
        if "wrote:echo ok" in data["output"]:
            break
        await asyncio.sleep(0.02)

    assert "wrote:echo ok" in data["output"]
    assert resized == {
        "session_id": session["session_id"],
        "cols": 132,
        "rows": 38,
        "resized": True,
        "backend": "conpty",
    }
    assert FakePtyProcess.spawned[0].sizes == [(38, 132)]
    assert FakePtyProcess.spawned[0].writes == ["echo ok\r"]

    listed = await ops.list_shells()
    assert listed["sessions"] == [
        {
            "session_id": session["session_id"],
            "created": listed["sessions"][0]["created"],
            "attached": "0",
            "backend": "conpty",
        }
    ]

    killed = await ops.kill_shell(session["session_id"])
    assert killed == {"session_id": session["session_id"], "killed": True, "stderr": ""}
    assert FakePtyProcess.spawned[0].close_calls == [True]
    assert await ops.list_shells() == {"sessions": []}


@pytest.mark.asyncio
async def test_conpty_resize_reports_unsupported_process(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(conpty_ops, "winpty", SimpleNamespace(PtyProcess=FakePtyProcess))

    session = await conpty_ops.start_shell(name="no-resize")
    process = FakePtyProcess.spawned[0]
    process.setwinsize = None

    assert await conpty_ops.resize_shell(session["session_id"], 120, 35) == {
        "session_id": session["session_id"],
        "cols": 120,
        "rows": 35,
        "resized": False,
        "backend": "conpty",
    }


@pytest.mark.asyncio
async def test_windows_falls_back_to_native_when_pywinpty_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(ops, "_use_native_persistent_shell_backend", lambda: True)
    monkeypatch.setattr(conpty_ops, "winpty", None)

    async def fake_native_start(cwd=".", name=None, command=None):
        return {"session_id": name, "cwd": cwd, "command": command or "shell", "backend": "native"}

    monkeypatch.setattr(ops, "_native_start_shell", fake_native_start)

    session = await ops.start_shell(cwd=".", name="native-fallback")

    assert session["session_id"] == "native-fallback"
    assert session["backend"] == "native"


@pytest.mark.asyncio
async def test_conpty_reports_missing_shell_executable(tmp_path, monkeypatch):
    executable = "missing-conpty-shell"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
    get_settings.cache_clear()
    monkeypatch.setattr(ops, "_use_native_persistent_shell_backend", lambda: True)

    class MissingPtyProcess:
        @classmethod
        def spawn(cls, argv, cwd=None, env=None):  # noqa: ARG003
            raise FileNotFoundError(2, "The system cannot find the file specified", executable)

    monkeypatch.setattr(conpty_ops, "winpty", SimpleNamespace(PtyProcess=MissingPtyProcess))

    with pytest.raises(ShellExecutableNotFoundError) as raised:
        await ops.start_shell(cwd=".", name="missing-conpty")

    assert raised.value.executable == executable
    assert raised.value.command == executable
    assert raised.value.cwd == str(tmp_path)


@pytest.mark.asyncio
async def test_conpty_list_closes_naturally_exited_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(conpty_ops, "winpty", SimpleNamespace(PtyProcess=FakePtyProcess))

    session = await conpty_ops.start_shell(name="natural-exit")
    process = FakePtyProcess.spawned[0]
    process.alive = False

    assert await conpty_ops.list_shells() == {"sessions": []}
    assert session["session_id"] not in conpty_ops._CONPTY_SHELL_SESSIONS
    assert process.close_calls == [False]


@pytest.mark.asyncio
async def test_conpty_cleanup_tolerates_reader_from_closed_event_loop():
    class ClosedLoop:
        def is_closed(self):
            return True

    class StaleReader:
        _log_destroy_pending = True

        def get_loop(self):
            return ClosedLoop()

        def done(self):
            return False

    reader = StaleReader()

    await conpty_ops._cleanup_reader(reader)

    assert reader._log_destroy_pending is False
