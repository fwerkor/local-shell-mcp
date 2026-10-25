from __future__ import annotations

import asyncio
import base64

import pytest

from local_shell_mcp import hosted_chat
from local_shell_mcp import hosted_chat_store as module
from local_shell_mcp.hosted_chat_store import (
    HostedChatRunner,
    HostedChatStore,
    _close_unknown_tool_calls,
    _encryption_key,
)
from local_shell_mcp.settings import get_settings
from local_shell_mcp.state_store import get_state_store


@pytest.fixture(autouse=True)
def state_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def store(monkeypatch):
    instance = HostedChatStore(prefix="hosted-chat-edge")
    monkeypatch.setattr(module, "hosted_chat_store", instance)
    return instance


def profile_values(**changes):
    return {
        "name": "Test profile",
        "model": "unit-model",
        "endpoint": "https://example.org/v1",
        "api_key": "test-secret",
        **changes,
    }


def test_encryption_key_requires_stable_secret_when_state_not_file(monkeypatch, tmp_path):
    key = _encryption_key()
    assert len(key) == 32
    assert _encryption_key() == key
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"a" * 32).decode()
    )
    assert _encryption_key() == b"a" * 32
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"short").decode()
    )
    with pytest.raises(ValueError, match="32 bytes"):
        _encryption_key()
    monkeypatch.delenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY")
    (tmp_path / "state" / "hosted-chat-encryption-key").write_bytes(b"short")
    with pytest.raises(RuntimeError, match="Invalid Hosted Chat encryption key"):
        _encryption_key()
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "memory")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="non-file state storage"):
        _encryption_key()


def test_store_validates_profile_keys_and_identifiers(store):
    with pytest.raises(PermissionError, match="principal"):
        store.profiles("")
    for value in ("../escape", "", "x" * 71, "ümlaut", "unsafe/path"):
        with pytest.raises(ValueError, match="identifier"):
            store.profile("alice", value)
    for values in (
        profile_values(name=" "),
        profile_values(model=""),
        profile_values(name="n" * 121),
        profile_values(api_key="z" * 8193),
    ):
        with pytest.raises(ValueError):
            store.put_profile("alice", values)
    public = store.put_profile("alice", profile_values())
    pid = public["id"]
    assert public["has_key"]
    assert "api_key" not in store.profile("alice", pid)
    with pytest.raises(ValueError, match="Unknown"):
        store.profile("bob", pid)
    updated = store.put_profile("alice", profile_values(id=pid, name="Updated", api_key=""))
    assert updated["name"] == "Updated"
    assert store.profile("alice", pid, with_secret=True)["api_key"] == "test-secret"
    assert store.put_profile("alice", profile_values(name="No key", api_key=""))["has_key"] is False
    store.delete_profile("alice", pid)
    with pytest.raises(ValueError, match="Unknown"):
        store.delete_profile("alice", pid)


def test_store_conversation_lifecycle_and_records_filter(store):
    pid = store.put_profile("alice", profile_values())["id"]
    with pytest.raises(ValueError):
        store.create_conversation("bob", profile_id=pid)
    record = store.create_conversation("alice", profile_id=pid, title="X" * 250)
    assert len(record["title"]) == 180
    assert store.conversations("alice")[0]["id"] == record["id"]
    store.update_conversation("alice", record["id"], updater=lambda r: {**r, "events": ["event"]})
    assert "events" not in store.conversations("alice")[0]
    key = store._key("alice", "conversations", record["id"])
    assert store._read(key)["events"] == ["event"]
    prefix = f"{store.prefix}/{module._owner_key('alice')}/conversations/"
    get_state_store().write_bytes(prefix + "ignored.txt", b"ignored")
    assert len(store.conversations("alice")) == 1
    store.update_conversation("alice", record["id"], updater=lambda r: {**r, "status": "running"})
    with pytest.raises(ValueError, match="Stop the active"):
        store.delete_conversation("alice", record["id"])
    store.update_conversation("alice", record["id"], updater=lambda r: {**r, "status": "idle"})
    store.delete_conversation("alice", record["id"])
    with pytest.raises(ValueError, match="Unknown"):
        store.delete_conversation("alice", record["id"])


