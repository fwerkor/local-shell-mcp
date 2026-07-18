from local_shell_mcp import __version__
from local_shell_mcp.remote import RemoteManager, RemoteWorker, worker_info
from local_shell_mcp.settings import get_settings


def test_list_machines_reports_counts_and_details(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    manager = RemoteManager()
    now = 1_000_000.0
    monkeypatch.setattr("local_shell_mcp.remote._utc", lambda: now)

    recent = RemoteWorker(name="recent-worker", token="recent", last_seen=now - 5)
    stale = RemoteWorker(name="stale-worker", token="stale", last_seen=now - 500)
    manager.workers = {recent.name: recent, stale.name: stale}
    manager.tokens = {recent.token: recent.name, stale.token: stale.name}
    recent.queue.put_nowait({"id": "job-1"})

    result = manager.list_machines()

    assert result["counts"] == {"online": 1, "offline": 1, "total": 2}
    assert [machine["name"] for machine in result["machines"]] == ["recent-worker", "stale-worker"]
    assert result["machines"][0]["status"] == "online"
    assert result["machines"][0]["last_seen_age_s"] == 5
    assert result["machines"][0]["queue_depth"] == 1
    assert result["machines"][1]["status"] == "offline"


def test_worker_info_reports_runtime_version(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "local_shell_mcp.remote.persistent_shell_backend_info", lambda: {"backend": "test"}
    )

    info = worker_info(str(tmp_path))

    assert info["lsm_version"] == __version__


def test_list_machines_serializes_concurrent_registry_mutations(tmp_path, monkeypatch):
    import threading
    import time

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    first_yield = threading.Event()
    continue_iteration = threading.Event()
    writer_done = threading.Event()
    errors = []

    class CoordinatedDict(dict):
        def values(self):
            iterator = iter(super().values())
            first = next(iterator)
            yield first
            first_yield.set()
            assert continue_iteration.wait(2)
            yield from iterator

    manager = RemoteManager()
    manager._registry_loaded = True
    workers = {
        "worker-a": RemoteWorker(name="worker-a", token="token-a"),
        "worker-b": RemoteWorker(name="worker-b", token="token-b"),
    }
    manager.workers = CoordinatedDict(workers)
    manager.tokens = {worker.token: worker.name for worker in workers.values()}

    def read_registry():
        try:
            manager.list_machines()
        except Exception as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    def rename_worker():
        try:
            manager.rename("worker-b", "worker-c")
        except Exception as exc:  # pragma: no cover - asserted below.
            errors.append(exc)
        finally:
            writer_done.set()

    reader = threading.Thread(target=read_registry)
    writer = threading.Thread(target=rename_worker)
    reader.start()
    assert first_yield.wait(2)
    writer.start()
    time.sleep(0.05)
    assert not writer_done.is_set()
    continue_iteration.set()
    reader.join(2)
    writer.join(2)

    assert not errors
    assert writer_done.is_set()
    assert [row["name"] for row in manager.list_machines()["machines"]] == [
        "worker-a",
        "worker-c",
    ]
