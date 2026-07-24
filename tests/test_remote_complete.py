from __future__ import annotations

import asyncio
import hashlib
import io
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import local_shell_mcp.remote as remote
from local_shell_mcp.errors import ShellExecutableNotFoundError
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch, **extra):
    values = {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(tmp_path),
        "LOCAL_SHELL_MCP_STATE_DIR": str(tmp_path / ".state"),
        "LOCAL_SHELL_MCP_AUTH_MODE": "none",
        "LOCAL_SHELL_MCP_PUBLIC_BASE_URL": "http://testserver",
        "LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S": "1",
        "LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S": "30",
    }
    values.update({key: str(value) for key, value in extra.items()})
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _result() -> CommandResult:
    return CommandResult(
        ok=True,
        exit_code=0,
        timed_out=False,
        duration_ms=1,
        cwd=".",
        command="cmd",
        stdout="ok",
        stderr="",
        truncated=False,
    )


def test_distribution_helpers_and_worker_bundle(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert remote._canonical_dist_name("My_Pkg.Name") == "my-pkg-name"
    assert remote._dist_name_from_requirement("pkg-name>=1") == "pkg-name"
    assert remote._dist_name_from_requirement("extra; extra == 'x'") is None
    assert remote._dist_name_from_requirement(" !!!") is None

    package_file = tmp_path / "module.py"
    package_file.write_text("x = 1\n", encoding="utf-8")
    bytecode = tmp_path / "module.pyc"
    bytecode.write_bytes(b"ignored")
    unsafe = Path("../unsafe.py")

    class FakeDist:
        requires = ["dependency>=1", "optional; extra == 'feature'"]
        files = [Path("module.py"), Path("module.pyc"), unsafe]

        def locate_file(self, entry):
            return tmp_path / entry

    calls = []

    def distribution(name):
        calls.append(name)
        if name == "missing":
            raise remote.importlib_metadata.PackageNotFoundError(name)
        return FakeDist()

    monkeypatch.setattr(remote.importlib_metadata, "distribution", distribution)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        remote._add_distribution_to_tar(tar, "root", set())
        remote._add_distribution_to_tar(tar, "missing", set())
    with tarfile.open(fileobj=io.BytesIO(buffer.getvalue()), mode="r:gz") as tar:
        names = tar.getnames()
    assert "vendor/module.py" in names
    assert all(not name.endswith(".pyc") for name in names)
    assert "dependency" in calls

    response = asyncio.run(remote.worker_bundle(None))
    assert response.media_type == "application/gzip"
    with tarfile.open(fileobj=io.BytesIO(response.body), mode="r:gz") as tar:
        bundled = tar.getnames()
    assert "local_shell_mcp/remote.py" in bundled
    assert not any(name.endswith(".pyc") for name in bundled)


def test_controller_registration_resume_rename_revoke_and_defaults(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    manager = remote.RemoteManager()
    monkeypatch.setattr(remote, "_utc", lambda: 100.0)

    invite = asyncio.run(manager.create_invite(ttl_s=1, base_url="http://control.test"))
    assert invite["ttl_s"] == 60
    registration = asyncio.run(
        manager.register_worker(
            {
                "invite": invite["code"],
                "workdir": "/work",
                "capabilities": ["files"],
                "info": {"user": "alice", "hostname": "host"},
            }
        )
    )
    assert registration["name"] == "alice@host"
    assert registration["poll_timeout_s"] == 1
    token = registration["token"]

    with pytest.raises(ValueError, match="invalid invite"):
        asyncio.run(manager.register_worker({"invite": "missing"}))

    resumed = asyncio.run(
        manager.resume_worker(
            token,
            {"name": "alice@host", "workdir": "/new", "capabilities": ["shell"]},
        )
    )
    assert resumed["name"] == "alice@host"
    assert resumed["poll_timeout_s"] == 1
    assert manager.workers["alice@host"].workdir == "/new"
    with pytest.raises(ValueError, match="belongs"):
        asyncio.run(manager.resume_worker(token, {"name": "other"}))
    with pytest.raises(PermissionError):
        asyncio.run(manager.resume_worker("invalid", {}))

    second_invite = asyncio.run(manager.create_invite(base_url="http://control.test"))
    second = asyncio.run(
        manager.register_worker(
            {
                "invite": second_invite["code"],
                "info": {"user": "alice", "hostname": "host"},
            }
        )
    )
    assert second["name"] == "alice@host-2"

    renamed = manager.rename("alice@host", "renamed")
    assert renamed == {"old_name": "alice@host", "new_name": "renamed"}
    assert manager.tokens[token] == "renamed"
    with pytest.raises(ValueError, match="already exists"):
        manager.rename("renamed", "alice@host-2")
    with pytest.raises(ValueError, match="unknown"):
        manager.rename("missing", "new")

    revoked = manager.revoke("renamed")
    assert revoked["revoked"] is True
    with pytest.raises(ValueError, match="unknown"):
        manager.revoke("renamed")
    with pytest.raises(PermissionError):
        manager._worker_by_token(token)


def test_controller_poll_result_errors_and_cancellation(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    manager = remote.RemoteManager()
    manager._registry_loaded = True
    worker = remote.RemoteWorker(name="node", token="token", last_seen=100)
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    monkeypatch.setattr(remote, "_utc", lambda: 100.0)

    assert asyncio.run(manager.heartbeat("token", {"job_id": "none"}))["accepted"] is True
    assert asyncio.run(manager.submit_result("token", {"job_id": "unknown"})) == {"accepted": False}

    async def failed_call():
        task = asyncio.create_task(manager.call("node", "list_files", {}, timeout_s=2))
        polled = await manager.poll("token")
        await manager.submit_result(
            "token",
            {"job_id": polled["job"]["id"], "ok": False, "error": "Boom", "message": "bad"},
        )
        return await task

    failed = asyncio.run(failed_call())
    assert failed["ok"] is False
    assert failed["data"]["status"] == "error"
    assert failed["data"]["error_type"] == "Boom"

    async def cancelled_call():
        task = asyncio.create_task(manager.call("node", "list_files", {}, timeout_s=10))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled_call())
    with pytest.raises(ValueError, match="unknown remote"):
        asyncio.run(manager.call("missing", "x", {}))
    worker.last_seen = 0
    with pytest.raises(RuntimeError, match="offline"):
        asyncio.run(manager.call("node", "x", {}))


def test_remote_http_routes_success_and_errors(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    manager = remote.RemoteManager()
    monkeypatch.setattr(remote, "REMOTE_MANAGER", manager)
    app = Starlette(routes=remote.remote_routes())
    client = TestClient(app)

    invite = asyncio.run(manager.create_invite("route-node", base_url="http://testserver"))
    registered = client.post(
        "/remote/register",
        json={"invite": invite["code"], "name": "route-node", "info": {}},
    )
    assert registered.status_code == 200
    token = registered.json()["data"]["token"]
    headers = {"authorization": f"Bearer {token}"}

    resumed = client.post("/remote/resume", json={"name": "route-node"}, headers=headers)
    assert resumed.status_code == 200
    heartbeat = client.post("/remote/heartbeat", json={}, headers=headers)
    assert heartbeat.json()["data"]["accepted"] is True
    result = client.post("/remote/result", json={"job_id": "missing"}, headers=headers)
    assert result.json()["data"]["accepted"] is False

    assert client.post("/remote/register", json={"invite": "bad"}).status_code == 400
    assert client.post("/remote/resume", json={}, headers={}).status_code == 401
    assert client.post("/remote/poll", json={}, headers={}).status_code == 401
    assert client.post("/remote/heartbeat", json={}, headers={}).status_code == 401
    assert client.post("/remote/result", json={}, headers={}).status_code == 401
    assert remote._bearer_token(SimpleNamespace(headers={"authorization": "Basic x"})) == ""

    join = client.get("/join")
    assert join.status_code == 200
    assert "--invite is required" in join.text
    bundle = client.get(remote.REMOTE_WORKER_BUNDLE_PATH)
    assert bundle.status_code == 200


@pytest.mark.asyncio
async def test_every_worker_tool_dispatch_branch(monkeypatch, tmp_path):
    _configure(tmp_path, monkeypatch)
    command_result = _result()

    async def async_value(*args, **kwargs):
        return {"args": list(args), "kwargs": kwargs}

    def sync_value(*args, **kwargs):
        return {"args": list(args), "kwargs": kwargs}

    monkeypatch.setattr(remote, "run_shell", lambda *args, **kwargs: asyncio.sleep(0, result=command_result))
    monkeypatch.setattr(remote, "public_run_shell", lambda *args, **kwargs: asyncio.sleep(0, result=command_result))
    monkeypatch.setattr(remote, "_run_python", async_value)
    for name in (
        "start_shell",
        "send_shell",
        "read_shell",
        "kill_shell",
        "list_shells",
        "start_job",
        "list_jobs",
        "tail_job",
        "stop_job",
        "retry_job",
        "resize_shell",
        "tree",
        "grep",
        "browser_capture",
        "browser_get_text",
        "playwright_run_script",
        "_apply_patch_text",
    ):
        monkeypatch.setattr(remote, name, async_value)
    for name in (
        "list_dir",
        "glob_paths",
        "read_texts",
        "write_text",
        "edit_text",
        "delete_path",
        "perform_file_action",
        "transfer_stat",
        "transfer_read_chunk",
        "transfer_begin_write",
        "transfer_write_chunk",
        "transfer_finish_write",
        "transfer_abort_write",
        "transfer_alloc_temp_path",
        "transfer_pack_dir",
        "transfer_unpack_archive",
        "_worker_upload_url",
        "_worker_download_url",
    ):
        monkeypatch.setattr(remote, name, sync_value)

    cases = {
        "environment_info": {},
        "run_shell_tool": {"command": "echo ok"},
        "run_python_tool": {"code": "print(1)"},
        "shell_start": {},
        "shell_send": {"session_id": "s", "input_text": "x"},
        "shell_read": {"session_id": "s"},
        "shell_resize": {"session_id": "s", "cols": 120, "rows": 35},
        "shell_kill": {"session_id": "s"},
        "shell_list": {},
        "job_start": {"command": "true"},
        "job_list": {},
        "job_tail": {"job_id": "j"},
        "job_stop": {"job_id": "j"},
        "job_retry": {"job_id": "j"},
        "list_files": {},
        "tree_view": {},
        "glob_search": {"pattern": "*.py"},
        "grep_search": {"query": "x"},
        "read_file": {"path": "x"},
        "write_file": {"path": "x", "content": "y"},
        "edit_file": {"path": "x", "edits": []},
        "delete_file_or_dir": {"path": "x"},
        "human_file_action": {"action": "touch", "path": "x"},
        "transfer_stat": {"path": "x"},
        "transfer_read_chunk": {"path": "x"},
        "transfer_begin_write": {"path": "x"},
        "transfer_write_chunk": {"path": "x", "transfer_id": "t", "offset": 0, "data_b64": ""},
        "transfer_finish_write": {"path": "x", "transfer_id": "t"},
        "transfer_abort_write": {"path": "x", "transfer_id": "t"},
        "transfer_alloc_temp_path": {},
        "transfer_pack_dir": {"path": "x"},
        "transfer_unpack_archive": {"archive_path": "a", "dst_path": "d"},
        "transfer_upload_url": {"path": "x", "url": "http://x", "expected_bytes": 0, "expected_sha256": "d"},
        "transfer_download_url": {"url": "http://x", "path": "x", "expected_bytes": 0, "expected_sha256": "d"},
        "apply_patch": {"patch": "diff"},
        "browser_capture_tool": {"url": "https://x"},
        "browser_get_text_tool": {"url": "https://x"},
        "playwright_run_script_tool": {"script": "print(1)"},
    }
    for tool, args in cases.items():
        result = await remote.execute_worker_tool(tool, {**args, "_human": True})
        assert result is not None, tool

    with pytest.raises(ValueError, match="unsupported"):
        await remote.execute_worker_tool("unknown", {})


def test_worker_transfer_validation_and_curl_failures(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_WORKER_STATE_DIR=tmp_path / "worker-state")
    remote._write_worker_identity(
        {"server": "https://control.test", "name": "node", "access": "token"}
    )
    valid = "https://control.test/remote/transfer/token"
    remote._worker_validate_transfer_url(valid)
    for url in (
        "file:///tmp/x",
        "https://other.test/remote/transfer/x",
        "https://control.test/not-transfer/x",
    ):
        with pytest.raises(ValueError):
            remote._worker_validate_transfer_url(url)

    assert remote._worker_curl_timeout(None) == 30
    assert remote._worker_curl_timeout(1) == 30
    assert remote._worker_curl_timeout(999) == 30

    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="curl"):
        remote._worker_upload_url("source.bin", valid, 7, digest)
    with pytest.raises(FileNotFoundError, match="curl"):
        remote._worker_download_url(valid, "dest.bin", True, 7, digest)
    assert not (tmp_path / "dest.bin").exists()

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 22, stdout="", stderr="network"),
    )
    with pytest.raises(RuntimeError, match="curl exit 22"):
        remote._worker_upload_url("source.bin", valid, 7, digest)
    with pytest.raises(RuntimeError, match="curl exit 22"):
        remote._worker_download_url(valid, "dest.bin", True, 7, digest)


