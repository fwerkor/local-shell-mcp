from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import local_shell_mcp.audit as audit_module
import local_shell_mcp.jobs as jobs_module
import local_shell_mcp.oauth as oauth_module
import local_shell_mcp.peer_transfer as peer_transfer_module
import local_shell_mcp.remote as remote_module
import local_shell_mcp.state_store as state_store_module
import local_shell_mcp.tools as tools
import local_shell_mcp.ui_security as ui_security
from local_shell_mcp.dynamic_mcp import DynamicMCPManager
from local_shell_mcp.peer_transfer import close_peer_receiver, open_peer_receiver
from local_shell_mcp.settings import get_settings
from local_shell_mcp.state_store import (
    FileStateStore,
    MemoryStateStore,
    RedisStateStore,
    clear_memory_state,
    get_state_store,
)
from local_shell_mcp.transfer_ops import transfer_stat


def _configure_stateless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATELESS_CONTROLLER", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "s" * 48)
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://controller.test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX", f"test-{tmp_path.name}")
    for key, value in env.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key.upper(), value)
    get_settings.cache_clear()
    clear_memory_state()


def _configure_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "s" * 48)
    for key, value in env.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key.upper(), value)
    get_settings.cache_clear()
    get_settings()
    return root


def test_stateless_settings_require_no_persistent_directories(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)

    settings = get_settings()

    assert settings.stateless_controller is True
    assert settings.disable_local is True
    assert settings.state_backend == "memory"
    assert settings.file_download_enabled is False
    assert settings.ui_wallpaper == "none"
    assert not settings.workspace_root.exists()
    assert not settings.state_dir.exists()


def test_stateless_oauth_requires_strong_explicit_signing_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATELESS_CONTROLLER", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="OAUTH_JWT_SECRET"):
        get_settings()

    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "short")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        get_settings()


def test_stateless_without_oauth_does_not_require_jwt_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATELESS_CONTROLLER", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.stateless_controller is True
    assert settings.auth_mode == "none"


def test_stateless_ui_local_token_uses_state_backend(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)

    token = ui_security.get_or_create_ui_local_token()

    assert len(token) >= 32
    assert get_state_store().read_bytes("ui/local-token") == token.encode("utf-8")
    assert not get_settings().state_dir.exists()


def test_file_and_memory_state_store_round_trip(tmp_path):
    file_store = FileStateStore(tmp_path / "state")
    assert file_store.read_bytes("missing") is None
    assert file_store.list_keys() == []
    file_store.write_bytes("nested/value.bin", b"value")
    file_store.write_bytes("other.bin", b"other")
    assert file_store.read_bytes("nested/value.bin") == b"value"
    assert file_store.list_keys("nested/") == ["nested/value.bin"]
    with file_store.lock("nested/value.bin"):
        assert file_store.read_bytes("nested/value.bin") == b"value"
    file_store.delete("nested/value.bin")
    assert file_store.read_bytes("nested/value.bin") is None
    with pytest.raises(ValueError, match="escapes state directory"):
        file_store.read_bytes("../escape")

    clear_memory_state()
    first = MemoryStateStore("first")
    second = MemoryStateStore("second")
    assert first.read_bytes("key") is None
    first.write_bytes("key", b"one")
    first.write_bytes("nested/key", b"two")
    second.write_bytes("key", b"other")
    assert first.read_bytes("key") == b"one"
    assert second.read_bytes("key") == b"other"
    assert first.list_keys("nested/") == ["nested/key"]
    with first.lock("key"):
        assert first.read_bytes("key") == b"one"
    first.delete("key")
    assert first.read_bytes("key") is None
    assert state_store_module._MEMORY_LOCKS == {}

    with first.lock("held"):
        first.write_bytes("held", b"value")
        assert len(state_store_module._MEMORY_LOCKS) == 1
    assert state_store_module._MEMORY_LOCKS == {}

    for index in range(1_000):
        key = f"ephemeral/{index}"
        first.write_bytes(key, b"value")
        first.delete(key)
    assert state_store_module._MEMORY_LOCKS == {}


