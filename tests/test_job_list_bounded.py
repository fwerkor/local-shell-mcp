import json

import pytest

import local_shell_mcp.jobs as jobs
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_job_list_paginates_under_byte_cap_and_job_get_preserves_details(
    tmp_path, monkeypatch
):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()

    command = "打印" * 6_000
    progress = {"debug": "x" * 5_000}
    result = {"payload": "y" * 5_000}
    rows = [
        {
            "job_id": f"job-{index:03}",
            "name": "任务" * 2_000,
            "kind": "managed",
            "status": "succeeded",
            "command": command,
            "cwd": "/" + "路径" * 3_000,
            "created_at": float(index),
            "updated_at": float(index),
            "error": "error" * 2_000,
            "progress": progress,
            "result": result,
        }
        for index in range(90)
    ]
    (state_dir / jobs.JOB_STORE_FILE_NAME).write_text(
        json.dumps({"version": jobs.JOB_STORE_VERSION, "jobs": rows}), encoding="utf-8"
    )

    async def no_sessions():
        return {"sessions": []}

    monkeypatch.setattr(jobs, "list_shells", no_sessions)
    offset = 0
    seen = []
    page_count = 0
    while True:
        page = await jobs.list_jobs(limit=1000, offset=offset)
        assert len(json.dumps(page, ensure_ascii=True).encode()) <= jobs.JOB_LIST_MAX_RESPONSE_BYTES
        assert page["offset"] == offset
        assert page["total"] == 90
        assert page["counts"] == {"succeeded": 90}
        assert 0 < page["returned"] <= 90
        for row in page["jobs"]:
            assert "result" not in row
            assert "progress" not in row
            assert "error" not in row
            assert row["command_truncated"] is True
            assert len(row["command"].encode()) <= 192
            assert len(row["name"].encode()) <= 160
            assert len(row["cwd"].encode()) <= 256
        seen.extend(row["job_id"] for row in page["jobs"])
        page_count += 1
        if page["next_offset"] is None:
            assert page["truncated"] is False
            break
        assert page["truncated"] is True
        assert page["next_offset"] == offset + page["returned"]
        offset = page["next_offset"]

    assert page_count > 1
    assert seen == [f"job-{index:03}" for index in range(89, -1, -1)]
    full = (await jobs.get_job(seen[0]))["job"]
    assert full["command"] == command
    assert full["progress"] == progress
    assert full["result"] == result
    assert full["error"] == "error" * 2_000

    after_last = await jobs.list_jobs(limit=10, offset=10_000)
    assert after_last["jobs"] == []
    assert after_last["next_offset"] is None
    assert after_last["truncated"] is False
    assert (await jobs.list_jobs(include_finished=False))["jobs"] == []


