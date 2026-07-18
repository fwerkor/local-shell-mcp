from __future__ import annotations

from collections import namedtuple
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.testclient import TestClient

import local_shell_mcp.human_ui as ui
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_WALLPAPER", "none")
    get_settings.cache_clear()


def test_linux_dashboard_readers_parse_proc_files(monkeypatch):
    samples = {
        "/proc/stat": "cpu  100 5 25 200 10 0 0 0 0 0\n",
        "/proc/meminfo": "MemTotal: 1000 kB\nMemAvailable: 400 kB\n",
        "/proc/net/dev": (
            "Inter-| Receive | Transmit\n"
            " face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
            "    lo: 500 0 0 0 0 0 0 0 500 0 0 0 0 0 0 0\n"
            "  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n"
        ),
    }

    def read_text(path, *args, **kwargs):  # noqa: ANN001, ARG001
        return samples[str(path)]

    monkeypatch.setattr(ui.Path, "read_text", read_text)

    assert ui._read_linux_cpu_times() == (340, 210)
    assert ui._read_linux_memory() == (1_024_000, 614_400)
    assert ui._read_linux_network() == (1000, 2000)
    assert ui._percent(25, 100) == 25.0
    assert ui._percent(1, 0) is None


def test_local_dashboard_snapshot_calculates_rates_and_percentages(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "_CPU_SAMPLE", None)
    monkeypatch.setattr(ui, "_NETWORK_SAMPLE", None)
    cpu = iter([(1000, 200), (1200, 250)])
    network = iter([(100, 50), (300, 150)])
    monotonic = iter([10.0, 12.0])
    monkeypatch.setattr(ui, "_read_linux_cpu_times", lambda: next(cpu))
    monkeypatch.setattr(ui, "_read_linux_memory", lambda: (1000, 500))
    monkeypatch.setattr(ui, "_read_linux_network", lambda: next(network))
    monkeypatch.setattr(ui.os, "getloadavg", lambda: (2.0, 1.0, 0.5))
    monkeypatch.setattr(ui.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(ui.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(ui.Path, "read_text", lambda *args, **kwargs: "123.4 0")
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(ui.shutil, "disk_usage", lambda path: DiskUsage(1000, 600, 400))
    monkeypatch.setattr(ui, "get_settings", lambda: SimpleNamespace(workspace_root=tmp_path))

    first = ui._local_system_snapshot()
    second = ui._local_system_snapshot()

    assert first["cpu_percent"] == 50.0
    assert second["cpu_percent"] == 75.0
    assert second["memory_percent"] == 50.0
    assert second["disk_percent"] == 60.0
    assert second["network_rx_bps"] == 100.0
    assert second["network_tx_bps"] == 50.0
    assert second["uptime_s"] == 123


def test_dashboard_helpers_build_alerts_and_activity(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "get_settings", lambda: SimpleNamespace(workspace_root=tmp_path))
    alerts = ui._dashboard_alerts(
        [
            {"name": "local", "status": "online", "info": {}},
            {"name": "old-node", "status": "online", "info": {"version": "3.0.1"}},
            {"name": "off-node", "status": "offline", "last_seen_age_s": 120, "info": {}},
        ],
        {"disk_percent": 96},
        [{"name": "seed-run", "status": "failed", "updated_at": ui.time.time(), "error": "OOM"}],
        [{"ok": False, "status": "failed"}],
        "3.0.4",
    )
    titles = {alert["title"] for alert in alerts}
    assert "old-node uses LSM 3.0.1" in titles
    assert "off-node is offline" in titles
    assert "Workspace disk is 96% full" in titles
    assert "Job seed-run failed" in titles
    assert "1 recent MCP call failure(s)" in titles

    activity = ui._dashboard_activity(
        [
            {"ts": 3, "node": "a", "tool": "read_file", "ok": True},
            {"ts": 2, "node": "b", "tool": "run_shell", "ok": False},
            {"ts": 1, "node": "c", "tool": "job_start", "paired": False},
        ]
    )
    assert [item["kind"] for item in activity] == ["success", "failed", "running"]


def test_dashboard_api_returns_macro_snapshot(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ui,
        "_machine_rows",
        lambda: {
            "machines": [
                {"name": "local", "status": "online", "info": {"local": True}},
                {"name": "remote-a", "status": "offline", "last_seen_age_s": 90, "info": {}},
            ],
            "counts": {"online": 1, "offline": 1, "total": 2},
        },
    )
    monkeypatch.setattr(
        ui,
        "_local_system_snapshot",
        lambda: {
            "timestamp": 1000,
            "cpu_percent": 25,
            "cpu_count": 8,
            "memory_percent": 50,
            "disk_percent": 40,
            "load_1m": 1.2,
            "network_rx_bps": 100,
            "network_tx_bps": 50,
            "uptime_s": 3600,
        },
    )
    monkeypatch.setattr(
        ui,
        "todo_read",
        lambda: {
            "revision": 1,
            "todos": [
                {"id": "a", "status": "pending"},
                {"id": "b", "status": "completed"},
            ],
        },
    )

    async def fake_shells():
        return {
            "sessions": [
                {"session_id": "job-session", "backend": "tmux"},
                {"session_id": "manual", "backend": "tmux"},
            ]
        }

    async def fake_jobs(include_finished=True):  # noqa: ARG001
        return {
            "jobs": [
                {
                    "job_id": "job-1",
                    "name": "experiment",
                    "status": "running",
                    "session_id": "job-session",
                    "created_at": 900,
                },
                {"job_id": "job-2", "name": "done", "status": "completed"},
            ],
            "counts": {"running": 1, "completed": 1},
        }

    monkeypatch.setattr(ui, "list_shells", fake_shells)
    monkeypatch.setattr(ui, "list_jobs", fake_jobs)
    monkeypatch.setattr(
        ui,
        "query_audit",
        lambda **kwargs: {
            "entries": [
                {"ts": 950, "node": "local", "tool": "read_file", "ok": True, "operation": "files"},
                {"ts": 940, "node": "local", "tool": "run_shell", "ok": False, "operation": "shell"},
            ],
            "count": 2,
            "total_matched": 2,
        },
    )
    monkeypatch.setattr(
        ui,
        "version_info",
        lambda: {"version": "3.0.4", "package_version": "3.0.4", "python": "3.12", "platform": "test"},
    )

    response = TestClient(Starlette(routes=ui.ui_routes())).get("/api/ui/dashboard")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["health"] == "attention"
    assert payload["machines"]["counts"]["total"] == 2
    assert [job["job_id"] for job in payload["jobs"]] == ["job-1"]
    assert [session["session_id"] for session in payload["sessions"]] == ["manual"]
    assert payload["session_count"] == 2
    assert payload["todo_counts"] == {"total": 2, "open": 1}
    assert payload["audit_total_24h"] == 2
    assert any(alert["title"] == "remote-a is offline" for alert in payload["alerts"])
    assert any("MCP call failure" in alert["title"] for alert in payload["alerts"])
    assert [entry["kind"] for entry in payload["activity"]] == ["success", "failed"]


def test_dashboard_api_degrades_when_optional_sources_fail(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(ui, "_machine_rows", lambda: {"machines": [{"name": "local", "status": "online", "info": {}}], "counts": {"online": 1, "offline": 0, "total": 1}})
    monkeypatch.setattr(ui, "_local_system_snapshot", lambda: {"timestamp": 1, "disk_percent": 1})
    monkeypatch.setattr(ui, "todo_read", lambda: {"revision": 0, "todos": []})

    async def broken(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("optional source unavailable")

    monkeypatch.setattr(ui, "list_shells", broken)
    monkeypatch.setattr(ui, "list_jobs", broken)
    monkeypatch.setattr(ui, "query_audit", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("audit")))

    response = TestClient(Starlette(routes=ui.ui_routes())).get("/api/ui/dashboard")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["health"] == "attention"
    assert payload["jobs"] == []
    assert payload["sessions"] == []
    assert payload["activity"] == []
    assert {alert["title"] for alert in payload["alerts"]} == {
        "Persistent sessions unavailable",
        "Tracked jobs unavailable",
        "Audit activity unavailable",
    }
