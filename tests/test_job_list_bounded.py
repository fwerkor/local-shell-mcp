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
