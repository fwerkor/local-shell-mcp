from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from edge_case_support import _MemoryStateStore, symlink_or_skip
from edge_case_support import workspace as _transfer_workspace

import local_shell_mcp.remote as remote_module
import local_shell_mcp.tools as mcp_tools
from local_shell_mcp.errors import PathNotFoundError


def test_remote_inline_gui_image_rejects_invalid_payloads() -> None:
    assert mcp_tools._remote_inline_gui_image({}, "shot.png") is None
    with pytest.raises(RuntimeError, match="payload is invalid"):
        mcp_tools._remote_inline_gui_image({"screenshot_inline_b64": 3}, "shot.png")
    with pytest.raises(RuntimeError, match="payload is invalid"):
        mcp_tools._remote_inline_gui_image({"screenshot_inline_b64": "!!!"}, "shot.png")
    with pytest.raises(RuntimeError, match="size does not match"):
        mcp_tools._remote_inline_gui_image(
            {"screenshot_inline_b64": "aGVsbG8=", "screenshot_inline_size": 99},
            "shot.png",
        )

@pytest.mark.asyncio
async def test_remote_call_disabled_and_failure_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    disabled = SimpleNamespace(remote_enabled=False)
    result = await mcp_tools._remote_call(disabled, "node", "file_read", {})
    assert result.isError is True

    class Manager:
        def __init__(self, result):
            self.result = result
            self.calls = []

        async def call(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self.result

    settings = SimpleNamespace(
        remote_enabled=True,
        remote_peer_transfer_timeout_s=77,
        remote_job_timeout_s=222,
    )
    manager = Manager({"ok": False, "message": "bad", "data": "oops"})
    monkeypatch.setattr(mcp_tools, "remote_manager", lambda: manager)
    failure = await mcp_tools._remote_call(settings, "node", "transfer_stat", {})
    assert failure.isError is True
    assert manager.calls[-1][1]["rpc_timeout_s"] == 77.0

    manager.result = {"ok": True, "data": {"status": "not_found", "message": "gone"}}
    missing = await mcp_tools._remote_call(settings, "node", "file_read", {})
    assert missing.isError is True

    manager.result = {"ok": True, "data": {"value": 1}}
    ok = await mcp_tools._remote_call(settings, "node", "browser_snapshot", {}, timeout_s=9)
    assert ok["data"] == {"value": 1}
    assert manager.calls[-1][1]["rpc_timeout_s"] == 9.0

def test_remote_handled_exception_shapes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        remote_module,
        "missing_path_context",
        lambda path: {"path": str(path), "cwd": str(tmp_path)},
    )
    missing = remote_module._handled_remote_exception(PathNotFoundError("missing.txt"))
    assert missing["data"]["status"] == "not_found"
    generic = remote_module._handled_remote_exception(ValueError())
    assert generic["message"] == "ValueError"

