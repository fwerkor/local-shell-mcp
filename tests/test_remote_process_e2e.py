from __future__ import annotations

import asyncio
import os
import platform
import runpy
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest
import uvicorn
from starlette.applications import Starlette

import local_shell_mcp.remote as remote
import local_shell_mcp.tools as tools
from local_shell_mcp.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until(predicate, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except BaseException as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.05)
    raise TimeoutError(f"condition was not met within {timeout}s: {last_error!r}")


def _stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
        try:
            return process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return process.communicate(timeout=5)


def _worker_environment(worker_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join(
                item for item in (str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", "")) if item
            ),
            "LOCAL_SHELL_MCP_WORKER_STATE_DIR": str(worker_root / "identity"),
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(worker_root / "workspace"),
            "LOCAL_SHELL_MCP_STATE_DIR": str(worker_root / "service-state"),
            "LOCAL_SHELL_MCP_AUTH_MODE": "none",
            "LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S": "1",
            "LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S": "20",
            "LOCAL_SHELL_MCP_COMMAND_DENYLIST": "",
            "LOCAL_SHELL_MCP_PATH_DENYLIST": "",
        }
    )
    if env.get("LOCAL_SHELL_MCP_COVERAGE") == "1":
        env["COVERAGE_PROCESS_START"] = str(ROOT / "pyproject.toml")
        env["COVERAGE_FILE"] = str(ROOT / ".coverage")
    return env


def _start_worker(base_url: str, invite: str, worker_root: Path) -> subprocess.Popen[str]:
    workspace = worker_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "local_shell_mcp.remote_worker",
            "--server",
            base_url,
            "--invite",
            invite,
            "--name",
            "process-node",
            "--workdir",
            str(workspace),
        ],
        cwd=ROOT,
        env=_worker_environment(worker_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=(os.name != "nt"),
    )


@pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="one Linux x86_64 real process integration run is sufficient",
)
def test_real_controller_worker_tools_transfers_and_reconnect(tmp_path, monkeypatch):
    controller_root = tmp_path / "controller"
    worker_root = tmp_path / "worker"
    controller_root.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(controller_root))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(controller_root / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S", "1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S", "20")
    get_settings.cache_clear()

    manager = remote.RemoteManager()
    monkeypatch.setattr(remote, "REMOTE_MANAGER", manager)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", base_url)
    get_settings.cache_clear()

    app = Starlette(routes=remote.remote_routes())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    )
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

    def serve() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop_holder["loop"] = loop
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()

    thread = threading.Thread(target=serve, name="remote-e2e-controller", daemon=True)
    thread.start()
    _wait_until(lambda: server.started and "loop" in loop_holder)

    def controller(coroutine, timeout: float = 30):
        return asyncio.run_coroutine_threadsafe(coroutine, loop_holder["loop"]).result(timeout)

    invite = controller(
        manager.create_invite("process-node", str(worker_root / "workspace"), base_url=base_url)
    )
    first = _start_worker(base_url, invite["code"], worker_root)
    second: subprocess.Popen[str] | None = None
    try:
        _wait_until(
            lambda: any(
                row["name"] == "process-node" and row["status"] == "online"
                for row in manager.list_machines()["machines"]
            )
        )
        assert first.poll() is None

        written = controller(
            manager.call(
                "process-node",
                "write_file",
                {"path": "remote.txt", "content": "worker-data\n", "overwrite": True},
                timeout_s=10,
            )
        )
        assert written["ok"] is True
        read = controller(
            manager.call("process-node", "read_file", {"path": "remote.txt"}, timeout_s=10)
        )
        assert read["data"]["content"] == "worker-data\n"
        shell_result = controller(
            manager.call(
                "process-node",
                "run_shell_tool",
                {"command": "printf worker-shell-ok", "cwd": ".", "timeout_s": 5},
                timeout_s=10,
            )
        )
        assert "worker-shell-ok" in shell_result["data"]["stdout"]

        local_file = controller_root / "controller.bin"
        local_file.write_bytes(b"controller-to-worker" * 1024)
        pushed = controller(
            tools._copy_local_file_to_remote(
                "controller.bin", "process-node", "pushed.bin", True, None
            )
        )
        assert pushed["transport"] == "http-stream"
        pulled = controller(
            tools._copy_remote_file_to_local(
                "process-node", "pushed.bin", "roundtrip.bin", True, None
            )
        )
        assert pulled["transport"] == "http-chunks"
        assert (controller_root / "roundtrip.bin").read_bytes() == local_file.read_bytes()

        local_dir = controller_root / "tree"
        (local_dir / "nested").mkdir(parents=True)
        (local_dir / "nested" / "value.txt").write_text("directory-data", encoding="utf-8")
        directory_push = controller(
            tools._copy_local_dir_to_remote(
                "tree", "process-node", "remote-tree", True, 4096
            )
        )
        assert directory_push["entries"] >= 1
        directory_pull = controller(
            tools._copy_remote_dir_to_local(
                "process-node", "remote-tree", "tree-roundtrip", True, 4096
            )
        )
        assert directory_pull["entries"] >= 1
        assert (
            controller_root / "tree-roundtrip" / "nested" / "value.txt"
        ).read_text(encoding="utf-8") == "directory-data"

        identity_path = worker_root / "identity" / remote.REMOTE_WORKER_IDENTITY_FILE_NAME
        _wait_until(identity_path.is_file)
        identity_before = identity_path.read_text(encoding="utf-8")
        first_stdout, first_stderr = _stop_process(first)
        assert first.returncode in {0, -15}
        assert "Status: connected" in first_stdout
        assert "connection failed" not in first_stderr

        second = _start_worker(base_url, invite["code"], worker_root)
        _wait_until(lambda: second.poll() is None and "process-node" in manager.workers)
        time.sleep(1.2)
        assert second.poll() is None, second.stderr.read() if second.stderr else ""
        assert identity_path.read_text(encoding="utf-8") == identity_before

        resumed = controller(
            manager.call(
                "process-node",
                "read_file",
                {"path": "remote.txt"},
                timeout_s=10,
            )
        )
        assert resumed["data"]["content"] == "worker-data\n"
    finally:
        with suppress(Exception):
            if first.poll() is None:
                _stop_process(first)
        if second is not None:
            with suppress(Exception):
                _stop_process(second)
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def test_remote_worker_module_delegates_to_cli(monkeypatch):
    calls = []
    monkeypatch.setattr(remote, "run_worker_cli", calls.append)
    monkeypatch.setattr(sys, "argv", ["remote_worker", "--server", "x"])
    runpy.run_module("local_shell_mcp.remote_worker", run_name="__main__")
    assert calls == [["--server", "x"]]
