from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from local_shell_mcp import remote
from local_shell_mcp.settings import get_settings


@pytest.fixture
def isolated_remote(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATELESS_CONTROLLER", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invite_defaults_bounds_and_validation(isolated_remote):
    manager = remote.RemoteManager()
    default = await manager.create_invite()
    assert default["ttl_s"] == 7200
    assert default["max_uses"] == 1
    assert default["used_count"] == 0
    assert (await manager.create_invite(ttl_s=999999))["ttl_s"] == 604800
    assert (await manager.create_invite(ttl_s=1))["ttl_s"] == 60
    for invalid in (0, -1, 1.5, "3", True, None):
        with pytest.raises(ValueError, match="max_uses"):
            await manager.create_invite(max_uses=invalid)
    with pytest.raises(ValueError, match="name must be omitted"):
        await manager.create_invite(name="fixed", max_uses=2)


@pytest.mark.asyncio
async def test_multiple_registrations_survive_restart_and_consume_exact_quota(isolated_remote):
    first = remote.RemoteManager()
    invite = await first.create_invite(max_uses=3, workdir="/workspace")
    code = invite["code"]
    names = []
    tokens = []
    for index in range(3):
        manager = remote.RemoteManager()
        enrolled = await manager.register_worker(
            {
                "invite": code,
                "info": {"user": "alice", "hostname": "shared-host"},
            }
        )
        names.append(enrolled["name"])
        tokens.append(enrolled["token"])
        assert manager.workers[enrolled["name"]].workdir == "/workspace"
        if index < 2:
            assert manager.invites[code].used_count == index + 1
            assert manager.invites[code].max_uses == 3
        else:
            assert code not in manager.invites
    assert names == ["alice@shared-host", "alice@shared-host-2", "alice@shared-host-3"]
    assert len(set(tokens)) == 3
    with pytest.raises(ValueError, match="invalid invite"):
        await first.register_worker({"invite": code, "name": "fourth"})
    assert (await remote.RemoteManager().resume_worker(tokens[0], {"name": names[0]}))[
        "name"
    ] == names[0]


@pytest.mark.asyncio
async def test_duplicate_does_not_consume_quota(isolated_remote):
    manager = remote.RemoteManager()
    code = (await manager.create_invite(max_uses=2))["code"]
    await manager.register_worker({"invite": code, "name": "one"})
    with pytest.raises(ValueError, match="already exists"):
        await manager.register_worker({"invite": code, "name": "one"})
    assert manager.invites[code].used_count == 1
    await manager.register_worker({"invite": code, "name": "two"})
    assert code not in manager.invites


@pytest.mark.asyncio
async def test_last_slot_is_atomic_between_managers(isolated_remote):
    manager_a = remote.RemoteManager()
    code = (await manager_a.create_invite(max_uses=2))["code"]
    await manager_a.register_worker({"invite": code, "name": "first"})
    manager_b = remote.RemoteManager()
    results = await asyncio.gather(
        manager_a.register_worker({"invite": code, "name": "second"}),
        manager_b.register_worker({"invite": code, "name": "third"}),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    fresh = remote.RemoteManager()
    assert len(fresh.list_machines()["machines"]) == 2
    assert code not in fresh.invites


@pytest.mark.asyncio
async def test_failed_registry_write_does_not_consume_slot(isolated_remote, monkeypatch):
    manager = remote.RemoteManager()
    code = (await manager.create_invite(max_uses=2))["code"]
    original = manager._save_registry_unlocked
    monkeypatch.setattr(
        manager, "_save_registry_unlocked", lambda: (_ for _ in ()).throw(OSError("failed"))
    )
    with pytest.raises(OSError, match="failed"):
        await manager.register_worker({"invite": code, "name": "test"})
    monkeypatch.setattr(manager, "_save_registry_unlocked", original)
    fresh = remote.RemoteManager()
    fresh.list_machines()
    assert fresh.invites[code].used_count == 0
    assert fresh.workers == {}
    await fresh.register_worker({"invite": code, "name": "test"})
    assert fresh.invites[code].used_count == 1


@pytest.mark.asyncio
async def test_replayed_registration_returns_original_identity_without_spending_uses(
    isolated_remote,
):
    creator = remote.RemoteManager()
    code = (await creator.create_invite(max_uses=2))["code"]
    payload = {
        "invite": code,
        "enrollment_id": "random-retry-identifier",
        "info": {"user": "a", "hostname": "host"},
    }
    first = await creator.register_worker(payload)
    reloaded = remote.RemoteManager()
    assert await reloaded.register_worker(payload) == first
    assert reloaded.invites[code].used_count == 1
    assert len(reloaded.workers) == 1

    another = {**payload, "enrollment_id": "different-worker-identifier"}
    second = await reloaded.register_worker(another)
    assert second["token"] != first["token"]
    assert second["name"] != first["name"]
    after_quota = remote.RemoteManager()
    assert code not in after_quota.invites
    assert await after_quota.register_worker(payload) == first
    assert await after_quota.register_worker(another) == second
    assert len(after_quota.workers) == 2
    with pytest.raises(ValueError, match="invalid invite"):
        await after_quota.register_worker({**payload, "enrollment_id": "third-worker"})


@pytest.mark.asyncio
async def test_registration_replay_survives_expiry_and_revoke_blocks_identity(
    isolated_remote, monkeypatch
):
    manager = remote.RemoteManager()
    invite = await manager.create_invite(max_uses=2, ttl_s=60)
    payload = {"invite": invite["code"], "name": "first", "enrollment_id": "stable-attempt"}
    registered = await manager.register_worker(payload)
    monkeypatch.setattr(remote, "_utc", lambda: invite["expires_at"] + 1)
    assert (await remote.RemoteManager().register_worker(payload))["token"] == registered["token"]
    fresh = remote.RemoteManager()
    fresh.revoke("first")
    with pytest.raises(ValueError, match="enrollment has been revoked"):
        await remote.RemoteManager().register_worker(payload)


@pytest.mark.asyncio
async def test_registration_enrollment_id_validation(isolated_remote):
    manager = remote.RemoteManager()
    code = (await manager.create_invite(max_uses=2))["code"]
    for invalid in ("", True, 100, "x" * 129):
        with pytest.raises(ValueError, match="enrollment_id"):
            await manager.register_worker({"invite": code, "enrollment_id": invalid})
    assert manager.invites[code].used_count == 0


@pytest.mark.asyncio
async def test_lost_http_response_is_retried_without_duplicate_registration(
    isolated_remote, monkeypatch
):
    manager = remote.RemoteManager()
    invite = await manager.create_invite(max_uses=2)
    request = {"invite": invite["code"], "enrollment_id": "stable-across-network-retries"}
    attempts = []

    def network_post(url, payload, headers, timeout):
        assert url.endswith("/remote/register")
        result = asyncio.run(manager.register_worker(payload))
        attempts.append(result)
        if len(attempts) == 1:
            raise ConnectionError("response lost after server committed")
        return {"ok": True, "data": result}

    monkeypatch.setattr(remote, "_worker_post_json", network_post)
    monkeypatch.setattr(remote, "_worker_retry_delay", lambda attempt: 0)
    returned = await remote._worker_post_json_forever(
        "https://controller.test/remote/register", request, operation="register"
    )
    assert len(attempts) == 2
    assert attempts[0] == attempts[1] == returned["data"]
    assert len(manager.workers) == 1
    assert manager.invites[invite["code"]].used_count == 1


@pytest.mark.asyncio
async def test_revoked_enrollment_cannot_retry_into_available_invite(isolated_remote):
    creator = remote.RemoteManager()
    invite = await creator.create_invite(max_uses=3)
    original = {
        "invite": invite["code"],
        "enrollment_id": "lost-response-from-revoked-worker",
        "info": {"user": "tester", "hostname": "shared-host"},
    }
    registered = await creator.register_worker(original)
    controller = remote.RemoteManager()
    assert controller.revoke(registered["name"])["revoked"]
    key = hashlib.sha256(
        (invite["code"] + "\0" + original["enrollment_id"]).encode()
    ).hexdigest()
    assert controller.revoked_registrations[key] > remote._utc()
    assert registered["name"] not in controller.workers

    # A new controller process must reject the same retry even while unused
    # slots remain. The revoked worker's original token remains unusable.
    after_restart = remote.RemoteManager()
    with pytest.raises(ValueError, match="enrollment has been revoked"):
        await after_restart.register_worker(original)
    with pytest.raises(PermissionError, match="invalid worker identity"):
        await after_restart.resume_worker(registered["token"], {})
    assert after_restart.invites[invite["code"]].used_count == 1
    assert not after_restart.workers

    # The revoke only invalidates this particular enrollment, not the invite.
    another = await after_restart.register_worker(
        {**original, "enrollment_id": "another-device"}
    )
    assert another["token"] != registered["token"]
    assert after_restart.invites[invite["code"]].used_count == 2

    # Rejected retries must not consume that last remaining slot.
    for _ in range(2):
        with pytest.raises(ValueError, match="enrollment has been revoked"):
            await remote.RemoteManager().register_worker(original)
    assert remote.RemoteManager().list_machines()["counts"]["total"] == 1
    final = await remote.RemoteManager().register_worker(
        {**original, "enrollment_id": "third-device"}
    )
    assert final["token"] not in {registered["token"], another["token"]}


@pytest.mark.asyncio
async def test_revoked_enrollment_tombstone_expires_and_is_pruned(isolated_remote, monkeypatch):
    now = remote._utc()
    monkeypatch.setattr(remote, "_utc", lambda: now)
    manager = remote.RemoteManager()
    invite = await manager.create_invite(max_uses=2, ttl_s=604800)
    payload = {"invite": invite["code"], "name": "worker", "enrollment_id": "revoked"}
    await manager.register_worker(payload)
    manager.revoke("worker")
    assert len(manager.revoked_registrations) == 1

    monkeypatch.setattr(remote, "_utc", lambda: now + remote.MAX_REMOTE_INVITE_TTL_S - 1)
    with pytest.raises(ValueError, match="enrollment has been revoked"):
        await remote.RemoteManager().register_worker(payload)

    monkeypatch.setattr(remote, "_utc", lambda: now + remote.MAX_REMOTE_INVITE_TTL_S + 1)
    fresh = remote.RemoteManager()
    fresh.list_machines()
    assert fresh.revoked_registrations == {}
    # The original invite has also expired by now; cleanup cannot re-enable it.
    with pytest.raises(ValueError, match="invalid invite"):
        await fresh.register_worker(payload)
    fresh.flush_registry()
    assert remote.RemoteManager._read_registry(fresh._registry_path())[
        "revoked_registrations"
    ] == {}


@pytest.mark.asyncio
async def test_revoke_registry_write_failure_rolls_back_tombstone(
    isolated_remote, monkeypatch
):
    manager = remote.RemoteManager()
    code = (await manager.create_invite(max_uses=2))["code"]
    worker = await manager.register_worker(
        {"invite": code, "name": "rollback", "enrollment_id": "retry"}
    )
    original_save = manager._save_registry_unlocked

    def fail_save():
        raise OSError("simulated registry write failure")

    monkeypatch.setattr(manager, "_save_registry_unlocked", fail_save)
    with pytest.raises(OSError, match="simulated registry"):
        manager.revoke("rollback")
    assert "rollback" in manager.workers
    assert manager.tokens[worker["token"]] == "rollback"
    assert manager.revoked_registrations == {}
    monkeypatch.setattr(manager, "_save_registry_unlocked", original_save)

    after_restart = remote.RemoteManager()
    assert (
        await after_restart.register_worker(
            {"invite": code, "name": "rollback", "enrollment_id": "retry"}
        )
    ) == worker


@pytest.mark.parametrize(
    "revoked",
    [
        [],
        {"short-hash": 123},
        {"a" * 64: "tomorrow"},
        {"a" * 64: float("nan")},
        {"a" * 64: True},
        {"a" * 64: -1},
    ],
)
def test_registry_rejects_invalid_revoked_enrollment_records(revoked):
    raw = json.dumps({
        "version": 1,
        "workers": [],
        "invites": [],
        "revoked_registrations": revoked,
    }).encode()
    with pytest.raises(ValueError, match="revoked registrations"):
        remote.RemoteManager._read_registry(raw)

    # Backwards-compatible v1 registries do not have tombstone fields.
    old_registry = remote.RemoteManager._read_registry(
        b'{"version":1,"workers":[],"invites":[]}'
    )
    assert old_registry["revoked_registrations"] == {}


@pytest.mark.asyncio
async def test_http_retry_after_revocation_does_not_resurrect_worker(
    isolated_remote, monkeypatch
):
    manager = remote.RemoteManager()
    invite = await manager.create_invite(max_uses=2)
    payload = {
        "invite": invite["code"],
        "enrollment_id": "revoke-between-network-attempts",
    }
    attempts = 0

    def network_post(url, request, headers, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            registered = asyncio.run(manager.register_worker(request))
            remote.RemoteManager().revoke(registered["name"])
            raise ConnectionError("registration response lost")
        result = asyncio.run(remote.RemoteManager().register_worker(request))
        return {"ok": True, "data": result}

    monkeypatch.setattr(remote, "_worker_post_json", network_post)
    monkeypatch.setattr(remote, "_worker_retry_delay", lambda attempt: 0)
    with pytest.raises(ValueError, match="enrollment has been revoked"):
        await remote._worker_post_json_forever(
            "https://controller.test/remote/register", payload, operation="register"
        )
    assert attempts == 2
    fresh = remote.RemoteManager()
    fresh.list_machines()
    assert not fresh.workers
    assert fresh.invites[invite["code"]].used_count == 1
