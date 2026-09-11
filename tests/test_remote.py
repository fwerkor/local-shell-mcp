

import asyncio
import subprocess
import sys
import threading
import urllib.error
from io import BytesIO
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote
from local_shell_mcp.remote import join_script
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_remote_invites_use_requested_origin_prune_expired_entries_and_validate_names(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.delenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", raising=False)
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    manager.invites["expired"] = remote.RemoteInvite(
        code="expired",
        name=None,
        workdir=None,
        expires_at=0,
    )

    result = await manager.create_invite(
        "worker-a",
        "/workspace",
        120,
        base_url="https://control.example.test",
    )

    assert result["join_url"] == "https://control.example.test/join"
    assert "https://control.example.test/join" in result["command"]
    assert result["persistent_command"] == result["command"] + ' --persist && export PATH="${LOCAL_SHELL_MCP_WORKER_BIN_DIR:-$HOME/.local/bin}:$PATH"'
    assert result["powershell_join_url"] == "https://control.example.test/join.ps1"
    assert "https://control.example.test/join.ps1" in result["powershell_command"]
    assert result["powershell_persistent_command"].endswith(" -Persist")
    assert "expired" not in manager.invites
    with pytest.raises(ValueError, match="unsupported characters"):
        await manager.create_invite("bad/name")
    with pytest.raises(ValueError, match="128 characters"):
        await manager.create_invite("x" * 129)



@pytest.mark.asyncio
async def test_timed_out_remote_job_is_skipped_on_next_poll(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(name="worker-a", token="token-a")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    with pytest.raises(TimeoutError, match="remote job timed out"):
        await manager.call("worker-a", "list_files", {"path": "."}, timeout_s=0.01)

    cancelled_job = await worker.queue.get()
    worker.queue.put_nowait(cancelled_job)
    worker.queue.put_nowait({"id": "job-valid", "tool": "list_files", "args": {}})
    result = await manager.poll(worker.token)

    assert result["job"]["id"] == "job-valid"
    assert cancelled_job["id"] not in manager.cancelled_jobs
    assert cancelled_job["id"] not in manager.pending


@pytest.mark.asyncio
async def test_poll_requires_upgrade_before_dequeuing_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(name="worker-a", token="token-a")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    worker.queue.put_nowait({"id": "job-valid", "tool": "list_files", "args": {}})

    mismatch = await manager.poll(
        worker.token,
        {
            "protocol_version": 1,
            "worker_version": "0.0.0",
        },
    )

    assert mismatch == {
        "job": None,
        "upgrade": {"required": True, "version": remote.__version__},
        "poll_timeout_s": 25.0,
    }
    assert worker.queue.qsize() == 1
    assert worker.info["lsm_version"] == "0.0.0"
    assert worker.info["poll_protocol_version"] == 1

    matched = await manager.poll(
        worker.token,
        {
            "protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
            "worker_version": remote.__version__,
        },
    )
    assert matched["job"]["id"] == "job-valid"
    assert matched["upgrade"] == {"required": False, "version": remote.__version__}
    assert matched["poll_timeout_s"] == 25.0


@pytest.mark.asyncio
async def test_poll_clamps_to_worker_timeout_and_returns_current_controller_value(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S", "50")
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(name="worker-a", token="token-a")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    captured = []

    async def fake_poll_wait(queue, timeout_s):  # noqa: ANN001
        assert queue is worker.queue
        captured.append(timeout_s)
        raise TimeoutError

    monkeypatch.setattr(remote, "_wait_for_remote_poll_item", fake_poll_wait)

    result = await manager.poll(worker.token, {"poll_timeout_s": 10})

    assert captured == [pytest.approx(10)]
    assert result["poll_timeout_s"] == 50.0


@pytest.mark.asyncio
async def test_shutdown_interrupt_wakes_waiting_remote_poll(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S", "50")
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(name="worker-a", token="token-a")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    remote._prepare_remote_polls_for_server_start()  # noqa: SLF001
    try:
        poll = asyncio.create_task(manager.poll(worker.token))
        for _ in range(10):
            if remote._REMOTE_POLL_SHUTDOWN_WAITERS:  # noqa: SLF001
                break
            await asyncio.sleep(0)

        assert len(remote._REMOTE_POLL_SHUTDOWN_WAITERS) == 1  # noqa: SLF001
        assert remote._interrupt_remote_polls_for_shutdown() == 1  # noqa: SLF001
        with pytest.raises(remote.RemoteControllerShuttingDown, match="shutting down"):
            await poll
        assert not remote._REMOTE_POLL_SHUTDOWN_WAITERS  # noqa: SLF001

        with pytest.raises(remote.RemoteControllerShuttingDown, match="shutting down"):
            await manager.poll(worker.token)
    finally:
        remote._prepare_remote_polls_for_server_start()  # noqa: SLF001


@pytest.mark.asyncio
async def test_remote_queue_is_bounded_per_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS", "1")
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(name="worker-a", token="token-a")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    worker.queue.put_nowait({"id": "already-queued"})

    with pytest.raises(RuntimeError, match="queue is full"):
        await manager.call("worker-a", "list_files", {"path": "."}, timeout_s=1)


@pytest.mark.asyncio
async def test_lane_aware_worker_routes_transfer_jobs_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(
        name="worker-a",
        token="token-a",
        info={"poll_protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION},
    )
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    transfer_call = asyncio.create_task(
        manager.call("worker-a", "transfer_stat", {"path": "."}, timeout_s=2)
    )
    interactive_call = asyncio.create_task(
        manager.call("worker-a", "list_files", {"path": "."}, timeout_s=2)
    )
    await asyncio.sleep(0)

    interactive = await manager.poll(
        worker.token,
        {
            "protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
            "worker_version": remote.__version__,
            "lane": remote.REMOTE_WORKER_INTERACTIVE_LANE,
        },
    )
    transfer = await manager.poll(
        worker.token,
        {
            "protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
            "worker_version": remote.__version__,
            "lane": remote.REMOTE_WORKER_TRANSFER_LANE,
        },
    )

    assert interactive["job"]["tool"] == "list_files"
    assert transfer["job"]["tool"] == "transfer_stat"
    await manager.submit_result(
        worker.token,
        {"job_id": interactive["job"]["id"], "ok": True, "data": []},
    )
    await manager.submit_result(
        worker.token,
        {"job_id": transfer["job"]["id"], "ok": True, "data": {"type": "directory"}},
    )
    await interactive_call
    await transfer_call


@pytest.mark.asyncio
async def test_invalid_worker_poll_protocol_uses_legacy_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(
        name="worker-a",
        token="token-a",
        info={"poll_protocol_version": "future"},
    )
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    call = asyncio.create_task(
        manager.call("worker-a", "transfer_stat", {"path": "."}, timeout_s=2)
    )
    await asyncio.sleep(0)

    assert worker.queue.qsize() == 1
    assert worker.transfer_queue.qsize() == 0
    polled = await manager.poll(
        worker.token,
        {"protocol_version": 1, "worker_version": remote.__version__},
    )
    await manager.submit_result(
        worker.token,
        {"job_id": polled["job"]["id"], "ok": True, "data": {"type": "directory"}},
    )
    await call


@pytest.mark.asyncio
async def test_lane_upgrade_migrates_queued_transfer_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(
        name="worker-a",
        token="token-a",
        info={"poll_protocol_version": 1},
    )
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    call = asyncio.create_task(
        manager.call("worker-a", "transfer_stat", {"path": "."}, timeout_s=2)
    )
    await asyncio.sleep(0)
    assert worker.queue.qsize() == 1
    assert worker.transfer_queue.qsize() == 0

    polled = await manager.poll(
        worker.token,
        {
            "protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
            "worker_version": remote.__version__,
            "lane": remote.REMOTE_WORKER_TRANSFER_LANE,
        },
    )

    assert polled["job"]["tool"] == "transfer_stat"
    assert worker.queue.qsize() == 0
    await manager.submit_result(
        worker.token,
        {"job_id": polled["job"]["id"], "ok": True, "data": {"type": "directory"}},
    )
    await call

@pytest.mark.asyncio
async def test_join_script_loads_vendored_worker_dependencies(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.test")
    get_settings.cache_clear()

    response = await join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")

    assert 'export PYTHONPATH="$RUNTIME_ROOT:$RUNTIME_ROOT/vendor:${PYTHONPATH:-}"' in script
    assert 'RUNTIME_ROOT="$STATE_HOME/runtime"' in script
    assert 'mv "$RUNTIME_NEXT" "$RUNTIME_ROOT"' in script


@pytest.mark.asyncio
async def test_join_script_reports_download_progress_and_uses_worker_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.test")
    get_settings.cache_clear()

    response = await join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")

    assert "Downloading worker bundle" in script
    assert "--progress-bar" in script
    assert "python3 -m local_shell_mcp.remote_worker" in script
    assert "python3 -m local_shell_mcp.main worker" not in script


def test_worker_post_json_uses_curl_and_parses_success(monkeypatch):
    calls = []

    def fake_run(command, *, input, capture_output, check, creationflags):  # noqa: A002
        calls.append((command, input, check, creationflags))
        assert capture_output is True
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b'{"ok": true, "data": {"registered": true}}\nLOCAL_SHELL_MCP_HTTP_STATUS:200',
            stderr=b"",
        )

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    monkeypatch.setattr(remote.subprocess, "run", fake_run)

    result = remote._worker_post_json(  # noqa: SLF001
        "https://example.test/remote/register",
        {"invite": "abc"},
        {"Authorization": "Bearer token"},
        30,
    )

    assert result == {"ok": True, "data": {"registered": True}}
    command, body, check, creationflags = calls[0]
    assert command[:7] == [
        "/usr/bin/curl",
        "--connect-timeout",
        "10",
        "--max-time",
        "30",
        "-sS",
        "-L",
    ]
    assert ["-H", "Authorization: Bearer token"] in [command[index : index + 2] for index in range(len(command) - 1)]
    assert command[-1] == "https://example.test/remote/register"
    assert body == b'{"invite": "abc"}'
    assert check is False
    assert creationflags == remote._worker_subprocess_creationflags()  # noqa: SLF001


@pytest.mark.asyncio
async def test_worker_result_cancellation_terminates_active_curl(monkeypatch):
    started = threading.Event()
    killed = threading.Event()

    class FakePopen:
        def __init__(self, command, *, stdin, stdout, stderr, creationflags):  # noqa: ANN001
            assert command[0] == "/usr/bin/curl"
            assert stdin is subprocess.PIPE
            assert stdout is subprocess.PIPE
            assert stderr is subprocess.PIPE
            assert creationflags == remote._worker_subprocess_creationflags()  # noqa: SLF001
            self.returncode = None

        def communicate(self, input):  # noqa: A002, ANN001
            assert input == b'{"job_id": "job-1"}'
            started.set()
            killed.wait(1)
            self.returncode = -9
            return b"", b"terminated"

        def kill(self):
            killed.set()

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    monkeypatch.setattr(remote.subprocess, "Popen", FakePopen)

    submission = asyncio.create_task(
        remote._worker_post_json_forever(  # noqa: SLF001
            "https://example.test/remote/result",
            {"job_id": "job-1"},
            {"Authorization": "Bearer token"},
            30,
            "submit result",
        )
    )
    assert await asyncio.to_thread(started.wait, 1)

    submission.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(submission, timeout=1)

    assert killed.is_set()


def test_worker_post_json_curl_reports_non_2xx_body(monkeypatch):
    def fake_run(  # noqa: A002, ARG001
        command, *, input, capture_output, check, creationflags
    ):
        assert creationflags == remote._worker_subprocess_creationflags()  # noqa: SLF001
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"<html>Cloudflare 1010</html>\nLOCAL_SHELL_MCP_HTTP_STATUS:403",
            stderr=b"",
        )

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    monkeypatch.setattr(remote.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="failed with 403: <html>Cloudflare 1010</html>"):
        remote._worker_post_json("https://example.test/remote/register", {"invite": "abc"})  # noqa: SLF001


def test_worker_curl_subprocess_hides_windows_console(monkeypatch):
    monkeypatch.setattr(remote, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(remote.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert remote._worker_subprocess_creationflags() == 0x08000000  # noqa: SLF001


def test_worker_post_json_falls_back_to_urllib_when_curl_unavailable(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self):
            return b'{"ok": true, "data": {"heartbeat": true}}'

    captured = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    monkeypatch.setattr(remote.urllib.request, "urlopen", fake_urlopen)

    result = remote._worker_post_json(  # noqa: SLF001
        "https://example.test/remote/heartbeat",
        {},
        {"Authorization": "Bearer token"},
        12,
    )

    assert result == {"ok": True, "data": {"heartbeat": True}}
    assert captured["timeout"] == 12
    assert captured["request"].headers["Authorization"] == "Bearer token"
    assert captured["request"].data == b"{}"


def test_worker_post_json_requires_curl_for_bounded_poll(monkeypatch):
    monkeypatch.setattr(remote.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="curl is required"):
        remote._worker_post_json(  # noqa: SLF001
            "https://example.test/remote/poll",
            {},
            {"Authorization": "Bearer token"},
            35,
        )


def test_worker_post_json_urllib_reports_non_2xx_body(monkeypatch):
    def fake_urlopen(request, timeout=None):  # noqa: ANN001, ARG001
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs={},
            fp=BytesIO(b"<html>Cloudflare 1010</html>"),
        )

    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    monkeypatch.setattr(remote.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="failed with 403: <html>Cloudflare 1010</html>"):
        remote._worker_post_json("https://example.test/remote/result", {"job_id": "job_1"})  # noqa: SLF001


def test_worker_poll_request_timeout_uses_only_advertised_values():
    assert remote._worker_poll_request_timeout_s({"poll_timeout_s": 25}) == 35  # noqa: SLF001
    assert remote._worker_poll_request_timeout_s({"poll_timeout_s": 4.5}) == 14.5  # noqa: SLF001
    assert remote._worker_poll_request_timeout_s({}) is None  # noqa: SLF001
    for value in (None, 0, -1, "invalid", float("nan")):
        assert remote._worker_poll_request_timeout_s({"poll_timeout_s": value}) is None  # noqa: SLF001


def test_worker_poll_payload_advertises_current_long_poll_budget():
    assert remote._worker_poll_payload() == {  # noqa: SLF001
        "protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
        "worker_version": remote.__version__,
    }
    assert remote._worker_poll_payload(27)["poll_timeout_s"] == 17  # noqa: SLF001


def test_worker_retry_delay_is_capped():
    assert [remote._worker_retry_delay(i) for i in range(7)] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]  # noqa: SLF001


def test_reexec_updated_worker_runtime_prefers_installed_bundle(tmp_path, monkeypatch):
    from local_shell_mcp import remote_worker_cli, remote_worker_service

    state_dir = tmp_path / "state"
    runtime = state_dir / "runtime"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(state_dir))
    monkeypatch.setenv("PYTHONPATH", remote.os.pathsep.join(("/old/runtime", "/other")))
    monkeypatch.setattr(
        remote_worker_cli,
        "_worker_run_exec_argv",
        lambda: [sys.executable, "-m", "local_shell_mcp.main", "worker", "run"],
    )
    monkeypatch.setattr(remote_worker_service, "_current_worker_is_managed", lambda: False)
    calls = []
    monkeypatch.setattr(remote.os, "execv", lambda executable, argv: calls.append((executable, argv)))

    remote._reexec_updated_worker_runtime()  # noqa: SLF001

    pythonpath = remote.os.environ["PYTHONPATH"].split(remote.os.pathsep)
    assert pythonpath[:2] == [str(runtime), str(runtime / "vendor")]
    assert pythonpath[2:] == ["/old/runtime", "/other"]
    assert calls == [
        (
            sys.executable,
            [sys.executable, "-m", "local_shell_mcp.main", "worker", "run"],
        )
    ]


def test_reexec_updated_managed_windows_worker_uses_service_launcher(tmp_path, monkeypatch):
    from local_shell_mcp import remote_worker_cli, remote_worker_service

    state_dir = tmp_path / "state"
    launcher = state_dir / "worker-service.pyw"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("# launcher\n", encoding="utf-8")
    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_bytes(b"")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(state_dir))
    monkeypatch.setattr(remote.sys, "platform", "win32")
    monkeypatch.setattr(
        remote_worker_cli,
        "_worker_run_exec_argv",
        lambda: [sys.executable, "-m", "local_shell_mcp.main", "worker", "run"],
    )
    monkeypatch.setattr(remote_worker_service, "_current_worker_is_managed", lambda: True)
    monkeypatch.setattr(remote_worker_service, "_windows_pythonw_executable", lambda: pythonw)
    calls = []
    monkeypatch.setattr(remote.os, "execv", lambda executable, argv: calls.append((executable, argv)))

    remote._reexec_updated_worker_runtime()  # noqa: SLF001

    assert calls == [(str(pythonw), [str(pythonw), str(launcher.resolve())])]


@pytest.mark.asyncio
async def test_upgrade_worker_runtime_validates_manifest_version(monkeypatch):
    from local_shell_mcp import remote_worker_installer, remote_worker_service

    monkeypatch.setattr(
        remote_worker_installer,
        "install_or_update_runtime",
        lambda server: {"version": "3.1.0"},
    )
    monkeypatch.setattr(
        remote,
        "_reexec_updated_worker_runtime",
        lambda: pytest.fail("re-executed mismatched runtime"),
    )
    monkeypatch.setattr(
        remote_worker_service,
        "refresh_installed_service_definition",
        lambda: pytest.fail("refreshed service for mismatched runtime"),
    )
    with pytest.raises(RuntimeError, match="manifest provides 3.1.0"):
        await remote._upgrade_worker_runtime("https://example.test", "3.2.0")  # noqa: SLF001

    calls = []
    monkeypatch.setattr(
        remote_worker_installer,
        "install_or_update_runtime",
        lambda server: {"version": "3.2.0"},
    )
    monkeypatch.setattr(
        remote_worker_service,
        "refresh_installed_service_definition",
        lambda: calls.append("refresh"),
    )
    monkeypatch.setattr(remote, "_reexec_updated_worker_runtime", lambda: calls.append("reexec"))
    await remote._upgrade_worker_runtime("https://example.test", "3.2.0")  # noqa: SLF001
    assert calls == ["refresh", "reexec"]


def test_worker_cli_keyboard_interrupt_exits_cleanly():
    code = """
import sys as _sys
_sys.path.insert(0, "src")

from local_shell_mcp import remote


def fake_asyncio_run(coro):
    coro.close()
    raise KeyboardInterrupt


remote.asyncio.run = fake_asyncio_run
remote.run_worker_cli(["--server", "https://example.test", "--invite", "lsmcp_inv_test"])
"""

    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)  # noqa: S603

    assert completed.returncode == 130
    assert "Status: disconnected by user." in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.asyncio
async def test_worker_post_json_forever_retries_until_success(monkeypatch, capsys):
    calls = []
    sleeps = []

    def fake_post(url, payload, headers=None, timeout=None):
        calls.append((url, payload, headers, timeout))
        if len(calls) < 3:
            raise RuntimeError(f"temporary failure {len(calls)}")
        return {"ok": True, "data": {"heartbeat": True}}

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(remote, "_worker_post_json", fake_post)
    monkeypatch.setattr(remote.asyncio, "sleep", fake_sleep)

    result = await remote._worker_post_json_forever(  # noqa: SLF001
        "https://example.test/remote/poll",
        {},
        {"Authorization": "Bearer token"},
        12,
        "poll",
    )

    assert result == {"ok": True, "data": {"heartbeat": True}}
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
    assert "Status: poll failed: temporary failure 1. Retrying in 1s..." in capsys.readouterr().err


def test_worker_post_json_rejects_non_http_server_url():
    with pytest.raises(ValueError, match=r"absolute HTTP\(S\)"):
        remote._worker_post_json("file:///tmp/worker", {"invite": "abc"})  # noqa: SLF001


@pytest.mark.asyncio
async def test_worker_post_json_forever_stops_on_permanent_http_error(monkeypatch):
    calls = []
    sleeps = []

    def fake_post(url, payload, headers=None, timeout=None):
        calls.append((url, payload, headers, timeout))
        raise remote.WorkerHttpError(url, 400, "invalid invite code")

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(remote, "_worker_post_json", fake_post)
    monkeypatch.setattr(remote.asyncio, "sleep", fake_sleep)

    with pytest.raises(remote.WorkerHttpError, match="invalid invite code"):
        await remote._worker_post_json_forever(  # noqa: SLF001
            "https://example.test/remote/register",
            {"invite": "expired"},
            None,
            30,
            "register",
        )

    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_remote_heartbeat_refreshes_worker_last_seen(monkeypatch):
    manager = remote.RemoteManager()
    worker = remote.RemoteWorker(
        name="worker-a", token="token-a", last_seen=1, status="offline"
    )
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    monkeypatch.setattr(remote, "_utc", lambda: 123.0)

    result = await manager.heartbeat(worker.token)

    assert result == {"accepted": True, "name": "worker-a"}
    assert worker.last_seen == 123.0
    assert worker.status == "online"


@pytest.mark.asyncio
async def test_worker_job_sends_heartbeats_while_running(monkeypatch):
    posted_urls = []
    heartbeat_seen = asyncio.Event()
    loop = asyncio.get_running_loop()

    async def fake_execute(tool, args):
        assert tool == "slow_tool"
        assert args == {"value": 1}
        await asyncio.wait_for(heartbeat_seen.wait(), timeout=1)
        return {"done": True}

    def fake_post(url, payload, headers=None, timeout=None):
        posted_urls.append(url)
        assert payload == {"job_id": "job-1"}
        assert headers == {"Authorization": "Bearer token"}
        assert timeout == 30
        loop.call_soon_threadsafe(heartbeat_seen.set)
        return {"ok": True, "data": {"accepted": True}}

    monkeypatch.setattr(remote, "execute_worker_tool", fake_execute)
    monkeypatch.setattr(remote, "_worker_post_json", fake_post)

    result = await remote._execute_worker_job_with_heartbeat(  # noqa: SLF001
        {"id": "job-1", "tool": "slow_tool", "args": {"value": 1}},
        "https://example.test",
        {"Authorization": "Bearer token"},
        0.01,
    )

    assert result == {"done": True}
    assert posted_urls
    assert set(posted_urls) == {"https://example.test/remote/heartbeat"}


@pytest.mark.asyncio
async def test_worker_result_submission_sends_heartbeats_while_retrying(monkeypatch):
    result_attempts = 0
    heartbeat_calls = []
    result = {"job_id": "job-1", "ok": True, "data": {"done": True}}
    headers = {"Authorization": "Bearer token"}

    def fake_post(url, payload, request_headers=None, timeout=None):
        nonlocal result_attempts
        assert request_headers == headers
        if url.endswith("/result"):
            assert timeout == remote._worker_result_request_timeout_s(result)  # noqa: SLF001
            assert payload == result
            result_attempts += 1
            if result_attempts < 3:
                raise RuntimeError(f"temporary result failure {result_attempts}")
            return {"ok": True, "data": {"accepted": True}}
        assert url.endswith("/heartbeat")
        assert timeout == 30
        assert payload == {"job_id": "job-1"}
        heartbeat_calls.append(url)
        return {"ok": True, "data": {"accepted": True}}

    monkeypatch.setattr(remote, "_worker_post_json", fake_post)
    monkeypatch.setattr(remote, "_WORKER_RETRY_INITIAL_DELAY_S", 0.02)
    monkeypatch.setattr(remote, "_WORKER_RETRY_MAX_DELAY_S", 0.02)

    response = await remote._submit_worker_result_with_heartbeat(  # noqa: SLF001
        result,
        "https://example.test",
        headers,
        0.005,
    )

    assert response == {"ok": True, "data": {"accepted": True}}
    assert result_attempts == 3
    assert heartbeat_calls
    heartbeat_count = len(heartbeat_calls)
    await asyncio.sleep(0.02)
    assert len(heartbeat_calls) == heartbeat_count


def test_worker_result_request_timeout_scales_with_payload_size():
    small = {"job_id": "job-1", "ok": True, "data": {"stdout": "ok"}}
    large = {"job_id": "job-1", "ok": True, "data": {"stdout": "x" * (3 * 1024 * 1024)}}

    assert remote._worker_result_request_timeout_s(small) == 30  # noqa: SLF001
    assert remote._worker_result_request_timeout_s(large) > 120  # noqa: SLF001


@pytest.mark.asyncio
async def test_worker_result_submission_stops_when_controller_cancels(monkeypatch):
    result_attempts = 0
    heartbeat_calls = []
    result = {"job_id": "job-1", "ok": True, "data": {"stdout": "x"}}
    headers = {"Authorization": "Bearer token"}

    def fake_post(url, payload, request_headers=None, timeout=None):
        nonlocal result_attempts
        assert request_headers == headers
        if url.endswith("/result"):
            result_attempts += 1
            raise RuntimeError("slow result upload")
        assert url.endswith("/heartbeat")
        assert timeout == 30
        assert payload == {"job_id": "job-1"}
        heartbeat_calls.append(payload)
        return {"ok": True, "data": {"accepted": True, "cancelled": True}}

    monkeypatch.setattr(remote, "_worker_post_json", fake_post)
    monkeypatch.setattr(remote, "_WORKER_RETRY_INITIAL_DELAY_S", 0.05)
    monkeypatch.setattr(remote, "_WORKER_RETRY_MAX_DELAY_S", 0.05)

    response = await remote._submit_worker_result_with_heartbeat(  # noqa: SLF001
        result,
        "https://example.test",
        headers,
        0.005,
    )

    assert response == {"ok": True, "data": {"accepted": False, "cancelled": True}}
    assert result_attempts >= 1
    assert heartbeat_calls == [{"job_id": "job-1"}]
    attempts_after_cancel = result_attempts
    await asyncio.sleep(0.06)
    assert result_attempts == attempts_after_cancel


@pytest.mark.asyncio
async def test_remote_result_must_come_from_assigned_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    manager._registry_loaded = True
    worker_a = remote.RemoteWorker(name="worker-a", token="token-a")
    worker_b = remote.RemoteWorker(name="worker-b", token="token-b")
    manager.workers = {worker_a.name: worker_a, worker_b.name: worker_b}
    manager.tokens = {worker_a.token: worker_a.name, worker_b.token: worker_b.name}
    future = asyncio.get_running_loop().create_future()
    manager.pending["job-owned"] = future
    manager.pending_machines["job-owned"] = worker_a.name

    with pytest.raises(PermissionError, match="belongs to machine"):
        await manager.submit_result(
            worker_b.token,
            {"job_id": "job-owned", "ok": True, "data": {"forged": True}},
        )

    assert not future.done()
    assert manager.pending["job-owned"] is future
    assert manager.pending_machines["job-owned"] == worker_a.name

    accepted = await manager.submit_result(
        worker_a.token,
        {"job_id": "job-owned", "ok": True, "data": {"valid": True}},
    )
    assert accepted == {"accepted": True}
    assert future.result()["data"] == {"valid": True}


def test_remote_cancelled_job_tombstones_are_pruned_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S", "10")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS", "1")
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    manager.cancelled_jobs = {f"old-{index}": 0.0 for index in range(80)}
    monkeypatch.setattr(remote, "_utc", lambda: 100.0)

    manager._cancel_job("new-job")

    assert "new-job" in manager.cancelled_jobs
    assert all(not job_id.startswith("old-") for job_id in manager.cancelled_jobs)
    assert len(manager.cancelled_jobs) <= 64