def test_worker_identity_storage_retryability_and_http_parsing(tmp_path, monkeypatch, capsys):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_WORKER_STATE_DIR=tmp_path / "worker-state")
    assert remote._worker_state_dir() == tmp_path / "worker-state"
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert remote._worker_state_dir() == tmp_path / "xdg" / "local-shell-mcp-worker"
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert remote._worker_state_dir() == tmp_path / "home" / ".local/state/local-shell-mcp-worker"

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    identity = {"server": "https://control.test", "name": "node", "access": "token"}
    remote._write_worker_identity(identity)
    assert remote._read_worker_identity("https://control.test") == identity
    assert remote._read_worker_identity("https://other.test") is None
    assert remote._read_worker_identity("https://control.test", "other") is None
    remote._worker_identity_path().write_text("bad", encoding="utf-8")
    assert remote._read_worker_identity("https://control.test") is None
    remote._delete_worker_identity()
    remote._delete_worker_identity()

    assert remote._worker_error_is_retryable(remote.WorkerHttpError("u", 429, "busy"))
    assert remote._worker_error_is_retryable(remote.WorkerHttpError("u", 503, "down"))
    assert not remote._worker_error_is_retryable(remote.WorkerHttpError("u", 400, "bad"))
    assert not remote._worker_error_is_retryable(ValueError("bad"))
    assert remote._worker_error_is_retryable(RuntimeError("temporary"))
    remote._worker_log_retry("poll", RuntimeError("down"), 2)
    assert "Retrying in 2s" in capsys.readouterr().err

    assert remote._parse_worker_http_json("u", 200, '{"ok":true}') == {"ok": True}
    with pytest.raises(remote.WorkerHttpError):
        remote._parse_worker_http_json("u", 500, "down")
    with pytest.raises(RuntimeError, match="invalid JSON"):
        remote._parse_worker_http_json("u", 200, "bad")
    with pytest.raises(RuntimeError, match="expected object"):
        remote._parse_worker_http_json("u", 200, "[]")


