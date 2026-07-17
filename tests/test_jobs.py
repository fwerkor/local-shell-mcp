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


def test_runner_environment_policy_is_shell_neutral_and_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST", "TOKEN_ONE,TOKEN_TWO"
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES", "PRIVATE_,SERVICE_"
    )
    get_settings.cache_clear()

    paths = jobs_module._attempt_paths("job_test", 1)
    argv = jobs_module._runner_argv(paths, tmp_path)
    blocklist_index = argv.index("--env-blocklist-b64") + 1
    prefixes_index = argv.index("--env-blocked-prefixes-b64") + 1
    blocklist_payload = argv[blocklist_index]
    prefixes_payload = argv[prefixes_index]

    assert '"' not in blocklist_payload
    assert "'" not in blocklist_payload
    assert '"' not in prefixes_payload
    assert "'" not in prefixes_payload
    assert jobs_module._parse_runner_env_policy(
        blocklist_payload, "env blocklist"
    ) == ["TOKEN_ONE", "TOKEN_TWO"]
    assert jobs_module._parse_runner_env_policy(
        prefixes_payload, "env blocked prefixes"
    ) == ["PRIVATE_", "SERVICE_"]

    powershell_command = jobs_module._runner_command(argv, "powershell.exe")
    assert blocklist_payload in powershell_command
    assert prefixes_payload in powershell_command


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