def test_redis_state_store_round_trip_and_lock(monkeypatch):
    class FakeLock:
        def __init__(self, acquired: bool = True, reacquire_failures: int = 0):
            self.acquired = acquired
            self.released = False
            self.reacquired = 0
            self.reacquire_failures = reacquire_failures

        def acquire(self, *, blocking: bool):
            assert blocking is True
            return self.acquired

        def release(self):
            self.released = True

        def reacquire(self):
            self.reacquired += 1
            if self.reacquire_failures:
                self.reacquire_failures -= 1
                raise OSError("temporary redis outage")
            return True

    class FakeClient:
        def __init__(self):
            self.values: dict[str, bytes] = {}
            self.next_lock = FakeLock()
            self.last_lock_args = None

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value):
            self.values[key] = bytes(value)

        def delete(self, key):
            self.values.pop(key, None)

        def scan_iter(self, *, match):
            prefix = match.removesuffix("*")
            return [key.encode("utf-8") for key in self.values if key.startswith(prefix)]

        def lock(self, key, *, timeout, blocking_timeout, thread_local):
            self.last_lock_args = (key, timeout, blocking_timeout, thread_local)
            return self.next_lock

    client = FakeClient()

    class FakeRedis:
        @staticmethod
        def from_url(url):
            assert url == "redis://state.test/0"
            return client

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=FakeRedis))
    monkeypatch.setattr(state_store_module, "_REDIS_LOCK_RENEW_INTERVAL_S", 0.005)
    store = RedisStateStore("redis://state.test/0", ":test-prefix:")

    assert store.read_bytes("missing") is None
    store.write_bytes("jobs/one", b"1")
    store.write_bytes("jobs/two", b"2")
    assert store.read_bytes("jobs/one") == b"1"
    assert store.list_keys("jobs/") == ["jobs/one", "jobs/two"]
    with store.lock("jobs"):
        assert store.read_bytes("jobs/two") == b"2"
        deadline = time.monotonic() + 1
        while client.next_lock.reacquired < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
    assert client.last_lock_args == ("test-prefix:locks:jobs", 30.0, 5, False)
    assert client.next_lock.reacquired >= 1
    assert client.next_lock.released is True

    client.next_lock = FakeLock(reacquire_failures=1)
    with (
        pytest.raises(OSError, match="temporary redis outage"),
        store.lock("guarded-write"),
    ):
        store.write_bytes("jobs/guarded", b"must-not-write")
    assert store.read_bytes("jobs/guarded") is None
    assert client.next_lock.released is True

    client.next_lock = FakeLock(reacquire_failures=1)
    with store.lock("flaky-renewal"):
        deadline = time.monotonic() + 1
        while client.next_lock.reacquired < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
    assert client.next_lock.reacquired >= 2
    assert client.next_lock.released is True

    store.delete("jobs/one")
    assert store.read_bytes("jobs/one") is None

    client.next_lock = FakeLock(acquired=False)
    with (
        pytest.raises(TimeoutError, match="timed out acquiring state lock"),
        store.lock("busy"),
    ):
        raise AssertionError("lock body must not run")


@pytest.mark.asyncio
async def test_stateless_rejects_dynamic_stdio_mcp(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    manager = DynamicMCPManager(get_settings().state_dir)

    with pytest.raises(ValueError, match="stdio dynamic MCP servers are unavailable"):
        await manager.manage(
            action="register",
            name="local-process",
            transport="stdio",
            command="python3",
            refresh=False,
        )


def test_stateless_oauth_code_uses_state_backend(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch, oauth_admin_pin="correct-pin")
    oauth_module._CLIENTS.clear()
    oauth_module._CODES.clear()
    app = Starlette(
        routes=[
            Route("/oauth/register", oauth_module.oauth_register, methods=["POST"]),
            Route("/oauth/authorize", oauth_module.oauth_authorize_post, methods=["POST"]),
            Route("/oauth/token", oauth_module.oauth_token, methods=["POST"]),
        ]
    )
    client = TestClient(app, base_url="https://controller.test")
    redirect = "https://client.test/callback"
    registered = client.post(
        "/oauth/register",
        json={"client_name": "serverless test", "redirect_uris": [redirect]},
    )
    client_id = registered.json()["client_id"]
    verifier = "serverless-verifier"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    authorized = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "pin": "correct-pin",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlsplit(authorized.headers["location"]).query)["code"][0]
    assert get_state_store().read_bytes(oauth_module.OAUTH_CODE_STORE_FILE_NAME) is not None

    oauth_module._CODES.clear()
    token = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_verifier": verifier,
        },
    )

    assert token.status_code == 200
    assert token.json()["token_type"] == "Bearer"


