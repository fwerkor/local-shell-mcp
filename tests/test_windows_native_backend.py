import asyncio

import pytest

import local_shell_mcp.shell_ops as ops
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_native_persistent_shell_backend_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    old_backend = ops._use_native_persistent_shell_backend
    ops._use_native_persistent_shell_backend = lambda: True
    monkeypatch.setattr(ops.conpty_ops, "is_available", lambda: False)
    session = await ops.start_shell(name="native-roundtrip")
    try:
        await ops.send_shell(session["session_id"], "echo native-ok")
        data = {"output": ""}
        for _ in range(40):
            data = await ops.read_shell(session["session_id"], lines=20)
            if "native-ok" in data["output"]:
                break
            await asyncio.sleep(0.05)
        assert "native-ok" in data["output"]
        assert session["backend"] == "native"
        listed = await ops.list_shells()
        assert any(item["session_id"] == session["session_id"] for item in listed["sessions"])
    finally:
        await ops.kill_shell(session["session_id"])
        ops._use_native_persistent_shell_backend = old_backend


@pytest.mark.asyncio
async def test_native_send_uses_windows_line_ending(monkeypatch):
    class FakeStdin:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            return None

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.returncode = None

    process = FakeProcess()
    session = ops.NativeShellSession(
        session_id="native-newline",
        process=process,
        cwd=None,
        command="powershell",
        created=0,
        output=ops.TailBuffer(1024, bytearray()),
        readers=[],
        lock=asyncio.Lock(),
    )
    monkeypatch.setattr(ops.sys, "platform", "win32")
    ops._NATIVE_SHELL_SESSIONS[session.session_id] = session
    try:
        await ops._native_send_shell(session.session_id, "echo native-ok")
    finally:
        ops._NATIVE_SHELL_SESSIONS.pop(session.session_id, None)

    assert bytes(process.stdin.data) == b"echo native-ok\r\n"


@pytest.mark.asyncio
async def test_native_shell_creation_is_serialized(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(ops, "_use_native_persistent_shell_backend", lambda: True)
    monkeypatch.setattr(ops.conpty_ops, "is_available", lambda: False)
    ops._NATIVE_SHELL_SESSIONS.clear()
    spawned = []

    class FakeProcess:
        def __init__(self):
            self.pid = len(spawned) + 1
            self.returncode = None
            self.stdout = None
            self.stdin = None

    async def fake_create_subprocess_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        await asyncio.sleep(0)
        process = FakeProcess()
        spawned.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    outcomes = await asyncio.gather(
        ops.start_shell(name="duplicate", command="echo one"),
        ops.start_shell(name="duplicate", command="echo two"),
        return_exceptions=True,
    )

    assert len(spawned) == 1
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, RuntimeError) for item in outcomes) == 1
    assert list(ops._NATIVE_SHELL_SESSIONS) == ["duplicate"]

    spawned[0].returncode = 0
    await ops.kill_shell("duplicate")