def test_unknown_tool_result_records_are_closed_without_replay():
    messages = [
        {"role": "assistant", "tool_calls": [None, {"id": "pending"}, {"id": "done"}]},
        {"role": "tool", "tool_call_id": "done", "content": "ok"},
    ]
    _close_unknown_tool_calls(messages)
    assert len(messages) == 3
    assert messages[-1]["tool_call_id"] == "pending"
    assert "Do not automatically repeat" in messages[-1]["content"]
    _close_unknown_tool_calls(messages)
    assert len(messages) == 3


@pytest.mark.asyncio
async def test_runner_handles_failed_turn_and_restart_reconciliation(store, monkeypatch):
    profile_id = store.put_profile("alice", profile_values())["id"]
    record = store.create_conversation("alice", profile_id=profile_id)
    runner = HostedChatRunner()
    monkeypatch.setattr(module, "hosted_chat_runner", runner)

    async def fail_turn(**_):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(hosted_chat, "complete_turn", fail_turn)
    for bad in ("", " " * 2, "x" * 40001):
        with pytest.raises(ValueError, match="Message must contain"):
            await runner.start("alice", record["id"], bad, "http://localhost", "")
    await runner.start("alice", record["id"], "failure test", "http://localhost", "")
    await asyncio.sleep(0.1)
    state = store.conversation("alice", record["id"])
    assert state["status"] == "failed"
    assert state["error"] == "RuntimeError: Hosted Chat turn failed"
    with pytest.raises(ValueError, match="No active"):
        runner.stop("alice", record["id"])
    store.update_conversation("alice", record["id"], updater=lambda r: {**r, "status": "running"})
    with pytest.raises(ValueError, match="interrupted turn"):
        await runner.start("alice", record["id"], "retry", "http://localhost", "")
    assert runner.reconcile("alice", record["id"])["status"] == "interrupted"
    assert runner.reconcile("alice", record["id"])["status"] == "interrupted"


@pytest.mark.asyncio
async def test_runner_rejects_duplicate_turn_and_can_cancel(store, monkeypatch):
    profile_id = store.put_profile("alice", profile_values())["id"]
    record = store.create_conversation("alice", profile_id=profile_id)
    runner = HostedChatRunner()
    monkeypatch.setattr(module, "hosted_chat_runner", runner)
    started = asyncio.Event()

    async def suspended_turn(**_):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(hosted_chat, "complete_turn", suspended_turn)
    await runner.start("alice", record["id"], "start", "http://localhost", "")
    await asyncio.wait_for(started.wait(), 2)
    assert runner.reconcile("alice", record["id"])["status"] == "running"
    with pytest.raises(ValueError, match="already running"):
        await runner.start("alice", record["id"], "duplicate", "http://localhost", "")
    loop = asyncio.get_running_loop()
    was_debug = loop.get_debug()
    loop.set_debug(True)
    try:
        await asyncio.to_thread(runner.stop, "alice", record["id"])
        await asyncio.sleep(0.15)
    finally:
        loop.set_debug(was_debug)
    assert store.conversation("alice", record["id"])["status"] == "interrupted"
    with pytest.raises(ValueError, match="No active"):
        runner.stop("alice", record["id"])


@pytest.mark.asyncio
async def test_replica_preserves_foreign_run_and_fences_stale_owner(store, monkeypatch):
    import time

    profile_id = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=profile_id)
    first_started, second_started = asyncio.Event(), asyncio.Event()
    first_release, second_release = asyncio.Event(), asyncio.Event()
    lost_ownership = []

    async def fake_turn(*, messages, checkpoint, **_):
        if messages[-1]["content"] == "first":
            first_started.set()
            await first_release.wait()
            try:
                await checkpoint([*messages, {"role": "assistant", "content": "old writer"}], [])
            except ValueError as exc:
                lost_ownership.append(str(exc))
        else:
            second_started.set()
            await second_release.wait()
            await checkpoint([*messages, {"role": "assistant", "content": "new writer"}], [])

    monkeypatch.setattr(hosted_chat, "complete_turn", fake_turn)
    replica_a, replica_b = HostedChatRunner(), HostedChatRunner()
    await replica_a.start("alice", chat["id"], "first", "http://controller", "")
    await asyncio.wait_for(first_started.wait(), 2)
    assert replica_b.reconcile("alice", chat["id"])["status"] == "running"
    with pytest.raises(ValueError, match="interrupted turn"):
        await replica_b.start("alice", chat["id"], "second", "http://controller", "")

    store.update_conversation(
        "alice", chat["id"], updater=lambda r: {**r, "lease_until": time.time() - 1}
    )
    assert replica_b.reconcile("alice", chat["id"])["status"] == "interrupted"
    await replica_b.start("alice", chat["id"], "second", "http://controller", "")
    await asyncio.wait_for(second_started.wait(), 2)
    first_release.set()
    await asyncio.sleep(0.1)
    assert lost_ownership and "ownership" in lost_ownership[0]
    assert store.conversation("alice", chat["id"])["status"] == "running"
    second_release.set()
    await asyncio.sleep(0.15)
    result = store.conversation("alice", chat["id"])
    assert result["status"] == "idle"
    assert result["messages"][-1]["content"] == "new writer"