def test_shared_oauth_client_reads_reload_non_file_backend(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    oauth_module._CLIENTS.clear()
    oauth_module._LOADED_CLIENT_STORE_SIGNATURE = None
    store = get_state_store()

    def write_clients(*client_ids: str) -> None:
        rows = {
            client_id: {
                "redirect_uris": [f"https://{client_id}.test/callback"],
                "client_name": client_id,
                "created_at": 1,
                "approved": True,
            }
            for client_id in client_ids
        }
        store.write_bytes(
            oauth_module.OAUTH_CLIENT_STORE_FILE_NAME,
            json.dumps({"version": 1, "clients": rows}).encode(),
        )

    write_clients("first")
    assert oauth_module._get_client("first") is not None

    write_clients("first", "second")
    assert oauth_module._get_client("second") is not None


@pytest.mark.asyncio
async def test_memory_stateless_remote_identity_is_invalid_after_cold_start(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    first = remote_module.RemoteManager()
    invite = await first.create_invite(name="worker-a", workdir="/srv/work")

    clear_memory_state()
    second = remote_module.RemoteManager()
    with pytest.raises(ValueError, match="invalid invite code"):
        await second.register_worker(
            {
                "invite": invite["code"],
                "name": "worker-a",
                "workdir": "/srv/work",
            }
        )

    invite = await second.create_invite(name="worker-a", workdir="/srv/work")
    registered = await second.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
            "capabilities": ["transfer_stat"],
            "info": {"hostname": "worker-a"},
        }
    )
    assert registered["token"].startswith("lsmcp_wk_")

    clear_memory_state()
    third = remote_module.RemoteManager()
    with pytest.raises(PermissionError, match="invalid worker identity"):
        await third.resume_worker(
            registered["token"],
            {
                "name": "worker-a",
                "workdir": "/srv/work",
            },
        )
    assert not get_settings().state_dir.exists()


@pytest.mark.asyncio
async def test_shared_state_remote_invite_survives_manager_restart(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    first = remote_module.RemoteManager()
    invite = await first.create_invite(name="worker-a", workdir="/srv/work")

    second = remote_module.RemoteManager()
    registered = await second.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
        }
    )

    assert registered["token"].startswith("lsmcp_wk_")
    third = remote_module.RemoteManager()
    resumed = await third.resume_worker(registered["token"], {"name": "worker-a"})
    assert resumed["name"] == "worker-a"


@pytest.mark.asyncio
async def test_shared_state_warm_manager_refreshes_invite_before_registration(
    tmp_path, monkeypatch
):
    _configure_stateless(tmp_path, monkeypatch)
    creator = remote_module.RemoteManager()
    warm = remote_module.RemoteManager()
    assert warm.list_machines()["machines"] == []

    invite = await creator.create_invite(name="worker-a", workdir="/srv/work")
    registered = await warm.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
        }
    )

    assert registered["token"].startswith("lsmcp_wk_")


@pytest.mark.asyncio
async def test_shared_state_invite_is_consumed_once_across_warm_managers(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    first = remote_module.RemoteManager()
    invite = await first.create_invite(name="worker-a", workdir="/srv/work")
    second = remote_module.RemoteManager()
    second.list_machines()

    registered = await first.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
        }
    )
    with pytest.raises(ValueError, match="invalid invite code"):
        await second.register_worker(
            {
                "invite": invite["code"],
                "name": "worker-b",
                "workdir": "/srv/work",
            }
        )

    reloaded = remote_module.RemoteManager()
    resumed = await reloaded.resume_worker(registered["token"], {"name": "worker-a"})
    assert resumed["name"] == "worker-a"


@pytest.mark.asyncio
async def test_remote_registration_rolls_back_on_registry_commit_failure(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    manager = remote_module.RemoteManager()
    invite = await manager.create_invite(name="worker-a", workdir="/srv/work")

    def fail_save():
        raise OSError("state unavailable")

    monkeypatch.setattr(manager, "_save_registry_unlocked", fail_save)
    with pytest.raises(OSError, match="state unavailable"):
        await manager.register_worker(
            {
                "invite": invite["code"],
                "name": "worker-a",
                "workdir": "/srv/work",
            }
        )

    assert invite["code"] in manager.invites
    assert manager.invites[invite["code"]].used is False
    assert "worker-a" not in manager.workers
    assert manager.tokens == {}


@pytest.mark.asyncio
async def test_remote_registry_backup_failure_does_not_undo_primary_commit(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    store = get_state_store()
    original_write = store.write_bytes

    def fail_secondary_writes(key: str, value: bytes) -> None:
        if key in {remote_module.REMOTE_WORKER_REGISTRY_BACKUP_FILE_NAME, "audit.jsonl"}:
            raise OSError("secondary storage unavailable")
        original_write(key, value)

    monkeypatch.setattr(store, "write_bytes", fail_secondary_writes)
    manager = remote_module.RemoteManager()
    invite = await manager.create_invite(name="worker-a", workdir="/srv/work")
    registered = await manager.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
        }
    )

    monkeypatch.setattr(store, "write_bytes", original_write)
    reloaded = remote_module.RemoteManager()
    resumed = await reloaded.resume_worker(registered["token"], {"name": "worker-a"})
    assert resumed["name"] == "worker-a"


