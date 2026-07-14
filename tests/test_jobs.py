import asyncio
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import local_shell_mcp.jobs as jobs_module
from local_shell_mcp.jobs import list_jobs, retry_job, start_job, stop_job, tail_job
from local_shell_mcp.settings import get_settings


def test_runner_command_invokes_powershell_executable_and_quotes_arguments():
    command = jobs_module._runner_command(
        [
            r"C:\Program Files\Python\python.exe",
            "-m",
            "local_shell_mcp.main",
            "--status-file",
            r"C:\state dir\job's-status.json",
        ],
        "powershell.exe",
    )

    assert command == (
        "& 'C:\\Program Files\\Python\\python.exe' '-m' "
        "'local_shell_mcp.main' '--status-file' "
        "'C:\\state dir\\job''s-status.json'"
    )


@pytest.mark.asyncio
async def test_jobs_track_tail_stop_and_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()

    active_sessions = set()
    outputs = {}

    async def fake_start_shell(cwd=".", name=None, command=None):
        session_id = name or f"session-{len(active_sessions) + 1}"
        active_sessions.add(session_id)
        outputs[session_id] = f"started: {command}"
        return {"session_id": session_id, "cwd": cwd, "command": command, "backend": "fake"}

    async def fake_list_shells():
        return {"sessions": [{"session_id": session_id} for session_id in sorted(active_sessions)]}

    async def fake_read_shell(session_id, lines=200):  # noqa: ARG001
        return {"session_id": session_id, "output": outputs[session_id]}

    async def fake_kill_shell(session_id):
        active_sessions.discard(session_id)
        return {"session_id": session_id, "killed": True, "stderr": ""}

    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)
    monkeypatch.setattr(jobs_module, "list_shells", fake_list_shells)
    monkeypatch.setattr(jobs_module, "read_shell", fake_read_shell)
    monkeypatch.setattr(jobs_module, "kill_shell", fake_kill_shell)

    job = await start_job("python -m http.server", cwd=".", name="server")
    assert job["status"] == "running"
    assert job["attempts"] == 1

    listed = await list_jobs()
    assert listed["counts"] == {"running": 1}
    assert listed["jobs"][0]["job_id"] == job["job_id"]

    tail = await tail_job(job["job_id"], lines=20)
    assert tail["job"]["status"] == "running"
    assert "job-runner" in tail["output"]
    assert tail["job"]["command"] == "python -m http.server"

    stopped = await stop_job(job["job_id"])
    assert stopped["killed"] is True
    assert stopped["job"]["status"] == "stopped"

    retried = await retry_job(job["job_id"])
    assert retried["status"] == "running"
    assert retried["attempts"] == 2
    assert retried["session_id"] != job["session_id"]


@pytest.mark.asyncio
async def test_job_list_marks_missing_running_session_lost(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()

    async def fake_start_shell(cwd=".", name=None, command=None):  # noqa: ARG001
        return {"session_id": "gone", "cwd": cwd, "command": command, "backend": "fake"}

    async def no_shells():
        return {"sessions": []}

    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)
    monkeypatch.setattr(jobs_module, "list_shells", no_shells)

    job = await start_job("printf done")
    assert job["status"] == "running"

    listed = await list_jobs()
    assert listed["counts"] == {"lost": 1}
    assert listed["jobs"][0]["status"] == "lost"
    assert listed["jobs"][0]["exit_code"] is None


@pytest.mark.asyncio
async def test_completed_job_retains_output_and_exit_code(tmp_path, monkeypatch):
    if os.name != "nt" and not shutil.which("tmux"):
        pytest.skip("tmux is required for the Unix persistent shell backend")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()

    job = await start_job("printf 'completed-output\n'; exit 3")
    row = job
    for _ in range(50):
        await asyncio.sleep(0.1)
        row = (await list_jobs())["jobs"][0]
        if row["status"] != "running":
            break

    assert row["status"] == "failed"
    assert row["exit_code"] == 3
    tail = await tail_job(job["job_id"])
    assert tail["output"] == "completed-output\n"
    assert tail["message"] == "job completed with exit code 3"