@pytest.mark.asyncio
async def test_runner_renews_durable_lease_while_model_waits(store, monkeypatch):
    profile_id = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=profile_id)
    monkeypatch.setattr(module, "RUN_HEARTBEAT_SECONDS", 0.04)
    monkeypatch.setattr(module, "RUN_LEASE_SECONDS", 0.5)
    started = asyncio.Event()

    async def fake_turn(**_):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(hosted_chat, "complete_turn", fake_turn)
    runner = HostedChatRunner()
    record = await runner.start("alice", chat["id"], "wait", "http://controller", "")
    await asyncio.wait_for(started.wait(), 2)
    initial = record["lease_until"]
    await asyncio.sleep(0.16)
    assert store.conversation("alice", chat["id"])["lease_until"] > initial
    runner.stop("alice", chat["id"])
    await asyncio.sleep(0.1)
    assert store.conversation("alice", chat["id"])["status"] == "interrupted"


@pytest.mark.asyncio
async def test_remote_replica_can_request_stop_using_durable_state(store, monkeypatch):
    profile_id = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=profile_id)
    monkeypatch.setattr(module, "RUN_HEARTBEAT_SECONDS", 0.03)
    started = asyncio.Event()

    async def running_turn(**_):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(hosted_chat, "complete_turn", running_turn)
    owner, observer = HostedChatRunner(), HostedChatRunner()
    await owner.start("alice", chat["id"], "test", "http://controller", "")
    await asyncio.wait_for(started.wait(), 2)
    observer.stop("alice", chat["id"])
    assert store.conversation("alice", chat["id"])["cancel_requested"] is True
    for _ in range(30):
        if store.conversation("alice", chat["id"])["status"] == "interrupted":
            break
        await asyncio.sleep(0.02)
    assert store.conversation("alice", chat["id"])["status"] == "interrupted"


def test_encryption_key_concurrent_initialization_is_atomic():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=12) as executor:
        keys = list(executor.map(lambda _: _encryption_key(), range(24)))
    assert len(set(keys)) == 1
    assert len(keys[0]) == 32