@pytest.mark.asyncio
async def test_remote_registry_rejects_stale_backup_after_partial_save(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    store = get_state_store()
    manager = remote_module.RemoteManager()
    invite = await manager.create_invite(name="worker-a", workdir="/srv/work")
    registered = await manager.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
        }
    )
    original_write = store.write_bytes

    def fail_backup(key: str, value: bytes) -> None:
        if key == remote_module.REMOTE_WORKER_REGISTRY_BACKUP_FILE_NAME:
            raise OSError("backup unavailable")
        original_write(key, value)

    monkeypatch.setattr(store, "write_bytes", fail_backup)
    manager.revoke("worker-a")
    monkeypatch.setattr(store, "write_bytes", original_write)
    original_write(remote_module.REMOTE_WORKER_REGISTRY_FILE_NAME, b"{corrupt")

    reloaded = remote_module.RemoteManager()
    with pytest.raises(RuntimeError, match="no valid backup"):
        await reloaded.resume_worker(registered["token"], {"name": "worker-a"})


@pytest.mark.asyncio
async def test_remote_registry_restores_generation_after_primary_write_failure(
    tmp_path, monkeypatch
):
    _configure_stateless(tmp_path, monkeypatch)
    store = get_state_store()
    manager = remote_module.RemoteManager()
    invite = await manager.create_invite(name="worker-a", workdir="/srv/work")
    previous_generation = store.read_bytes(
        remote_module.REMOTE_WORKER_REGISTRY_GENERATION_FILE_NAME
    )
    previous_backup = store.read_bytes(remote_module.REMOTE_WORKER_REGISTRY_BACKUP_FILE_NAME)
    assert previous_generation is not None
    assert previous_backup is not None
    original_write = store.write_bytes

    def fail_primary(key: str, value: bytes) -> None:
        if key == remote_module.REMOTE_WORKER_REGISTRY_FILE_NAME:
            raise OSError("primary unavailable")
        original_write(key, value)

    monkeypatch.setattr(store, "write_bytes", fail_primary)
    with pytest.raises(OSError, match="primary unavailable"):
        await manager.create_invite(name="worker-b", workdir="/srv/work")

    assert (
        store.read_bytes(remote_module.REMOTE_WORKER_REGISTRY_GENERATION_FILE_NAME)
        == previous_generation
    )
    monkeypatch.setattr(store, "write_bytes", original_write)
    original_write(remote_module.REMOTE_WORKER_REGISTRY_FILE_NAME, b"{corrupt")

    reloaded = remote_module.RemoteManager()
    registered = await reloaded.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
        }
    )
    assert registered["token"].startswith("lsmcp_wk_")


