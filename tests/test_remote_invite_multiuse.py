from __future__ import annotations

import asyncio

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