@pytest.mark.asyncio
async def test_runner_lease_recovers_after_transient_store_error(store, monkeypatch):
    profile_id = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=profile_id)
    monkeypatch.setattr(module, "RUN_HEARTBEAT_SECONDS", 0.03)
    monkeypatch.setattr(module, "RUN_LEASE_SECONDS", 0.4)
    started = asyncio.Event()

    async def suspended_turn(**_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(hosted_chat, "complete_turn", suspended_turn)
    original = store.update_conversation
    calls = 0

    def flaky_update(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError("temporary backend outage")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "update_conversation", flaky_update)
    runner = HostedChatRunner()
    record = await runner.start("alice", chat["id"], "wait", "http://controller", "")
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.sleep(0.15)
    assert calls >= 3
    assert store.conversation("alice", chat["id"])["lease_until"] > record["lease_until"]
    runner.stop("alice", chat["id"])
    await asyncio.sleep(0.1)
    assert store.conversation("alice", chat["id"])["status"] == "interrupted"


@pytest.mark.asyncio
async def test_transport_exception_does_not_persist_authorization_header(store, monkeypatch):
    import httpx

    secret = "sk-sensitive-secret"
    profile_id = store.put_profile("alice", profile_values(api_key=secret))["id"]
    chat = store.create_conversation("alice", profile_id=profile_id)

    async def fail_turn(**_):
        raise httpx.LocalProtocolError(f"Illegal header value b'Bearer {secret}\\n'")

    monkeypatch.setattr(hosted_chat, "complete_turn", fail_turn)
    runner = HostedChatRunner()
    await runner.start("alice", chat["id"], "go", "http://controller", "")
    for _ in range(100):
        record = store.conversation("alice", chat["id"])
        if record["status"] == "failed":
            break
        await asyncio.sleep(0.01)
    assert record["status"] == "failed"
    assert secret not in str(record)
    assert record["error"] == "LocalProtocolError: Hosted Chat turn failed"


@pytest.mark.parametrize("api_key", ["secret\n", "line\rbreak", "bad\tkey", "bad key", "café", "x" * 8193])
def test_profile_rejects_invalid_authorization_key(store, api_key):
    with pytest.raises(ValueError, match="API key"):
        store.put_profile("alice", profile_values(api_key=api_key))
    assert store.profiles("alice") == []


def test_archived_conversation_zstd_round_trip_and_principal_isolation(store):
    from local_shell_mcp.audit_archive_codec import decompress_bytes

    pid = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=pid, title="Long research conversation")
    messages = [{"role": "user", "content": "repeat " * 2000}]
    store.update_conversation(
        "alice", chat["id"], updater=lambda r: {**r, "messages": messages, "events": [{"name": "tool"}]}
    )
    original = store.conversation("alice", chat["id"])
    archived = store.archive_conversation("alice", chat["id"])
    assert archived["archived_at"] > 0
    assert store.conversations("alice") == []
    assert store.archived_conversations("alice")[0]["title"] == "Long research conversation"
    assert "messages" not in store.archived_conversations("alice")[0]
    assert store.archived_conversation("alice", chat["id"])["messages"] == messages
    with pytest.raises(ValueError, match="Archived"):
        store.conversation("alice", chat["id"])
    with pytest.raises(ValueError, match="Archived"):
        store.update_conversation("alice", chat["id"], updater=lambda record: record)
    assert store.archived_conversations("bob") == []
    with pytest.raises(ValueError):
        store.archived_conversation("bob", chat["id"])
    packed = get_state_store().read_bytes(store._archive_key("alice", chat["id"]))
    assert packed.startswith(b"\x28\xb5\x2f\xfd")
    assert len(packed) < len(decompress_bytes(packed))
    assert get_state_store().read_bytes(store._key("alice", "conversations", chat["id"])) is None
    # The separate archive retains the entire original record across instances.
    reloaded = HostedChatStore(prefix=store.prefix)
    assert reloaded.archived_conversation("alice", chat["id"])["events"] == [{"name": "tool"}]
    restored = reloaded.restore_conversation("alice", chat["id"])
    assert restored == original
    assert reloaded.archived_conversations("alice") == []
    assert reloaded.conversations("alice")[0]["id"] == chat["id"]
    assert reloaded.conversation("alice", chat["id"])["messages"] == messages


def test_archiving_running_chat_and_double_archive_are_rejected(store):
    pid = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=pid)
    store.update_conversation("alice", chat["id"], updater=lambda r: {**r, "status": "running"})
    with pytest.raises(ValueError, match="Stop"):
        store.archive_conversation("alice", chat["id"])
    assert store.archived_conversations("alice") == []
    store.update_conversation("alice", chat["id"], updater=lambda r: {**r, "status": "interrupted"})
    store.archive_conversation("alice", chat["id"])
    with pytest.raises(ValueError, match="already archived"):
        store.archive_conversation("alice", chat["id"])
    store.delete_archived_conversation("alice", chat["id"])
    assert store.archived_conversations("alice") == []
    assert store.conversations("alice") == []
    with pytest.raises(ValueError, match="Unknown"):
        store.delete_archived_conversation("alice", chat["id"])


