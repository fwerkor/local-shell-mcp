"""Opt-in conversion of timed-out commands to tracked, durable jobs."""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from conftest import python_shell_command

import local_shell_mcp.jobs as jobs
import local_shell_mcp.remote as remote
import local_shell_mcp.tools as tools
from local_shell_mcp.fs_ops import prune_temp_dir, temp_dir
from local_shell_mcp.jobs import retry_job, run_job_with_timeout, tail_job
from local_shell_mcp.settings import get_settings


@pytest.fixture
def isolated_job_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    # The persistent job runner is a separate Python process whose cwd is the
    # isolated workspace, so use an absolute path to this checkout's sources.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def _wait_job(job_id: str, timeout: float = 15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await tail_job(job_id)
        if result["job"]["status"] not in {"starting", "running"}:
            return result
        await asyncio.sleep(0.1)
    pytest.fail(f"job {job_id} did not complete")


def _structured(result):
    # FastMCP.call_tool returns (content, structured_content) directly.
    return result[1] if isinstance(result, tuple) else result.structuredContent


@pytest.mark.asyncio
async def test_timeout_preserves_one_execution_and_tracks_output(isolated_job_workspace):
    path = isolated_job_workspace / "executed.txt"
    command = python_shell_command(
        f"from pathlib import Path; import time; "
        f"p=Path({str(path)!r}); p.open('a').write('once\\n'); "
        "print('before timeout', flush=True); time.sleep(2); print('finished')"
    )
    result = await run_job_with_timeout(command, ".", 1)
    assert result["timed_out"] is True
    assert result["persisted"] is True
    assert result["job_id"].startswith("job_")
    assert result["job_status"] == "running"
    # Slow CI machines may still be starting the runner at the deadline.
    assert result["stdout"].strip() in {"", "before timeout"}

    completed = await _wait_job(result["job_id"])
    assert completed["job"]["exit_code"] == 0
    assert "before timeout" in completed["output"]
    assert "finished" in completed["output"]
    assert path.read_text() == "once\n"


@pytest.mark.asyncio
async def test_completed_persistent_call_returns_exit_code_and_bounded_output(
    isolated_job_workspace,
):
    command = python_shell_command(
        "import sys; print('x'*300, flush=True); print('fail', file=sys.stderr, flush=True); sys.exit(7)"
    )
    result = await run_job_with_timeout(command, ".", 5, 32)
    assert result["timed_out"] is False
    assert result["persisted"] is False
    assert result["job_status"] == "failed"
    # PowerShell -Command maps nonzero native-process exit codes to 1.
    assert result["exit_code"] == (1 if os.name == "nt" else 7)
    assert result["ok"] is False
    assert len(result["stdout"].encode()) <= 32
    assert "fail" in result["stdout"]
    assert result["stderr"] == ""  # The persistent job log merges both streams.
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_timeout_has_no_terminal_placeholder_output(isolated_job_workspace):
    result = await run_job_with_timeout(python_shell_command("import time; time.sleep(2)"), ".", 1)
    assert result["stdout"] == ""
    await _wait_job(result["job_id"])


