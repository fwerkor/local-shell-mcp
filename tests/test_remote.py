

import asyncio
import subprocess
import sys
import urllib.error
from io import BytesIO

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
            "protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
            "worker_version": "0.0.0",
        },
    )

    assert mismatch == {
        "job": None,
        "upgrade": {"required": True, "version": remote.__version__},
    }
    assert worker.queue.qsize() == 1
    assert worker.info["lsm_version"] == "0.0.0"

    matched = await manager.poll(
        worker.token,
        {
            "protocol_version": remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
            "worker_version": remote.__version__,
        },
    )
    assert matched["job"]["id"] == "job-valid"
    assert matched["upgrade"] == {"required": False, "version": remote.__version__}


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

    def fake_run(command, *, input, capture_output, check):  # noqa: A002
        calls.append((command, input, check))
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
    command, body, check = calls[0]
    assert command[:4] == ["/usr/bin/curl", "--max-time", "30", "-sS"]
    assert ["-H", "Authorization: Bearer token"] in [command[index : index + 2] for index in range(len(command) - 1)]
    assert command[-1] == "https://example.test/remote/register"
    assert body == b'{"invite": "abc"}'
    assert check is False


def test_worker_post_json_curl_reports_non_2xx_body(monkeypatch):
    def fake_run(command, *, input, capture_output, check):  # noqa: A002, ARG001
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
        "https://example.test/remote/poll",
        {},
        {"Authorization": "Bearer token"},
        12,
    )

    assert result == {"ok": True, "data": {"heartbeat": True}}
    assert captured["timeout"] == 12
    assert captured["request"].headers["Authorization"] == "Bearer token"
    assert captured["request"].data == b"{}"


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


def test_worker_retry_delay_is_capped():
    assert [remote._worker_retry_delay(i) for i in range(7)] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]  # noqa: SLF001


def test_reexec_updated_worker_runtime_prefers_installed_bundle(tmp_path, monkeypatch):
    from local_shell_mcp import remote_worker_cli

    state_dir = tmp_path / "state"
    runtime = state_dir / "runtime"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(state_dir))
    monkeypatch.setenv("PYTHONPATH", "/old/runtime:/other")
    monkeypatch.setattr(
        remote_worker_cli,
        "_worker_run_exec_argv",
        lambda: [sys.executable, "-m", "local_shell_mcp.main", "worker", "run"],
    )
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


@pytest.mark.asyncio
async def test_upgrade_worker_runtime_validates_manifest_version(monkeypatch):
    from local_shell_mcp import remote_worker_installer

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
    with pytest.raises(RuntimeError, match="manifest provides 3.1.0"):
        await remote._upgrade_worker_runtime("https://example.test", "3.2.0")  # noqa: SLF001

    calls = []
    monkeypatch.setattr(
        remote_worker_installer,
        "install_or_update_runtime",
        lambda server: {"version": "3.2.0"},
    )
    monkeypatch.setattr(remote, "_reexec_updated_worker_runtime", lambda: calls.append("reexec"))
    await remote._upgrade_worker_runtime("https://example.test", "3.2.0")  # noqa: SLF001
    assert calls == ["reexec"]


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

    async def fake_execute(tool, args):
        assert tool == "slow_tool"
        assert args == {"value": 1}
        await asyncio.sleep(0.05)
        return {"done": True}

    def fake_post(url, payload, headers=None, timeout=None):
        posted_urls.append(url)
        assert payload == {}
        assert headers == {"Authorization": "Bearer token"}
        assert timeout == 30
        return {"ok": True, "data": {"accepted": True}}

    monkeypatch.setattr(remote, "execute_worker_tool", fake_execute)
    monkeypatch.setattr(remote, "_worker_post_json", fake_post)

    result = await remote._execute_worker_job_with_heartbeat(  # noqa: SLF001
        {"tool": "slow_tool", "args": {"value": 1}},
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
        assert timeout == 30
        if url.endswith("/result"):
            assert payload == result
            result_attempts += 1
            if result_attempts < 3:
                raise RuntimeError(f"temporary result failure {result_attempts}")
            return {"ok": True, "data": {"accepted": True}}
        assert url.endswith("/heartbeat")
        assert payload == {}
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