@pytest.mark.asyncio
async def test_remote_registry_malformed_invite_uses_valid_backup(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    store = get_state_store()
    manager = remote_module.RemoteManager()
    invite = await manager.create_invite(name="worker-a", workdir="/srv/work")
    raw = store.read_bytes(remote_module.REMOTE_WORKER_REGISTRY_FILE_NAME)
    assert raw is not None
    registry = json.loads(raw)
    registry["invites"][0]["expires_at"] = "not-a-number"
    store.write_bytes(
        remote_module.REMOTE_WORKER_REGISTRY_FILE_NAME,
        json.dumps(registry).encode("utf-8"),
    )

    reloaded = remote_module.RemoteManager()
    registered = await reloaded.register_worker(
        {
            "invite": invite["code"],
            "name": "worker-a",
            "workdir": "/srv/work",
        }
    )
    assert registered["token"].startswith("lsmcp_wk_")


@pytest.mark.asyncio
async def test_stateless_managed_job_and_audit_stay_off_disk(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    kind = f"serverless-test-{tmp_path.name}"

    async def handler(context: jobs_module.ManagedJobContext, payload: dict[str, Any]):
        await context.log("working")
        await context.update_progress(phase="done")
        return {"value": payload["value"]}

    jobs_module.register_managed_job_handler(kind, handler)
    job = await jobs_module.start_managed_job(kind, {"value": 7})
    for _ in range(100):
        await asyncio.sleep(0.01)
        rows = await jobs_module.list_jobs()
        current = next(row for row in rows["jobs"] if row["job_id"] == job["job_id"])
        if current["status"] != "running":
            break

    tail = await jobs_module.tail_job(job["job_id"])
    audit_module.audit("serverless_test", value=7)
    audit_rows = audit_module.query_audit(search="serverless_test")

    assert current["status"] == "succeeded"
    assert current["result"] == {"value": 7}
    assert "working" in tail["output"]
    assert audit_rows["count"] >= 1
    assert get_state_store().read_bytes("jobs.json") is not None
    assert get_state_store().read_bytes("audit.jsonl") is not None
    assert not get_settings().state_dir.exists()

    stopped = await jobs_module.stop_job(job["job_id"])
    assert stopped["killed"] is False


def test_state_backed_audit_tail_and_retention_include_external_payloads(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch, max_audit_log_bytes="8000")
    large_value = "".join(hashlib.sha256(str(index).encode()).hexdigest() for index in range(1200))

    audit_module.audit("serverless_large_audit", payload=large_value)

    store = get_state_store()
    audit_bytes = len(store.read_bytes("audit.jsonl") or b"")
    payload_bytes = sum(len(store.read_bytes(key) or b"") for key in store.list_keys("audit-payloads/"))
    assert audit_bytes + payload_bytes <= get_settings().max_audit_log_bytes

    tail = tools._read_audit_tail_entries(10)
    assert any(entry.get("event") == "serverless_large_audit" for entry in tail["entries"])
    assert not get_settings().audit_log_path.exists()


@pytest.mark.asyncio
async def test_remote_only_job_controls_reject_local_shell_jobs(tmp_path, monkeypatch):
    _configure_stateless(tmp_path, monkeypatch)
    local_job = {
        "job_id": "local-shell-job",
        "kind": "shell",
        "status": "failed",
        "created_at": 1.0,
    }
    with jobs_module._store_transaction() as store:
        store["jobs"].append(local_job)

    for operation in (
        lambda: jobs_module.tail_job("local-shell-job"),
        lambda: jobs_module.stop_job("local-shell-job"),
        lambda: jobs_module.retry_job("local-shell-job"),
    ):
        with pytest.raises(ValueError, match="local shell jobs are unavailable"):
            await operation()



@pytest.mark.asyncio
async def test_direct_remote_transfer_bypasses_controller_data_path(tmp_path, monkeypatch):
    root = _configure_workspace(
        tmp_path,
        monkeypatch,
        remote_transfer_strategy="direct",
        remote_peer_transfer_enabled="true",
        remote_peer_transfer_bind_host="127.0.0.1",
        remote_peer_transfer_advertise_host="127.0.0.1",
    )
    source = root / "source.bin"
    destination = root / "destination.bin"
    payload = bytes(range(256)) * 64
    source.write_bytes(payload)
    calls: list[tuple[str, str]] = []

    async def transfer(machine: str, tool: str, args: dict[str, Any], timeout_s=None):
        del timeout_s
        calls.append((machine, tool))
        if tool == "transfer_stat":
            return transfer_stat(args["path"], args.get("sha256", True))
        if tool == "transfer_open_receiver":
            return open_peer_receiver(
                path=args["path"],
                overwrite=args.get("overwrite", True),
                expected_bytes=args["expected_bytes"],
                expected_sha256=args["expected_sha256"],
                bind_host=args["bind_host"],
                advertise_host=args["advertise_host"],
                port=args["port"],
                timeout_s=args["timeout_s"],
            )
        if tool == "transfer_put_url":
            return remote_module._worker_put_url(
                args["path"],
                args["url"],
                args["expected_bytes"],
                args["expected_sha256"],
                args.get("timeout_s"),
            )
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    result = await tools._copy_remote_file_to_remote(
        "source-worker", "source.bin", "destination-worker", "destination.bin", True
    )

    assert result["transport"] == "peer-direct"
    assert destination.read_bytes() == payload
    assert ("destination-worker", "transfer_open_receiver") in calls
    assert ("source-worker", "transfer_put_url") in calls
    assert all(tool not in {"transfer_read_chunk", "transfer_write_chunk"} for _, tool in calls)


def test_peer_receiver_rejects_invalid_requests_and_can_be_cancelled(tmp_path, monkeypatch):
    root = _configure_workspace(tmp_path, monkeypatch)
    destination = root / "destination.bin"
    good = b"expected-payload"
    digest = hashlib.sha256(good).hexdigest()

    with pytest.raises(ValueError, match="expected_bytes"):
        open_peer_receiver(
            path="negative.bin",
            overwrite=True,
            expected_bytes=-1,
            expected_sha256=digest,
            bind_host="127.0.0.1",
        )
    with pytest.raises(ValueError, match="SHA-256"):
        open_peer_receiver(
            path="bad-digest.bin",
            overwrite=True,
            expected_bytes=1,
            expected_sha256="bad",
            bind_host="127.0.0.1",
        )

    receiver = open_peer_receiver(
        path="destination.bin",
        overwrite=True,
        expected_bytes=len(good),
        expected_sha256=digest,
        bind_host="127.0.0.1",
        advertise_host="127.0.0.1",
        timeout_s=30,
    )
    parsed = urlsplit(receiver["url"])
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    connection.request("PUT", parsed.path, body=b"short")
    response = connection.getresponse()
    body = response.read()
    assert response.status == 400
    assert b"size_mismatch" in body

    connection.request("PUT", parsed.path, body=b"x" * len(good))
    response = connection.getresponse()
    body = response.read()
    connection.close()

    assert response.status == 400
    assert b"sha256 mismatch" in body
    assert not destination.exists()

    cancellable = open_peer_receiver(
        path="cancelled.bin",
        overwrite=True,
        expected_bytes=len(good),
        expected_sha256=digest,
        bind_host="127.0.0.1",
        advertise_host="127.0.0.1",
        timeout_s=30,
    )
    parsed = urlsplit(cancellable["url"])
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    connection.request("PUT", "/local-shell-mcp-transfer/not-the-token", body=good)
    response = connection.getresponse()
    response.read()
    connection.close()
    assert response.status == 404
    assert close_peer_receiver(cancellable["receiver_id"])["closed"] is True
    assert close_peer_receiver(cancellable["receiver_id"])["closed"] is False
    assert not (root / "cancelled.bin").exists()


def test_peer_receiver_aborts_write_when_listener_bind_fails(tmp_path, monkeypatch):
    root = _configure_workspace(tmp_path, monkeypatch)
    payload = b"payload"
    digest = hashlib.sha256(payload).hexdigest()
    aborted: list[tuple[str, str]] = []
    original_abort = peer_transfer_module.transfer_abort_write

    def abort(path: str, transfer_id: str):
        aborted.append((path, transfer_id))
        return original_abort(path, transfer_id)

    def fail_bind(*_args, **_kwargs):
        raise OSError("address already in use")

    monkeypatch.setattr(peer_transfer_module, "transfer_abort_write", abort)
    monkeypatch.setattr(peer_transfer_module, "ThreadingHTTPServer", fail_bind)

    with pytest.raises(OSError, match="address already in use"):
        open_peer_receiver(
            path="bind-failure.bin",
            overwrite=True,
            expected_bytes=len(payload),
            expected_sha256=digest,
            bind_host="127.0.0.1",
        )

    assert len(aborted) == 1
    assert aborted[0][0] == "bind-failure.bin"
    assert not (root / "bind-failure.bin").exists()


@pytest.mark.asyncio
async def test_auto_remote_transfer_falls_back_to_memory_relay(tmp_path, monkeypatch):
    _configure_workspace(
        tmp_path,
        monkeypatch,
        remote_transfer_strategy="auto",
        remote_peer_transfer_enabled="true",
        remote_transfer_s3_bucket="transfer-bucket",
    )
    attempts: list[str] = []

    async def direct(*args, **kwargs):
        del args, kwargs
        attempts.append("direct")
        raise RuntimeError("peer unreachable")

    async def object_store(*args, **kwargs):
        del args, kwargs
        attempts.append("object_store")
        raise RuntimeError("storage unavailable")

    async def relay(*args, **kwargs):
        del args, kwargs
        attempts.append("relay")
        return {"transport": "controller-memory-relay"}

    monkeypatch.setattr(tools, "_copy_remote_file_direct", direct)
    monkeypatch.setattr(tools, "_copy_remote_file_via_object_store", object_store)
    monkeypatch.setattr(tools, "_copy_remote_file_via_controller_relay", relay)

    result = await tools._copy_remote_file_to_remote(
        "source-worker", "source.bin", "destination-worker", "destination.bin", True
    )

    assert attempts == ["direct", "object_store", "relay"]
    assert result["transport"] == "controller-memory-relay"
    assert len(result["fallbacks"]) == 2
    assert result["fallbacks"][0].startswith("peer-direct: RuntimeError")
    assert result["fallbacks"][1].startswith("s3-presigned: RuntimeError")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty", "offset", "write"])
async def test_memory_relay_aborts_destination_on_invalid_chunk(tmp_path, monkeypatch, failure):
    _configure_workspace(tmp_path, monkeypatch, remote_transfer_strategy="relay")
    calls: list[str] = []

    async def transfer(machine: str, tool: str, args: dict[str, Any], timeout_s=None):
        del machine, timeout_s
        calls.append(tool)
        if tool == "transfer_stat":
            return {"type": "file", "path": "source.bin", "size": 4, "sha256": "a" * 64}
        if tool == "transfer_begin_write":
            return {"transfer_id": "tx"}
        if tool == "transfer_read_chunk":
            if failure == "empty":
                return {"offset": 0, "bytes": 0, "data_b64": "", "sha256": "b" * 64}
            return {
                "offset": 1 if failure == "offset" else 0,
                "bytes": 4,
                "data_b64": "AAAAAA==",
                "sha256": "b" * 64,
            }
        if tool == "transfer_write_chunk":
            return {"bytes": 3 if failure == "write" else 4}
        if tool == "transfer_abort_write":
            return {"aborted": True, "path": args["path"]}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)

    with pytest.raises(tools.RemoteTransferError):
        await tools._copy_remote_file_to_remote(
            "source-worker", "source.bin", "destination-worker", "destination.bin", True
        )

    assert calls[-1] == "transfer_abort_write"


@pytest.mark.asyncio
async def test_direct_transfer_failure_closes_receiver_and_checks_destination(tmp_path, monkeypatch):
    _configure_workspace(
        tmp_path,
        monkeypatch,
        remote_transfer_strategy="direct",
        remote_peer_transfer_enabled="true",
    )
    calls: list[str] = []

    async def failing_transfer(machine: str, tool: str, args: dict[str, Any], timeout_s=None):
        del machine, args, timeout_s
        calls.append(tool)
        if tool == "transfer_stat":
            return {"type": "file", "path": "source.bin", "size": 4, "sha256": "a" * 64}
        if tool == "transfer_open_receiver":
            return {"receiver_id": "receiver", "url": "http://peer/upload"}
        if tool == "transfer_put_url":
            raise RuntimeError("connect failed")
        if tool == "transfer_close_receiver":
            return {"closed": True}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(tools, "_remote_transfer_data", failing_transfer)
    with pytest.raises(RuntimeError, match="connect failed"):
        await tools._copy_remote_file_to_remote(
            "source-worker", "source.bin", "destination-worker", "destination.bin", True
        )
    assert calls[-1] == "transfer_close_receiver"

    stat_calls = 0

    async def bad_destination(machine: str, tool: str, args: dict[str, Any], timeout_s=None):
        nonlocal stat_calls
        del machine, args, timeout_s
        if tool == "transfer_stat":
            stat_calls += 1
            if stat_calls == 1:
                return {"type": "file", "path": "source.bin", "size": 4, "sha256": "a" * 64}
            return {"type": "file", "path": "destination.bin", "size": 3, "sha256": "c" * 64}
        if tool == "transfer_open_receiver":
            return {"receiver_id": "receiver", "url": "http://peer/upload"}
        if tool == "transfer_put_url":
            return {"bytes": 4}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(tools, "_remote_transfer_data", bad_destination)
    with pytest.raises(tools.RemoteTransferError, match="verification failed"):
        await tools._copy_remote_file_to_remote(
            "source-worker", "source.bin", "destination-worker", "destination.bin", True
        )


@pytest.mark.asyncio
async def test_object_store_validation_and_s3_client_factory(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch, remote_transfer_strategy="object_store")
    with pytest.raises(RuntimeError, match="remote_transfer_s3_bucket"):
        await tools._copy_remote_file_to_remote(
            "source-worker", "source.bin", "destination-worker", "destination.bin", True
        )

    _configure_workspace(
        tmp_path,
        monkeypatch,
        remote_transfer_strategy="object_store",
        remote_transfer_s3_bucket="bucket",
        remote_transfer_s3_region="test-region",
        remote_transfer_s3_endpoint_url="https://s3.test",
    )

    async def directory_stat(machine: str, tool: str, args: dict[str, Any], timeout_s=None):
        del machine, args, timeout_s
        assert tool == "transfer_stat"
        return {"type": "dir", "path": "source", "size": 0, "sha256": None}

    monkeypatch.setattr(tools, "_remote_transfer_data", directory_stat)
    with pytest.raises(ValueError, match="source is not a file"):
        await tools._copy_remote_file_to_remote(
            "source-worker", "source", "destination-worker", "destination.bin", True
        )

    seen: dict[str, Any] = {}

    def client(service, **kwargs):
        seen.update(service=service, **kwargs)
        return "s3-client"

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))
    assert tools._s3_transfer_client() == "s3-client"
    assert seen == {
        "service": "s3",
        "region_name": "test-region",
        "endpoint_url": "https://s3.test",
    }