def test_worker_cli_error_path(monkeypatch, capsys):
    async def fail(*args, **kwargs):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(remote, "run_worker", fail)
    with pytest.raises(SystemExit) as raised:
        remote.run_worker_cli(["--server", "https://x", "--invite", "i"])
    assert raised.value.code == 1
    assert "connection failed" in capsys.readouterr().err



def test_remote_registry_invite_and_registration_edge_cases(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    invalid = tmp_path / "invalid-registry.json"
    for payload in (
        "[]",
        '{"version":2,"workers":[]}',
        '{"version":1,"workers":{}}',
    ):
        invalid.write_text(payload, encoding="utf-8")
        with pytest.raises(ValueError, match="registry"):
            remote.RemoteManager._read_registry(invalid)

    manager = remote.RemoteManager()
    manager._registry_loaded = True
    with pytest.raises(ValueError, match="required"):
        remote._validate_machine_name("   ")

    monkeypatch.setattr(remote, "MAX_REMOTE_INVITES", 0)
    with pytest.raises(RuntimeError, match="Too many"):
        asyncio.run(manager.create_invite())
    monkeypatch.setattr(remote, "MAX_REMOTE_INVITES", 128)

    now = 100.0
    monkeypatch.setattr(remote, "_utc", lambda: now)
    manager.invites["used"] = remote.RemoteInvite("used", None, None, now + 10, used=True)
    with pytest.raises(ValueError, match="already"):
        asyncio.run(manager.register_worker({"invite": "used"}))
    manager.invites["expired"] = remote.RemoteInvite("expired", None, None, now - 1)
    with pytest.raises(ValueError, match="expired"):
        asyncio.run(manager.register_worker({"invite": "expired"}))
    manager.invites["bound"] = remote.RemoteInvite("bound", "bound-name", None, now + 10)
    with pytest.raises(ValueError, match="bound"):
        asyncio.run(
            manager.register_worker({"invite": "bound", "name": "different"})
        )
    manager.workers["duplicate"] = remote.RemoteWorker("duplicate", "existing")
    manager.invites["duplicate"] = remote.RemoteInvite(
        "duplicate", "duplicate", None, now + 10
    )
    with pytest.raises(ValueError, match="already exists"):
        asyncio.run(manager.register_worker({"invite": "duplicate"}))

    manager.tokens["orphan"] = "missing"
    with pytest.raises(PermissionError, match="no longer valid"):
        asyncio.run(manager.resume_worker("orphan", {}))

    manager.workers["user@host"] = remote.RemoteWorker("user@host", "one")
    manager.workers["user@host-2"] = remote.RemoteWorker("user@host-2", "two")
    assert manager._default_machine_name(
        {"info": {"user": "user", "hostname": "host"}}
    ) == "user@host-3"


def test_remote_cancel_prune_revoke_and_rename_pending_jobs(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS=1,
        LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S=1000,
    )
    manager = remote.RemoteManager()
    manager._registry_loaded = True
    worker = remote.RemoteWorker("node", "token", last_seen=100)
    manager.workers["node"] = worker
    manager.tokens["token"] = "node"
    monkeypatch.setattr(remote, "_utc", lambda: 100.0)

    for index in range(70):
        manager.cancelled_jobs[f"job-{index}"] = 100.0
    manager._prune_cancelled_jobs_locked(100.0)
    assert len(manager.cancelled_jobs) == 64

    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        manager.pending["cancel-me"] = future
        manager.pending_machines["cancel-me"] = "node"
        assert manager._cancel_job_if_unclaimed("cancel-me") is True
        assert future.cancelled()
    finally:
        loop.close()

    manager.pending_machines["pending"] = "node"
    worker.queue.put_nowait({"id": "queued"})
    renamed = manager.rename("node", "renamed")
    assert renamed["new_name"] == "renamed"
    assert manager.pending_machines["pending"] == "renamed"

    manager.pending_machines["pending"] = "renamed"
    manager.pending["pending"] = None  # type: ignore[assignment]
    revoked = manager.revoke("renamed")
    assert revoked["revoked"] is True
    assert worker.queue.empty()
    assert "queued" not in manager.cancelled_jobs


@pytest.mark.asyncio
async def test_remote_mutation_timeout_and_claimed_cancellation_cleanup(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch)
    manager = remote.RemoteManager()
    manager._registry_loaded = True
    worker = remote.RemoteWorker("node", "token", last_seen=100)
    manager.workers["node"] = worker
    manager.tokens["token"] = "node"
    monkeypatch.setattr(remote, "_utc", lambda: 100.0)

    with pytest.raises(TimeoutError, match="write_file"):
        await manager.call("node", "write_file", {}, timeout_s=0.01)

    task = asyncio.create_task(
        manager.call("node", "write_file", {"path": "x"}, timeout_s=10)
    )
    polled = await manager.poll("token")
    job_id = polled["job"]["id"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert job_id in manager.pending
    accepted = await manager.submit_result(
        "token", {"job_id": job_id, "ok": True, "data": {"done": True}}
    )
    assert accepted == {"accepted": True}
    await asyncio.sleep(0)
    assert job_id not in manager.pending
    assert job_id not in manager.pending_machines
    assert job_id not in manager.claimed_jobs


def test_worker_upload_protocol_and_generated_execution_edges(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_WORKER_STATE_DIR=tmp_path / "worker-state",
    )
    remote._write_worker_identity(
        {"server": "https://control.test", "name": "node", "access": "token"}
    )
    url = "https://control.test/remote/transfer/token"
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="not a file"):
        remote._worker_upload_url("directory", url, 0, hashlib.sha256(b"").hexdigest())

    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    with pytest.raises(ValueError, match="size mismatch"):
        remote._worker_upload_url("source.bin", url, 8, digest)
    with pytest.raises(ValueError, match="sha256"):
        remote._worker_upload_url("source.bin", url, 7, "0" * 64)

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="not-json", stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match="invalid response"):
        remote._worker_upload_url("source.bin", url, 7, digest)
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout='{"ok":false,"message":"bad"}\n__LSM_HTTP_STATUS__:400',
            stderr="",
        ),
    )
    with pytest.raises(RuntimeError, match="HTTP 400"):
        remote._worker_upload_url("source.bin", url, 7, digest)

    async def fake_run_shell(command, **kwargs):
        return _result()

    monkeypatch.setattr(remote, "run_shell", fake_run_shell)
    patch = asyncio.run(remote._apply_patch_text("diff --git a/a b/a\n", "."))
    assert patch["patch_path"].endswith(".diff")
    script = asyncio.run(remote._run_python("print('ok')", ".", 5))
    assert script["script_path"].endswith(".py")
    assert remote._handled_remote_exception(ValueError("bad"))["error"] == "ValueError"
    shell_error = remote._handled_remote_exception(
        ShellExecutableNotFoundError("missing-shell", "echo ok", ".", "[WinError 2]")
    )
    assert shell_error["ok"] is False
    assert shell_error["data"]["status"] == "executable_not_found"
    assert shell_error["data"]["executable"] == "missing-shell"
    assert shell_error["data"]["command"] == "echo ok"