def test_remote_worker_gui_temp_path_and_stat_edges(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    root = remote_module.temp_dir()
    valid = root / ("gui-" + "a" * 32 + ".png")
    valid.write_bytes(b"payload")
    stat = remote_module._worker_gui_temp_stat(str(valid), sha256=True)
    assert stat["size"] == 7
    assert len(stat["sha256"]) == 64

    invalid = root / "bad.png"
    with pytest.raises(ValueError, match="invalid filename"):
        remote_module._worker_gui_temp_path(str(invalid), must_exist=False)

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    escaped = root / ("gui-" + "b" * 32 + ".png")
    symlink_or_skip(escaped, outside)
    with pytest.raises(ValueError, match="escapes"):
        remote_module._worker_gui_temp_path(str(escaped), must_exist=True)

def test_remote_gui_relay_optimizer_invalid_large_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    root = remote_module.temp_dir()
    path = root / ("gui-" + "c" * 32 + ".png")
    path.write_bytes(b"x" * (128 * 1024))
    assert remote_module._optimize_gui_temp_for_relay(str(path)) == {
        "optimized": False,
        "bytes": 128 * 1024,
        "format": "original",
    }
    assert remote_module._optimize_gui_temp_for_relay(str(root / "missing.png")) == {
        "optimized": False,
        "bytes": 0,
        "format": "original",
    }

@pytest.mark.asyncio
async def test_remote_transfer_dispatch_remaining_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        remote_module,
        "transfer_refresh_stream_write",
        lambda path, transfer_id: calls.append(("refresh", (path, transfer_id))),
    )
    monkeypatch.setattr(
        remote_module,
        "open_peer_receiver",
        lambda **kwargs: {"receiver": kwargs},
    )
    monkeypatch.setattr(
        remote_module, "close_peer_receiver", lambda receiver_id: {"closed": receiver_id}
    )

    async def put(*args, **kwargs):
        calls.append(("put", args))
        return {"put": True}

    async def get(*args, **kwargs):
        calls.append(("get", args))
        return {"get": True}

    monkeypatch.setattr(remote_module, "_worker_put_url_cancellable", put)
    monkeypatch.setattr(remote_module, "_worker_download_url_cancellable", get)

    assert await remote_module._execute_transfer_worker_tool(
        "transfer_refresh_stream_write", {"path": "p", "transfer_id": "t"}
    ) == {"refreshed": True}
    opened = await remote_module._execute_transfer_worker_tool(
        "transfer_open_receiver",
        {"path": "p", "expected_bytes": 1, "expected_sha256": "x"},
    )
    assert opened["receiver"]["bind_host"] == "0.0.0.0"
    assert await remote_module._execute_transfer_worker_tool(
        "transfer_close_receiver", {"receiver_id": "r"}
    ) == {"closed": "r"}
    assert (
        await remote_module._execute_transfer_worker_tool(
            "transfer_put_url",
            {"path": "p", "url": "https://x", "expected_bytes": 1},
        )
    ) == {"put": True}
    assert (
        await remote_module._execute_transfer_worker_tool(
            "transfer_get_url",
            {
                "path": "p",
                "url": "https://x",
                "expected_bytes": 1,
                "expected_sha256": "x",
            },
        )
    ) == {"get": True}
    with pytest.raises(ValueError, match="unsupported"):
        await remote_module._execute_transfer_worker_tool("unknown", {})

def test_remote_registry_load_recovers_backup_and_sanitizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = b"good-generation"
    backup = {
        "version": 1,
        "generation": generation.decode(),
        "workers": [
            {
                "name": "node",
                "access": "token",
                "last_seen": "bad",
                "created_at": 1,
                "reset_generation": "bad",
            },
            {"name": "", "access": "ignored"},
        ],
        "invites": [
            {"code": "", "expires_at": 99999999999},
            {"code": "invite", "expires_at": 99999999999, "used": False},
        ],
    }
    store = _MemoryStateStore(
        {
            remote_module.REMOTE_WORKER_REGISTRY_FILE_NAME: b"not-json",
            remote_module.REMOTE_WORKER_REGISTRY_BACKUP_FILE_NAME: __import__("json")
            .dumps(backup)
            .encode(),
            remote_module.REMOTE_WORKER_REGISTRY_GENERATION_FILE_NAME: generation,
        }
    )
    monkeypatch.setattr(remote_module, "get_state_store", lambda: store)
    monkeypatch.setattr(remote_module, "audit", lambda *args, **kwargs: None)
    manager = remote_module.RemoteManager()
    manager._load_registry_unlocked()
    assert set(manager.workers) == {"node"}
    assert manager.workers["node"].last_seen == 0.0
    assert manager.workers["node"].reset_generation == 0
    assert set(manager.invites) == {"invite"}
    assert manager._registry_loaded is True

def test_remote_small_validation_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported remote worker lane"):
        remote_module._worker_job_lane("tool", "bad")
    assert (
        remote_module._worker_job_lane("transfer_stat") == remote_module.REMOTE_WORKER_TRANSFER_LANE
    )
    assert (
        remote_module._worker_job_lane("file_read") == remote_module.REMOTE_WORKER_INTERACTIVE_LANE
    )

    invalid_registry = {
        "version": 1,
        "generation": "",
        "workers": [],
        "invites": [],
    }
    with pytest.raises(ValueError, match="generation is invalid"):
        remote_module.RemoteManager._read_registry(
            __import__("json").dumps(invalid_registry).encode()
        )

    assert remote_module._worker_reset_generation({"reset_generation": "bad"}) is None

    _transfer_workspace(tmp_path, monkeypatch)
    root = remote_module.temp_dir()
    directory = root / ("gui-" + "d" * 32 + ".png")
    directory.mkdir()
    with pytest.raises(IsADirectoryError):
        remote_module._worker_gui_temp_stat(str(directory))
