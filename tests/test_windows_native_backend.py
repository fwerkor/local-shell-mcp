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