@pytest.mark.asyncio
async def test_worker_apply_patch_honors_nested_cwd_in_git_worktree(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "sample.py"
    target.write_text(
        "def helper():\n    return 0\n\n\ndef target():\n    return 1\n",
        encoding="utf-8",
    )
    patch = """*** Begin Patch
*** Update File: sample.py
@@
 def target():
@@
-    return 1
+    return 2
*** End Patch
"""

    result = await remote._apply_patch_text(patch, str(nested))

    assert result["exit_code"] == 0, result
    assert target.read_text(encoding="utf-8").endswith("def target():\n    return 2\n")


def test_worker_resume_identity_and_curl_post_failures(tmp_path, monkeypatch, capsys):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_WORKER_STATE_DIR=tmp_path / "worker-state",
    )
    remote._write_worker_identity(
        {"server": "https://control.test", "name": "node", "access": "token"}
    )
    assert remote._worker_identity_rejected(RuntimeError("failed with 401"))
    assert remote._worker_identity_rejected(RuntimeError("invalid worker identity"))
    assert remote._worker_identity_rejected(RuntimeError("identity is no longer valid"))
    assert not remote._worker_identity_rejected(RuntimeError("temporary"))

    monkeypatch.setattr(
        remote,
        "_worker_post_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            remote.WorkerHttpError("u", 401, "invalid")
        ),
    )
    assert asyncio.run(remote._worker_resume_or_none("u", {}, {})) is None
    assert not remote._worker_identity_path().exists()
    assert "identity rejected" in capsys.readouterr().err

    attempts = iter([RuntimeError("temporary"), {"ok": True}])

    def retry(*args, **kwargs):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(remote, "_worker_post_json", retry)
    monkeypatch.setattr(remote, "_worker_retry_delay", lambda attempt: 0)
    assert asyncio.run(remote._worker_resume_or_none("u", {}, {})) == {"ok": True}
    with pytest.raises(ValueError, match="permanent"):
        monkeypatch.setattr(
            remote,
            "_worker_post_json",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("permanent")),
        )
        asyncio.run(remote._worker_resume_or_none("u", {}, {}))

    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="curl"):
        remote._worker_post_json_with_curl("u", b"{}", {})
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 7, stdout=b"body\nLOCAL_SHELL_MCP_HTTP_STATUS:503", stderr=b"network"
        ),
    )
    with pytest.raises(RuntimeError, match="curl exit 7"):
        remote._worker_post_json_with_curl("u", b"{}", {"X-Test": "1"}, 2)


def test_worker_identity_incomplete_and_cli_interrupt(tmp_path, monkeypatch, capsys):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_WORKER_STATE_DIR=tmp_path / "worker-state",
    )
    path = remote._worker_identity_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"server":"https://control.test","name":"","access":""}',
        encoding="utf-8",
    )
    assert remote._read_worker_identity("https://control.test") is None

    async def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(remote, "run_worker", interrupted)
    with pytest.raises(SystemExit) as raised:
        remote.run_worker_cli(["--server", "https://x", "--invite", "i"])
    assert raised.value.code == 130
    assert "disconnected by user" in capsys.readouterr().err