@pytest.mark.asyncio
async def test_job_get_rejects_unknown_job_and_no_local_shell_access(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
    get_settings.cache_clear()
    (state_dir / jobs.JOB_STORE_FILE_NAME).write_text(
        json.dumps(
            {
                "version": jobs.JOB_STORE_VERSION,
                "jobs": [
                    {"job_id": "hidden", "kind": "shell", "status": "succeeded"},
                    {"job_id": "managed", "kind": "managed", "status": "succeeded"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert [row["job_id"] for row in (await jobs.list_jobs())["jobs"]] == ["managed"]
    assert (await jobs.get_job("managed"))["job"]["kind"] == "managed"
    with pytest.raises(ValueError, match="local shell jobs are unavailable"):
        await jobs.get_job("hidden")
    with pytest.raises(KeyError, match="job not found"):
        await jobs.get_job("missing")


@pytest.mark.asyncio
async def test_job_list_preserves_bounded_alerts_with_surrogate_escaped_text(tmp_path, monkeypatch):
    import time

    from local_shell_mcp.human_ui import _dashboard_alerts

    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "false")
    get_settings.cache_clear()

    now = time.time()
    details = [
        {
            "job_id": "failed-with-surrogate",
            "kind": "shell",
            "name": "worker-\udcff" * 90,
            "status": "failed",
            "command": "printf '\udcfe'" * 120,
            "cwd": "/tmp/bad-\udcff-path" * 100,
            "session_id": "session-\udcff",
            "backend": "tmux-\udcff",
            "error": "OOM: allocation failed, invalid path \udcff; " + "日志" * 1_000,
            "created_at": now,
            "updated_at": now,
        },
        {
            "job_id": "lost-with-surrogate",
            "status": "lost",
            "command": "echo \udcff",
            "error": "completion receipt missing \udcfe",
            "created_at": now - 1,
            "updated_at": now,
        },
        {
            "job_id": "succeeded-with-surrogate",
            "status": "succeeded",
            "command": "echo \udcff",
            "cwd": "\udcff",
            "created_at": now - 2,
            "updated_at": now,
        },
    ]
    (state_dir / jobs.JOB_STORE_FILE_NAME).write_text(
        json.dumps({"version": jobs.JOB_STORE_VERSION, "jobs": details}), encoding="utf-8"
    )

    async def no_sessions():
        return {"sessions": []}

    monkeypatch.setattr(jobs, "list_shells", no_sessions)
    page = await jobs.list_jobs(limit=1000)
    assert page["returned"] == 3
    assert len(json.dumps(page, ensure_ascii=True).encode()) <= jobs.JOB_LIST_MAX_RESPONSE_BYTES
    # No unpaired surrogate may escape into an ordinary UTF-8 JSON client.
    json.dumps(page, ensure_ascii=False).encode("utf-8")

    failed, lost, succeeded = page["jobs"]
    assert failed["job_id"] == "failed-with-surrogate"
    assert failed["command_truncated"] is True
    assert failed["error"].startswith("OOM: allocation failed")
    assert failed["error"].endswith("…")
    assert len(failed["error"].encode("utf-8")) <= 256
    assert len(failed["name"].encode("utf-8")) <= 160
    assert len(failed["cwd"].encode("utf-8")) <= 256
    assert "?" in failed["command"]
    assert lost["error"] == "completion receipt missing ?"
    assert succeeded["command"] == "echo ?"
    assert succeeded["command_truncated"] is False
    assert "error" not in succeeded

    alerts = _dashboard_alerts([], {}, page["jobs"], [], "test")
    assert (
        next(item for item in alerts if item["title"].endswith("failed"))["detail"]
        == failed["error"]
    )
    assert (
        next(item for item in alerts if item["title"].endswith("lost"))["detail"] == lost["error"]
    )
    assert (await jobs.get_job("failed-with-surrogate"))["job"]["error"] == details[0]["error"]


@pytest.mark.asyncio
async def test_job_list_dashboard_failures_are_independent_of_active_first_page(
    tmp_path, monkeypatch
):
    import time

    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "false")
    get_settings.cache_clear()

    now = time.time()
    active = [
        {
            "job_id": f"active-{i}",
            "kind": "shell",
            "status": "running",
            "session_id": f"session-{i}",
            "command": "run",
            "created_at": now - i,
            "updated_at": now,
        }
        for i in range(40)
    ]
    failures = [
        {
            "job_id": f"failed-{i}",
            "status": "lost" if i == 1 else "failed",
            "command": "run",
            "error": "OOM " + "错误" * 1_000,
            "created_at": now - 100_000 - i,
            "updated_at": now - i * 10 if i != 3 else now - 90_000,
        }
        for i in range(4)
    ]
    (state_dir / jobs.JOB_STORE_FILE_NAME).write_text(
        json.dumps({"version": jobs.JOB_STORE_VERSION, "jobs": [*active, *failures]}),
        encoding="utf-8",
    )

    async def active_sessions():
        return {"sessions": [{"session_id": row["session_id"]} for row in active]}

    monkeypatch.setattr(jobs, "list_shells", active_sessions)
    default_page = await jobs.list_jobs()
    assert default_page["returned"] == 25
    assert default_page["counts"]["failed"] == 3
    assert default_page["counts"]["lost"] == 1
    assert all(row["status"] == "running" for row in default_page["jobs"])
    assert "recent_failures" not in default_page

    dashboard_page = await jobs.list_jobs(include_recent_failures=True)
    assert [row["job_id"] for row in dashboard_page["recent_failures"]] == [
        "failed-0",
        "failed-1",
        "failed-2",
    ]
    assert all(
        len(row["error"].encode("utf-8")) <= 256 for row in dashboard_page["recent_failures"]
    )
    assert (
        len(json.dumps(dashboard_page, ensure_ascii=True).encode())
        <= jobs.JOB_LIST_MAX_RESPONSE_BYTES
    )
    assert dashboard_page["next_offset"] is not None

    last_page = await jobs.list_jobs(offset=10_000, include_recent_failures=True)
    assert last_page["jobs"] == []
    assert len(last_page["recent_failures"]) == 3

    from local_shell_mcp.remote import _execute_job_worker_tool

    remote_page = await _execute_job_worker_tool(
        "job_list", {"limit": 1, "include_recent_failures": True}
    )
    assert [row["job_id"] for row in remote_page["recent_failures"]] == [
        "failed-0", "failed-1", "failed-2"
    ]
