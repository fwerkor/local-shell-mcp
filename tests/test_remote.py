

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

    assert 'export PYTHONPATH="$TMPDIR:$TMPDIR/vendor:${PYTHONPATH:-}"' in script


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