@pytest.mark.asyncio
async def test_job_log_is_bounded_and_reports_truncation(tmp_path, monkeypatch):
    if os.name != "nt" and not shutil.which("tmux"):
        pytest.skip("tmux is required for the Unix persistent shell backend")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES", "32")
    get_settings.cache_clear()

    job = await start_job("python3 -c \"print('x' * 200)\"")
    row = job
    for _ in range(50):
        await asyncio.sleep(0.1)
        row = (await list_jobs())["jobs"][0]
        if row["status"] != "running":
            break

    assert row["status"] == "succeeded"
    assert row["log_truncated"] is True
    tail = await tail_job(job["job_id"])
    assert len(tail["output"].encode()) <= 32


def test_concurrent_job_starts_preserve_every_record(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()

    sessions: set[str] = set()
    sessions_lock = threading.Lock()

    async def fake_start_shell(cwd=".", name=None, command=None):
        session_id = str(name)
        with sessions_lock:
            sessions.add(session_id)
        return {
            "session_id": session_id,
            "cwd": cwd,
            "command": command,
            "backend": "fake",
        }

    async def fake_list_shells():
        with sessions_lock:
            current = sorted(sessions)
        return {"sessions": [{"session_id": item} for item in current]}

    original_load = jobs_module._load_store

    def slow_load():
        store = original_load()
        time.sleep(0.02)
        return store

    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)
    monkeypatch.setattr(jobs_module, "list_shells", fake_list_shells)
    monkeypatch.setattr(jobs_module, "_load_store", slow_load)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(asyncio.run, start_job(f"printf {index}")) for index in range(8)]
        started = [future.result() for future in futures]

    listed = asyncio.run(list_jobs())
    assert {job["job_id"] for job in listed["jobs"]} == {job["job_id"] for job in started}
    assert listed["counts"] == {"running": 8}


def test_finished_job_history_and_attempt_files_are_bounded(tmp_path, monkeypatch):
    state_dir = tmp_path / ".local-shell-mcp"
    runtime_dir = state_dir / "jobs"
    runtime_dir.mkdir(parents=True)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_JOBS", "2")
    get_settings.cache_clear()

    rows = []
    for index in range(4):
        job_id = f"job_{index}"
        rows.append(
            {
                "job_id": job_id,
                "name": job_id,
                "status": "succeeded",
                "command": "true",
                "cwd": ".",
                "created_at": float(index),
                "updated_at": float(index),
                "attempts": 1,
            }
        )
        for suffix in ("command", "log", "status.json"):
            (runtime_dir / f"{job_id}-attempt-1.{suffix}").write_text("data", encoding="utf-8")
    (state_dir / "jobs.json").write_text(
        json.dumps({"version": jobs_module.JOB_STORE_VERSION, "jobs": rows}),
        encoding="utf-8",
    )

    async def no_shells():
        return {"sessions": []}

    monkeypatch.setattr(jobs_module, "list_shells", no_shells)
    listed = asyncio.run(list_jobs())

    assert [job["job_id"] for job in listed["jobs"]] == ["job_3", "job_2"]
    assert not list(runtime_dir.glob("job_0-attempt-*"))
    assert not list(runtime_dir.glob("job_1-attempt-*"))
    assert list(runtime_dir.glob("job_2-attempt-*"))
    assert list(runtime_dir.glob("job_3-attempt-*"))


@pytest.mark.asyncio
async def test_stop_failure_restores_retryable_job_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    active = {"session-a"}

    async def fake_start_shell(cwd=".", name=None, command=None):
        return {"session_id": "session-a", "cwd": cwd, "command": command, "backend": "fake"}

    async def fake_list_shells():
        return {"sessions": [{"session_id": item} for item in active]}

    async def failing_kill_shell(session_id):
        assert session_id == "session-a"
        raise RuntimeError("kill failed")

    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)
    monkeypatch.setattr(jobs_module, "list_shells", fake_list_shells)
    monkeypatch.setattr(jobs_module, "kill_shell", failing_kill_shell)

    job = await start_job("sleep 10")
    with pytest.raises(RuntimeError, match="kill failed"):
        await stop_job(job["job_id"])

    listed = await list_jobs()
    assert listed["jobs"][0]["status"] == "running"
    assert "stop failed" in listed["jobs"][0]["error"]