def test_archive_write_failure_preserves_original_and_orphans_recoverable(store, monkeypatch):
    pid = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=pid)
    backend = get_state_store()
    original_write = backend.write_bytes
    original_delete = backend.delete

    def fail_archive_write(key, data):
        if key.endswith(".json.zst"):
            raise OSError("simulated archive storage outage")
        original_write(key, data)

    monkeypatch.setattr(backend, "write_bytes", fail_archive_write)
    with pytest.raises(OSError):
        store.archive_conversation("alice", chat["id"])
    assert store.conversation("alice", chat["id"])["id"] == chat["id"]
    assert store.archived_conversations("alice") == []
    monkeypatch.setattr(backend, "write_bytes", original_write)

    def fail_delete(key):
        if "/conversations/" in key:
            raise OSError("simulated failed cleanup")
        original_delete(key)

    monkeypatch.setattr(backend, "delete", fail_delete)
    with pytest.raises(OSError):
        store.archive_conversation("alice", chat["id"])
    assert store.conversations("alice") == []
    assert store.archived_conversation("alice", chat["id"])["id"] == chat["id"]
    monkeypatch.setattr(backend, "delete", original_delete)
    store.restore_conversation("alice", chat["id"])
    assert len(store.conversations("alice")) == 1
    assert store.archived_conversations("alice") == []


def test_archive_metadata_write_failure_keeps_compressed_record_recoverable(store, monkeypatch):
    pid = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=pid)
    backend = get_state_store()
    original_write = backend.write_bytes

    def fail_metadata_write(key, data):
        if "/archive-metadata/" in key:
            raise OSError("metadata write failure")
        original_write(key, data)

    monkeypatch.setattr(backend, "write_bytes", fail_metadata_write)
    with pytest.raises(OSError):
        store.archive_conversation("alice", chat["id"])
    assert store.archived_conversations("alice")[0]["id"] == chat["id"]
    assert store.conversations("alice") == []
    monkeypatch.setattr(backend, "write_bytes", original_write)
    store.restore_conversation("alice", chat["id"])
    assert store.conversation("alice", chat["id"])["id"] == chat["id"]


@pytest.mark.asyncio
async def test_manual_compact_stores_cursor_without_modifying_original_history(store, monkeypatch):
    from local_shell_mcp import hosted_chat

    pid = store.put_profile("alice", profile_values(context_window=16384))["id"]
    chat = store.create_conversation("alice", profile_id=pid)
    original = [{"role": "user", "content": f"Task {i}"} for i in range(5)]
    store.update_conversation("alice", chat["id"], updater=lambda r: {**r, "messages": original})
    observed = []

    async def compact_history(**kwargs):
        observed.append(kwargs)
        return {"summary": "Task status and paths", "through": 3}

    monkeypatch.setattr(hosted_chat, "compact_history", compact_history)
    result = await store.compact_conversation("alice", chat["id"])
    assert result["messages"] == original
    assert result["context"] == {"summary": "Task status and paths", "through": 3}
    assert observed[0]["context_size"] == 16384
    assert observed[0]["force"] is True
    assert "api_key" not in store.profile("alice", pid)
    loaded = HostedChatStore(prefix=store.prefix).conversation("alice", chat["id"])
    assert loaded["context"] == result["context"]
    assert "context" not in store.conversations("alice")[0]
    # New tokens and model overrides still allow per-profile configuration.
    saved = store.put_profile("alice", profile_values(id=pid, api_key="", context_window=65536))
    assert saved["context_window"] == 65536
    for value in (True, "32768", 8191, 1000001):
        with pytest.raises(ValueError, match="Context window"):
            store.put_profile("alice", profile_values(id=pid, api_key="", context_window=value))


@pytest.mark.asyncio
async def test_manual_compact_rejects_running_or_archived_and_preserves_context_on_error(store, monkeypatch):
    from local_shell_mcp import hosted_chat

    pid = store.put_profile("alice", profile_values())["id"]
    chat = store.create_conversation("alice", profile_id=pid)
    store.update_conversation("alice", chat["id"], updater=lambda r: {**r, "status": "running"})
    with pytest.raises(ValueError, match="Stop"):
        await store.compact_conversation("alice", chat["id"])
    store.update_conversation("alice", chat["id"], updater=lambda r: {**r, "status": "idle"})

    async def fail(**kwargs):
        raise RuntimeError("model provider down")

    monkeypatch.setattr(hosted_chat, "compact_history", fail)
    baseline = store.conversation("alice", chat["id"])
    with pytest.raises(RuntimeError):
        await store.compact_conversation("alice", chat["id"])
    assert store.conversation("alice", chat["id"]) == baseline
    store.archive_conversation("alice", chat["id"])
    with pytest.raises(ValueError, match="Restore"):
        await store.compact_conversation("alice", chat["id"])