def test_worker_external_transfer_url_and_source_validation(tmp_path, monkeypatch):
    root = _configure_workspace(tmp_path, monkeypatch)
    source = root / "source.bin"
    source.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()

    with pytest.raises(ValueError, match="too long"):
        remote_module._worker_validate_external_transfer_url("https://x.test/" + "a" * 20_000)
    with pytest.raises(ValueError, match="absolute HTTP"):
        remote_module._worker_validate_external_transfer_url("ftp://x.test/file")
    with pytest.raises(ValueError, match="size mismatch"):
        remote_module._worker_put_url("source.bin", "https://x.test/file", 99, digest)
    with pytest.raises(ValueError, match="sha256 mismatch"):
        remote_module._worker_put_url("source.bin", "https://x.test/file", 7, "0" * 64)
    with pytest.raises(ValueError, match="source is not a file"):
        remote_module._worker_put_url(".", "https://x.test/file", 0, digest)


@pytest.mark.asyncio
async def test_object_store_transfer_uses_presigned_urls_and_deletes_object(tmp_path, monkeypatch):
    _configure_workspace(
        tmp_path,
        monkeypatch,
        remote_transfer_strategy="object_store",
        remote_transfer_s3_bucket="transfer-bucket",
        remote_transfer_s3_prefix="lsm-test",
    )
    content = b"object-store-transfer"
    digest = hashlib.sha256(content).hexdigest()
    events: list[str] = []

    class FakeS3:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, str]] = []
            self.presigned: list[tuple[str, str]] = []

        def generate_presigned_url(self, operation, *, Params, ExpiresIn, HttpMethod):
            del ExpiresIn
            self.presigned.append((operation, HttpMethod))
            events.append(f"presign:{operation}")
            return f"https://storage.test/{Params['Bucket']}/{Params['Key']}?op={operation}"

        def delete_object(self, *, Bucket, Key):
            self.deleted.append((Bucket, Key))
            events.append("delete")

    fake_s3 = FakeS3()
    monkeypatch.setattr(tools, "_s3_transfer_client", lambda: fake_s3)
    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def transfer(machine: str, tool: str, args: dict[str, Any], timeout_s=None):
        del timeout_s
        calls.append((machine, tool, args))
        if tool == "transfer_stat":
            return {"type": "file", "path": "source.bin", "size": len(content), "sha256": digest}
        if tool == "transfer_put_url":
            assert args["url"].startswith("https://storage.test/")
            events.append("upload")
            return {"bytes": len(content), "sha256": digest}
        if tool == "transfer_get_url":
            assert args["url"].startswith("https://storage.test/")
            events.append("download")
            return {"path": "destination.bin", "bytes": len(content), "sha256": digest}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    result = await tools._copy_remote_file_to_remote(
        "source-worker", "source.bin", "destination-worker", "destination.bin", True
    )

    assert result["transport"] == "s3-presigned"
    assert fake_s3.presigned == [("put_object", "PUT"), ("get_object", "GET")]
    assert len(fake_s3.deleted) == 1
    assert fake_s3.deleted[0][0] == "transfer-bucket"
    assert [tool for _, tool, _ in calls] == ["transfer_stat", "transfer_put_url", "transfer_get_url"]
    assert events == [
        "presign:put_object",
        "upload",
        "presign:get_object",
        "download",
        "delete",
    ]