@pytest.mark.asyncio
async def test_job_list_recovers_interrupted_stopping_and_retrying_states(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    runtime_dir = state_dir / "jobs"
    runtime_dir.mkdir(parents=True)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    now = time.time()
    rows = [
        {
            "job_id": "job_stop_gone",
            "name": "stop-gone",
            "status": "stopping",
            "command": "sleep 10",
            "cwd": ".",
            "session_id": "gone-session",
            "created_at": now,
            "updated_at": now,
            "attempts": 1,
        },
        {
            "job_id": "job_stop_live",
            "name": "stop-live",
            "status": "stopping",
            "command": "sleep 10",
            "cwd": ".",
            "session_id": "live-session",
            "created_at": now - 1,
            "updated_at": now,
            "attempts": 1,
        },
        {
            "job_id": "job_retry_gone",
            "name": "retry-gone",
            "status": "retrying",
            "command": "true",
            "cwd": ".",
            "session_id": "old-session",
            "created_at": now - 2,
            "updated_at": now,
            "attempts": 1,
            "pending_attempt": 2,
            "pending_session_name": "missing-retry-session",
        },
        {
            "job_id": "job_retry_live",
            "name": "retry-live",
            "status": "retrying",
            "command": "true",
            "cwd": ".",
            "session_id": "old-session-2",
            "created_at": now - 3,
            "updated_at": now,
            "attempts": 1,
            "pending_attempt": 2,
            "pending_session_name": "live-retry-session",
            "pending_command_path": str(runtime_dir / "retry.command"),
            "pending_log_path": str(runtime_dir / "retry.log"),
            "pending_status_path": str(runtime_dir / "retry.status.json"),
        },
    ]
    (state_dir / jobs_module.JOB_STORE_FILE_NAME).write_text(
        json.dumps({"version": jobs_module.JOB_STORE_VERSION, "jobs": rows}),
        encoding="utf-8",
    )

    async def active_shells():
        return {
            "sessions": [
                {"session_id": "live-session"},
                {"session_id": "live-retry-session"},
            ]
        }

    monkeypatch.setattr(jobs_module, "list_shells", active_shells)

    listed = await list_jobs()
    recovered = {job["job_id"]: job for job in listed["jobs"]}

    assert recovered["job_stop_gone"]["status"] == "stopped"
    assert recovered["job_stop_live"]["status"] == "running"
    assert "interrupted stop" in recovered["job_stop_live"]["error"]
    assert recovered["job_retry_gone"]["status"] == "failed"
    assert "retry was interrupted" in recovered["job_retry_gone"]["error"]
    assert recovered["job_retry_live"]["status"] == "running"
    assert recovered["job_retry_live"]["session_id"] == "live-retry-session"
    assert recovered["job_retry_live"]["attempts"] == 2


@pytest.mark.asyncio
async def test_job_store_migrates_v1_without_losing_history(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    legacy_jobs = [
        {
            "job_id": "job_legacy_done",
            "name": "legacy-done",
            "status": "exited",
            "command": "true",
            "cwd": ".",
            "session_id": "legacy-done-session",
            "created_at": 1.0,
            "updated_at": 2.0,
            "attempts": 1,
        },
        {
            "job_id": "job_legacy_live",
            "name": "legacy-live",
            "status": "running",
            "command": "sleep 10",
            "cwd": ".",
            "session_id": "legacy-live-session",
            "created_at": 3.0,
            "updated_at": 3.0,
            "attempts": 1,
        },
    ]
    store_path = state_dir / jobs_module.JOB_STORE_FILE_NAME
    store_path.write_text(
        json.dumps({"version": 1, "jobs": legacy_jobs}), encoding="utf-8"
    )

    async def legacy_shells():
        return {"sessions": [{"session_id": "legacy-live-session"}]}

    monkeypatch.setattr(jobs_module, "list_shells", legacy_shells)
    listed = await list_jobs()

    assert {job["job_id"] for job in listed["jobs"]} == {
        "job_legacy_done",
        "job_legacy_live",
    }
    assert listed["counts"] == {"exited": 1, "running": 1}
    for path in (store_path, state_dir / jobs_module.JOB_STORE_BACKUP_FILE_NAME):
        migrated = json.loads(path.read_text(encoding="utf-8"))
        assert migrated["version"] == jobs_module.JOB_STORE_VERSION
        assert {job["job_id"] for job in migrated["jobs"]} == {
            "job_legacy_done",
            "job_legacy_live",
        }


@pytest.mark.asyncio
async def test_job_start_does_not_launch_shell_when_store_is_invalid(
    tmp_path, monkeypatch
):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    (state_dir / jobs_module.JOB_STORE_FILE_NAME).write_text(
        json.dumps({"version": 99, "jobs": []}), encoding="utf-8"
    )
    started = False

    async def fake_start_shell(cwd=".", name=None, command=None):  # noqa: ARG001
        nonlocal started
        started = True
        return {"session_id": str(name), "backend": "fake"}

    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)

    with pytest.raises(RuntimeError, match="refusing to reset"):
        await start_job("echo must-not-run")

    assert started is False
    runtime_dir = state_dir / "jobs"
    assert not runtime_dir.exists() or not list(runtime_dir.iterdir())


@pytest.mark.asyncio
async def test_job_list_recovers_interrupted_start(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    now = time.time()
    rows = [
        {
            "job_id": "job_start_live",
            "name": "start-live",
            "status": "starting",
            "command": "sleep 10",
            "cwd": ".",
            "session_id": "start-live-session",
            "created_at": now,
            "updated_at": now,
            "attempts": 1,
            "operation_id": "start_stale_live",
            "operation_kind": "start",
        },
        {
            "job_id": "job_start_missing",
            "name": "start-missing",
            "status": "starting",
            "command": "sleep 10",
            "cwd": ".",
            "session_id": "start-missing-session",
            "created_at": now - 1,
            "updated_at": now,
            "attempts": 1,
            "operation_id": "start_stale_missing",
            "operation_kind": "start",
        },
    ]
    (state_dir / jobs_module.JOB_STORE_FILE_NAME).write_text(
        json.dumps({"version": jobs_module.JOB_STORE_VERSION, "jobs": rows}),
        encoding="utf-8",
    )

    async def active_shells():
        return {"sessions": [{"session_id": "start-live-session"}]}

    monkeypatch.setattr(jobs_module, "list_shells", active_shells)
    listed = await list_jobs()
    recovered = {job["job_id"]: job for job in listed["jobs"]}

    assert recovered["job_start_live"]["status"] == "running"
    assert "recovered job start" in recovered["job_start_live"]["error"]
    assert recovered["job_start_missing"]["status"] == "failed"
    assert "start was interrupted" in recovered["job_start_missing"]["error"]
    stored = json.loads(
        (state_dir / jobs_module.JOB_STORE_FILE_NAME).read_text(encoding="utf-8")
    )
    assert all("operation_id" not in job for job in stored["jobs"])


@pytest.mark.asyncio
async def test_job_store_recovers_from_atomic_backup(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    state_dir.mkdir(parents=True)
    row = {
        "job_id": "job_saved",
        "name": "saved",
        "status": "succeeded",
        "command": "true",
        "cwd": ".",
        "created_at": 1.0,
        "updated_at": 2.0,
        "completed_at": 2.0,
        "exit_code": 0,
        "attempts": 1,
    }
    jobs_module._save_store({"version": jobs_module.JOB_STORE_VERSION, "jobs": [row]})
    store_path = state_dir / jobs_module.JOB_STORE_FILE_NAME
    backup_path = state_dir / jobs_module.JOB_STORE_BACKUP_FILE_NAME
    assert backup_path.is_file()
    store_path.write_text("{broken", encoding="utf-8")

    async def no_shells():
        return {"sessions": []}

    monkeypatch.setattr(jobs_module, "list_shells", no_shells)
    listed = await list_jobs()

    assert [job["job_id"] for job in listed["jobs"]] == ["job_saved"]
    assert json.loads(store_path.read_text(encoding="utf-8"))["jobs"][0]["job_id"] == "job_saved"


@pytest.mark.asyncio
async def test_job_store_refuses_to_overwrite_unrecoverable_corruption(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    store_path = state_dir / jobs_module.JOB_STORE_FILE_NAME
    store_path.write_text("{broken", encoding="utf-8")

    async def no_shells():
        return {"sessions": []}

    monkeypatch.setattr(jobs_module, "list_shells", no_shells)

    with pytest.raises(RuntimeError, match="refusing to reset"):
        await list_jobs()
    assert store_path.read_text(encoding="utf-8") == "{broken"
    assert not (state_dir / jobs_module.JOB_STORE_BACKUP_FILE_NAME).exists()


@pytest.mark.asyncio
async def test_job_list_does_not_interrupt_active_start(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    active: set[str] = set()
    start_entered = asyncio.Event()
    allow_start = asyncio.Event()

    async def fake_start_shell(cwd=".", name=None, command=None):
        start_entered.set()
        await allow_start.wait()
        active.add(str(name))
        return {
            "session_id": str(name),
            "cwd": cwd,
            "command": command,
            "backend": "fake",
        }

    async def fake_list_shells():
        return {"sessions": [{"session_id": item} for item in sorted(active)]}

    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)
    monkeypatch.setattr(jobs_module, "list_shells", fake_list_shells)

    start_task = asyncio.create_task(start_job("sleep 10"))
    await start_entered.wait()

    during = await list_jobs()
    assert during["jobs"][0]["status"] == "starting"

    allow_start.set()
    started = await start_task
    assert started["status"] == "running"
    assert (await list_jobs())["jobs"][0]["status"] == "running"


@pytest.mark.asyncio
async def test_job_list_does_not_interrupt_active_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    active = {"session-stop"}
    kill_entered = asyncio.Event()
    allow_kill = asyncio.Event()

    async def fake_start_shell(cwd=".", name=None, command=None):
        return {
            "session_id": "session-stop",
            "cwd": cwd,
            "command": command,
            "backend": "fake",
        }

    async def fake_list_shells():
        return {"sessions": [{"session_id": item} for item in sorted(active)]}

    async def fake_kill_shell(session_id):
        assert session_id == "session-stop"
        kill_entered.set()
        await allow_kill.wait()
        active.discard(session_id)
        return {"session_id": session_id, "killed": True, "stderr": ""}

    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)
    monkeypatch.setattr(jobs_module, "list_shells", fake_list_shells)
    monkeypatch.setattr(jobs_module, "kill_shell", fake_kill_shell)

    job = await start_job("sleep 10")
    stop_task = asyncio.create_task(stop_job(job["job_id"]))
    await kill_entered.wait()

    during = await list_jobs()
    assert during["jobs"][0]["status"] == "stopping"

    allow_kill.set()
    stopped = await stop_task
    assert stopped["job"]["status"] == "stopped"
    assert (await list_jobs())["jobs"][0]["status"] == "stopped"


@pytest.mark.asyncio
async def test_job_list_does_not_interrupt_active_retry(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    now = time.time()
    (state_dir / jobs_module.JOB_STORE_FILE_NAME).write_text(
        json.dumps(
            {
                "version": jobs_module.JOB_STORE_VERSION,
                "jobs": [
                    {
                        "job_id": "job-retry-race",
                        "name": "retry-race",
                        "status": "failed",
                        "command": "echo retry",
                        "cwd": ".",
                        "session_id": "old-session",
                        "created_at": now,
                        "updated_at": now,
                        "completed_at": now,
                        "exit_code": 1,
                        "attempts": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    active: set[str] = set()
    start_entered = asyncio.Event()
    allow_start = asyncio.Event()

    async def fake_list_shells():
        return {"sessions": [{"session_id": item} for item in sorted(active)]}

    async def fake_start_shell(cwd=".", name=None, command=None):
        start_entered.set()
        await allow_start.wait()
        active.add(str(name))
        return {
            "session_id": str(name),
            "cwd": cwd,
            "command": command,
            "backend": "fake",
        }

    monkeypatch.setattr(jobs_module, "list_shells", fake_list_shells)
    monkeypatch.setattr(jobs_module, "start_shell", fake_start_shell)

    retry_task = asyncio.create_task(retry_job("job-retry-race"))
    await start_entered.wait()

    during = await list_jobs()
    assert during["jobs"][0]["status"] == "retrying"

    allow_start.set()
    retried = await retry_task
    assert retried["status"] == "running"
    assert retried["attempts"] == 2
