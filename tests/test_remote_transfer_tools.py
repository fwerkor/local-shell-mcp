from __future__ import annotations

from typing import Any

import pytest

import local_shell_mcp.tools as tools
from local_shell_mcp.fs_ops import delete_path
from local_shell_mcp.settings import get_settings
from local_shell_mcp.transfer_ops import (
    transfer_abort_write,
    transfer_alloc_temp_path,
    transfer_begin_write,
    transfer_finish_write,
    transfer_pack_dir,
    transfer_read_chunk,
    transfer_stat,
    transfer_unpack_archive,
    transfer_write_chunk,
)


class FakeRemoteManager:
    async def call(self, machine: str, tool: str, args: dict[str, Any], timeout_s: int | None = None) -> dict[str, Any]:
        try:
            if tool == "transfer_stat":
                data = transfer_stat(args["path"], args.get("sha256", True))
            elif tool == "transfer_read_chunk":
                data = transfer_read_chunk(args["path"], args.get("offset", 0), args.get("chunk_size"))
            elif tool == "transfer_begin_write":
                data = transfer_begin_write(args["path"], args.get("overwrite", True), args.get("expected_bytes"))
            elif tool == "transfer_write_chunk":
                data = transfer_write_chunk(
                    args["path"],
                    args["transfer_id"],
                    args["offset"],
                    args["data_b64"],
                    args.get("expected_sha256"),
                )
            elif tool == "transfer_finish_write":
                data = transfer_finish_write(
                    args["path"],
                    args["transfer_id"],
                    args.get("expected_bytes"),
                    args.get("expected_sha256"),
                )
            elif tool == "transfer_abort_write":
                data = transfer_abort_write(args["path"], args["transfer_id"])
            elif tool == "transfer_alloc_temp_path":
                data = transfer_alloc_temp_path(args.get("suffix", ".bin"))
            elif tool == "transfer_pack_dir":
                data = transfer_pack_dir(args["path"], args.get("compression", "gz"))
            elif tool == "transfer_unpack_archive":
                data = transfer_unpack_archive(
                    args["archive_path"],
                    args["dst_path"],
                    args.get("overwrite", True),
                    args.get("cleanup_archive", True),
                )
            elif tool == "delete_file_or_dir":
                data = delete_path(args["path"], args.get("recursive", False))
            else:
                raise ValueError(f"unsupported fake remote tool: {tool}")
            return {"ok": True, "message": "", "data": data}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    monkeypatch.setattr(tools, "remote_manager", lambda: FakeRemoteManager())
    return tmp_path


@pytest.mark.asyncio
async def test_remote_copy_file_streams_between_workers(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src-machine").mkdir()
    (root / "dst-machine").mkdir()
    data = b"abcdef" * 1000
    (root / "src-machine" / "payload.bin").write_bytes(data)

    result = await tools._copy_remote_file_to_remote(
        "src", "src-machine/payload.bin", "dst", "dst-machine/payload.bin", True, 128
    )

    assert result["chunks"] > 1
    assert result["bytes"] == len(data)
    assert (root / "dst-machine" / "payload.bin").read_bytes() == data


@pytest.mark.asyncio
async def test_remote_copy_dir_packs_transfers_and_unpacks(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src-machine" / "run" / "nested").mkdir(parents=True)
    (root / "dst-machine").mkdir()
    (root / "src-machine" / "run" / "nested" / "result.txt").write_text("ok", encoding="utf-8")

    result = await tools._copy_remote_dir_to_remote(
        "src", "src-machine/run", "dst", "dst-machine/run-copy", True, 256
    )

    assert result["entries"] >= 1
    assert (root / "dst-machine" / "run-copy" / "nested" / "result.txt").read_text(encoding="utf-8") == "ok"