@pytest.mark.asyncio
async def test_object_store_cleanup_failure_retries_and_is_reported(tmp_path, monkeypatch):
    _configure_workspace(
        tmp_path,
        monkeypatch,
        remote_transfer_strategy="object_store",
        remote_transfer_s3_bucket="transfer-bucket",
    )
    content = b"object-store-transfer"
    digest = hashlib.sha256(content).hexdigest()

    class FakeS3:
        def __init__(self) -> None:
            self.delete_attempts = 0

        def generate_presigned_url(self, operation, *, Params, ExpiresIn, HttpMethod):
            del ExpiresIn, HttpMethod
            return f"https://storage.test/{Params['Bucket']}/{Params['Key']}?op={operation}"

        def delete_object(self, *, Bucket, Key):
            del Bucket, Key
            self.delete_attempts += 1
            raise OSError("cleanup failed")

    fake_s3 = FakeS3()
    monkeypatch.setattr(tools, "_s3_transfer_client", lambda: fake_s3)

    async def transfer(machine: str, tool: str, args: dict[str, Any], timeout_s=None):
        del machine, timeout_s
        if tool == "transfer_stat":
            return {"type": "file", "path": "source.bin", "size": len(content), "sha256": digest}
        if tool == "transfer_put_url":
            return {"bytes": len(content), "sha256": digest}
        if tool == "transfer_get_url":
            return {"path": args["path"], "bytes": len(content), "sha256": digest}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    result = await tools._copy_remote_file_to_remote(
        "source-worker", "source.bin", "destination-worker", "destination.bin", True
    )

    assert result["transport"] == "s3-presigned"
    assert result["cleanup_error"] == "OSError: cleanup failed"
    assert fake_s3.delete_attempts == 3
    rows = audit_module.query_audit(search="remote_transfer_object_cleanup_failed")
    assert rows["count"] >= 1