@pytest.mark.asyncio
async def test_run_python_can_persist_and_keep_script_path(isolated_job_workspace):
    result = await tools._run_python(
        "import time; print('start', flush=True); time.sleep(2)", ".", 1, True
    )
    assert result["timed_out"] is True
    assert result["job_id"]
    assert result["script_path"].endswith(".py")
    await _wait_job(result["job_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("runner", ["local", "worker"])
async def test_persistent_python_script_survives_pruning_and_retry(
    runner, isolated_job_workspace, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_TMP_FILES", "1")
    get_settings.cache_clear()
    marker = isolated_job_workspace / "reruns.txt"
    code = f"from pathlib import Path; Path({str(marker)!r}).open('a').write('once\\n')"
    entrypoint = tools._run_python if runner == "local" else remote._run_python
    result = await entrypoint(code, ".", 10, True)
    assert result["ok"] is True
    script = isolated_job_workspace / result["script_path"]
    assert script.is_file()

    for i in range(10):
        (temp_dir() / f"temporary-{i}.txt").write_text(str(i))
    prune_temp_dir()
    assert script.read_text() == code

    retried = await retry_job(result["job_id"])
    completed = await _wait_job(retried["job_id"])
    assert completed["job"]["exit_code"] == 0
    assert marker.read_text() == "once\nonce\n"

    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_JOBS", "1")
    get_settings.cache_clear()
    # Test retention pruning without starting a third shell on a crowded CI runner.
    with jobs._store_transaction() as store:
        store["jobs"].append(
            {"job_id": "newer_job", "status": "succeeded", "created_at": time.time() + 1}
        )
    assert not script.exists()


@pytest.mark.asyncio
async def test_live_log_cap_is_reported_as_truncated(isolated_job_workspace, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES", "64")
    get_settings.cache_clear()
    log = isolated_job_workspace / "job.log"
    log.write_bytes(b"x" * 64)

    async def fake_start(command, cwd):
        with jobs._store_transaction() as store:
            store["jobs"].append(
                {
                    "job_id": "job_test",
                    "status": "running",
                    "command": command,
                    "cwd": cwd,
                    "created_at": time.time(),
                    "log_path": str(log),
                    "status_path": str(log.with_suffix(".status")),
                }
            )
        return {"job_id": "job_test"}

    monkeypatch.setattr(jobs, "start_job", fake_start)
    monkeypatch.setattr(jobs, "_attempt_paths", lambda _id, _attempt: {"log": log, "status": log.with_suffix(".status")})
    result = await run_job_with_timeout("echo x", ".", 1, 1000)
    assert result["timed_out"] is True
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_completed_output_is_captured_before_zero_retention_pruning(
    isolated_job_workspace, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_JOBS", "0")
    get_settings.cache_clear()
    log = isolated_job_workspace / "result.log"
    log.write_text("completed\n")
    status = isolated_job_workspace / "result.status"
    status.write_text(json.dumps({"completed_at": time.time(), "exit_code": 0}))

    async def fake_start(command, cwd):
        with jobs._store_transaction() as store:
            store["jobs"].append(
                {
                    "job_id": "job_test",
                    "status": "running",
                    "command": command,
                    "cwd": cwd,
                    "created_at": time.time(),
                    "log_path": str(log),
                    "status_path": str(status),
                }
            )
        return {"job_id": "job_test"}

    monkeypatch.setattr(jobs, "start_job", fake_start)
    monkeypatch.setattr(jobs, "_attempt_paths", lambda _id, _attempt: {"log": log, "status": status})
    result = await run_job_with_timeout("echo completed", ".", 1)
    assert result["ok"] is True
    assert result["stdout"] == "completed\n"
    assert result["exit_code"] == 0
    assert (await jobs.list_jobs())["jobs"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("runner", ["local", "worker"])
async def test_python_invalid_calls_leave_no_durable_script(runner, isolated_job_workspace):
    entrypoint = tools._run_python if runner == "local" else remote._run_python
    with pytest.raises(ValueError, match="timeout_s"):
        await entrypoint("print('x')", ".", 121, True)
    with pytest.raises(Exception, match="missing|not found|exist"):
        await entrypoint("print('x')", "nonexistent-subdirectory", 3, True)
    assert not list((get_settings().state_dir / "jobs" / "scripts").glob("*.py"))


@pytest.mark.asyncio
@pytest.mark.parametrize("runner", ["local", "worker"])
async def test_python_failed_start_cleans_unreferenced_script(runner, isolated_job_workspace, monkeypatch):
    entrypoint = tools._run_python if runner == "local" else remote._run_python

    async def reject_start(*args, **kwargs):
        raise PermissionError("blocked start")

    monkeypatch.setattr(jobs, "start_job", reject_start)
    with pytest.raises(PermissionError, match="blocked start"):
        await entrypoint("print('x')", ".", 3, True)
    assert not list((get_settings().state_dir / "jobs" / "scripts").glob("*.py"))


def test_opted_in_local_command_is_not_cancelled_by_tool_watchdog():
    for name in ("run_shell", "run_python"):
        assert tools._public_tool_timeout_s(name, {"persist_on_timeout": True}) is None
        assert tools._public_tool_timeout_s(
            name, {"persist_on_timeout": True, "machine": "worker"}
        ) is None
        assert tools._public_tool_timeout_s(name, {}) is not None


@pytest.mark.asyncio
async def test_wrapper_defaults_to_nonpersistent_execution(monkeypatch, isolated_job_workspace):
    seen = []

    async def fake_normal(*args):
        seen.append(args)
        from local_shell_mcp.models import CommandResult

        return CommandResult(ok=True, exit_code=0, duration_ms=0, cwd=".", command="echo ok")

    async def should_not_start(*args):
        raise AssertionError("default call must not start a tracked job")

    monkeypatch.setattr(tools, "public_run_shell", fake_normal)
    monkeypatch.setattr(tools, "run_job_with_timeout", should_not_start)
    result = await tools.build_mcp().call_tool("run_shell", {"command": "echo ok"})
    assert _structured(result)["data"]["ok"] is True
    assert seen == [("echo ok", ".", None, None)]


@pytest.mark.asyncio
async def test_worker_receives_persistence_option(monkeypatch):
    seen = []

    async def fake_job(*args):
        seen.append(args)
        return {"timed_out": True, "job_id": "job_test"}

    monkeypatch.setattr(remote, "run_job_with_timeout", fake_job)
    result = await remote._execute_command_worker_tool(
        "run_shell_persist_tool",
        {"command": "sleep 10", "cwd": ".", "timeout_s": 1},
    )
    assert result["job_id"] == "job_test"
    assert seen == [("sleep 10", ".", 1, None)]

    async def fake_python(*args):
        seen.append(args)
        return {"timed_out": True, "job_id": "job_python"}

    monkeypatch.setattr(remote, "_run_python", fake_python)
    result = await remote._execute_command_worker_tool(
        "run_python_persist_tool",
        {"code": "print(1)", "cwd": ".", "timeout_s": 1},
    )
    assert result["job_id"] == "job_python"
    assert seen[-1] == ("print(1)", ".", 1, True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("run_shell_tool", {"command": "echo unsafe", "persist_on_timeout": True}),
        ("run_python_tool", {"code": "print('unsafe')", "persist_on_timeout": True}),
    ],
)
async def test_ordinary_worker_operations_reject_unprotected_persistence(tool, args):
    with pytest.raises(ValueError, match="require run_"):
        await remote._execute_command_worker_tool(tool, args)


@pytest.mark.asyncio
async def test_local_mcp_opt_in_returns_tracked_job(isolated_job_workspace):
    result = await tools.build_mcp().call_tool(
        "run_shell", {"command": "echo hello", "timeout_s": 10, "persist_on_timeout": True}
    )
    data = _structured(result)["data"]
    assert data["job_id"].startswith("job_")
    assert data["job_status"] == "succeeded"
    assert data["timed_out"] is False
    assert data["stdout"].strip() == "hello"


@pytest.mark.asyncio
async def test_invalid_public_timeout_does_not_start_job(monkeypatch, isolated_job_workspace):
    async def should_not_start(*args):
        raise AssertionError("timeout must be validated before job creation")

    import local_shell_mcp.jobs as jobs

    monkeypatch.setattr(jobs, "start_job", should_not_start)
    with pytest.raises(ValueError, match="timeout_s must be"):
        await run_job_with_timeout("echo no", ".", 121)


@pytest.mark.asyncio
async def test_remote_tool_forwards_opt_in_flag(monkeypatch, isolated_job_workspace):
    seen = []

    async def fake_remote(settings, machine, tool, args, **kwargs):
        seen.append((machine, tool, args, kwargs))
        return tools._ok({"job_id": "job_test"})

    monkeypatch.setattr(tools, "_remote_call", fake_remote)
    mcp = tools.build_mcp()
    for name, payload in (
        ("run_shell", {"command": "sleep 10"}),
        ("run_python", {"code": "import time; time.sleep(10)"}),
    ):
        result = await mcp.call_tool(
            name, {**payload, "machine": "worker1", "timeout_s": 1, "persist_on_timeout": True}
        )
        assert _structured(result)["data"]["job_id"] == "job_test"
    assert [row[1] for row in seen] == ["run_shell_persist_tool", "run_python_persist_tool"]
    assert all(row[3]["execution_timeout_s"] > 1 for row in seen)

    seen.clear()
    for name, payload in (
        ("run_shell", {"command": "echo ok"}),
        ("run_python", {"code": "print(1)"}),
    ):
        await mcp.call_tool(name, {**payload, "machine": "worker1"})
    assert [row[1] for row in seen] == ["run_shell_tool", "run_python_tool"]


@pytest.mark.asyncio
async def test_expensive_preflight_cannot_be_bypassed_with_persistence(
    monkeypatch, isolated_job_workspace
):
    async def should_not_start(*args):
        raise AssertionError("preflight must block persistent recursive scans")

    monkeypatch.setattr(tools, "run_job_with_timeout", should_not_start)
    result = await tools.build_mcp().call_tool(
        "run_shell",
        {
            "command": "find / -type f -name '*.db'",
            "cwd": "/",
            "timeout_s": 60,
            "persist_on_timeout": True,
        },
    )
    assert _structured(result)["ok"] is False
