from __future__ import annotations

import asyncio
import base64
import io
import json
import os
from types import SimpleNamespace

import pytest

import local_shell_mcp.conpty_ops as conpty
import local_shell_mcp.jobs as jobs
import local_shell_mcp.shell_ops as shell
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tmux_helper import TmuxSelection


def _configure(tmp_path, monkeypatch, **extra):
    values = {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(tmp_path),
        "LOCAL_SHELL_MCP_STATE_DIR": str(tmp_path / ".state"),
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH": str(tmp_path / "audit.jsonl"),
        "LOCAL_SHELL_MCP_AUTH_MODE": "none",
        "LOCAL_SHELL_MCP_COMMAND_DENYLIST": "",
        "LOCAL_SHELL_MCP_PATH_DENYLIST": "",
    }
    values.update({key: str(value) for key, value in extra.items()})
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    jobs._ACTIVE_JOB_OPERATIONS.clear()
    shell._NATIVE_SHELL_SESSIONS.clear()
    conpty._CONPTY_SHELL_SESSIONS.clear()


def _command_result(*, ok=True, stdout="", stderr=""):
    return CommandResult(
        ok=ok,
        exit_code=0 if ok else 1,
        timed_out=False,
        duration_ms=1,
        cwd=".",
        command="cmd",
        stdout=stdout,
        stderr=stderr,
        truncated=False,
    )


def test_job_store_helpers_recovery_pruning_and_attempt_files(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_MAX_JOBS=1)
    assert jobs._load_store() == jobs._empty_store()

    invalid = tmp_path / "invalid.json"
    for payload in ({"version": 3, "jobs": []}, {"version": 2, "jobs": {}}, []):
        invalid.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            jobs._load_store_file(invalid)

    invalid.write_text(
        json.dumps({"version": 1, "jobs": [{"job_id": "legacy"}, 1]}),
        encoding="utf-8",
    )
    assert jobs._load_store_file(invalid) == {
        "version": jobs.JOB_STORE_VERSION,
        "jobs": [{"job_id": "legacy"}],
    }

    main = jobs._job_store_path()
    backup = jobs._job_store_backup_path()
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_text("bad", encoding="utf-8")
    backup.write_text(json.dumps({"version": 2, "jobs": [{"job_id": "a"}, 1]}), encoding="utf-8")
    recovered = jobs._load_store()
    assert recovered["jobs"] == [{"job_id": "a"}]
    backup.write_text("bad", encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing"):
        jobs._load_store()

    jobs._remove_attempt_paths(None)
    paths = {"a": tmp_path / "a", "b": tmp_path / "b"}
    for path in paths.values():
        path.write_text("x", encoding="utf-8")
    jobs._remove_attempt_paths(paths)
    assert not any(path.exists() for path in paths.values())

    runtime = jobs._job_runtime_dir()
    for name in ("job_x-attempt-1.log", "job_x-attempt-2.log"):
        (runtime / name).write_text("x", encoding="utf-8")
    jobs._remove_attempt_files("")
    jobs._remove_attempt_files("job_x", keep_attempt=2)
    assert not (runtime / "job_x-attempt-1.log").exists()
    assert (runtime / "job_x-attempt-2.log").exists()

    store = {
        "jobs": [
            {"job_id": "active", "status": "running", "created_at": 1},
            {"job_id": "old", "status": "failed", "created_at": 1},
            {"job_id": "new", "status": "failed", "created_at": 2},
        ]
    }
    jobs._prune_store(store)
    assert [job["job_id"] for job in store["jobs"]] == ["active"]


def test_job_runner_arguments_status_and_operations(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    paths = jobs._attempt_paths("job", 2)
    argv = jobs._runner_argv(paths, tmp_path)
    assert argv[1:4] == ["-m", "local_shell_mcp.main", "job-runner"]
    monkeypatch.setattr(jobs.sys, "frozen", True, raising=False)
    assert jobs._runner_argv(paths, tmp_path)[1] == "job-runner"

    assert jobs._runner_command(["a", "b c"], "bash") == "a 'b c'"
    assert jobs._runner_command(["a", "b'c"], "powershell.exe").startswith("& ")
    assert "\"b c\"" in jobs._runner_command(["a", "b c"], "cmd.exe")
    assert jobs._runner_shell_args("pwsh", "x")[-1] == "x"
    assert jobs._runner_shell_args("cmd", "x")[1:3] == ["/S", "/C"]
    assert jobs._runner_shell_args("bash", "x")[-2:] == ["-lc", "x"]

    assert jobs._shell_safe_name("  💥  ") == "job"
    assert jobs._active_session_ids({"sessions": [{"session_id": "a"}, {}]}) == {"a"}
    assert jobs._read_status_path(None) is None
    bad = tmp_path / "bad-status"
    bad.write_text("bad", encoding="utf-8")
    assert jobs._read_status_path(bad) is None
    bad.write_text("[]", encoding="utf-8")
    assert jobs._read_status_path(bad) is None

    job = {}
    jobs._apply_status_payload(job, {"exit_code": 0, "completed_at": 5, "output_bytes": 3}, 9)
    assert job["status"] == "succeeded" and job["completed_at"] == 5
    jobs._apply_status_payload(job, {"exit_code": 2, "error": "bad"}, 9)
    assert job["status"] == "failed" and job["error"] == "bad"

    job = {
        "pending_attempt": 2,
        "pending_session_name": "s",
        "pending_command_path": "c",
        "pending_log_path": "l",
        "pending_status_path": "p",
    }
    jobs._adopt_pending_retry(job)
    assert job["attempts"] == 2 and job["session_id"] == "s"
    jobs._clear_pending_retry(job)
    assert "pending_attempt" not in job

    op = jobs._begin_job_operation(job, "retry")
    assert jobs._job_operation_matches(job, op)
    assert jobs._job_operation_is_active(job, "retry")
    jobs._ACTIVE_JOB_OPERATIONS.discard(op)
    assert not jobs._job_operation_is_active(job, "retry")
    jobs._clear_job_operation(job)
    assert "operation_id" not in job
    with pytest.raises(KeyError, match="not found"):
        jobs._find_job({"jobs": []}, "missing")

    encoded = jobs._encode_runner_env_policy(["A", "B"])
    assert jobs._parse_runner_env_policy(encoded, "value") == ["A", "B"]
    for raw in ("bad", base64.urlsafe_b64encode(b"{}").decode()):
        with pytest.raises(ValueError):
            jobs._parse_runner_env_policy(raw, "value")


def test_job_refresh_every_recovery_state(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert jobs._refresh_job_status({"status": "done"}, set()) == {"status": "done"}

    active_retry = {"status": "retrying"}
    operation = jobs._begin_job_operation(active_retry, "retry")
    assert jobs._refresh_job_status(active_retry, set()) is active_retry
    jobs._ACTIVE_JOB_OPERATIONS.discard(operation)

    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({"exit_code": 0, "completed_at": 3}), encoding="utf-8")
    retry = {
        "status": "retrying",
        "pending_attempt": 2,
        "pending_session_name": "new",
        "pending_status_path": str(status_path),
    }
    jobs._refresh_job_status(retry, set(), 5)
    assert retry["status"] == "succeeded" and retry["attempts"] == 2

    retry = {"status": "retrying", "pending_attempt": 2, "pending_session_name": "new"}
    jobs._refresh_job_status(retry, {"new"}, 5)
    assert retry["status"] == "running" and "recovered retry" in retry["error"]
    retry = {"status": "retrying", "pending_attempt": 2}
    jobs._refresh_job_status(retry, set(), 5)
    assert retry["status"] == "failed"

    stopping = {"status": "stopping", "session_id": "s"}
    jobs._refresh_job_status(stopping, {"s"}, 5)
    assert stopping["status"] == "running"
    stopping = {"status": "stopping", "session_id": "s"}
    jobs._refresh_job_status(stopping, set(), 5)
    assert stopping["status"] == "stopped"

    running = {"status": "running", "session_id": "s"}
    assert jobs._refresh_job_status(running, {"s"}, 5)["status"] == "running"
    jobs._refresh_job_status(running, set(), 5)
    assert running["status"] == "lost"


def test_job_log_compaction_and_runner_error_status(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES=5)
    log = tmp_path / "log"
    assert jobs._read_log_tail(None, 2) == ""
    assert jobs._read_log_tail(str(log), 2) == ""
    log.write_bytes(b"a\nb\nc\n")
    assert jobs._read_log_tail(str(log), 2) == "b\nc\n"

    handle = io.BytesIO(b"123")
    handle.seek(0, os.SEEK_END)
    assert jobs._compact_log(handle, 5) is False
    handle = io.BytesIO(b"123456789")
    handle.seek(0, os.SEEK_END)
    assert jobs._compact_log(handle, 4) is True
    assert handle.getvalue() == b"6789"

    command = tmp_path / "command"
    log = tmp_path / "runner.log"
    status = tmp_path / "runner.status"
    command.write_text("echo x", encoding="utf-8")

    class NoStdout:
        stdout = None

    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *args, **kwargs: NoStdout())
    with pytest.raises(SystemExit) as raised:
        jobs.run_job_runner_cli(
            [
                "--command-file", str(command),
                "--log-file", str(log),
                "--status-file", str(status),
                "--cwd", str(tmp_path),
                "--shell", "bash",
                "--max-log-bytes", "4",
            ]
        )
    assert raised.value.code == 127
    payload = json.loads(status.read_text(encoding="utf-8"))
    assert "did not expose stdout" in payload["error"]


def test_job_start_tail_stop_and_retry_failures(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def start_shell(cwd, name, command):
        return {"session_id": "session", "backend": "native"}

    monkeypatch.setattr(jobs, "start_shell", start_shell)
    started = asyncio.run(jobs.start_job("echo x", name="name"))
    assert started["status"] == "running"
    job_id = started["job_id"]

    monkeypatch.setattr(jobs, "list_shells", lambda: asyncio.sleep(0, result={"sessions": [{"session_id": "session"}]}))
    monkeypatch.setattr(jobs, "read_shell", lambda *args: asyncio.sleep(0, result={"output": "live"}))
    tailed = asyncio.run(jobs.tail_job(job_id))
    assert tailed["output"] == "live"

    monkeypatch.setattr(jobs, "read_shell", lambda *args: (_ for _ in ()).throw(RuntimeError("read failed")))
    tailed = asyncio.run(jobs.tail_job(job_id))
    assert tailed["job"]["status"] == "lost"

    terminal = asyncio.run(jobs.stop_job(job_id))
    assert terminal["killed"] is False

    with jobs._store_transaction() as store:
        current = jobs._find_job(store, job_id)
        current["status"] = "failed"
    monkeypatch.setattr(jobs, "_prepare_attempt", lambda *args: (_ for _ in ()).throw(RuntimeError("prepare")))
    with pytest.raises(RuntimeError, match="prepare"):
        asyncio.run(jobs.retry_job(job_id))
    with jobs._store_transaction() as store:
        assert "retry failed" in jobs._find_job(store, job_id)["error"]


def test_shell_buffers_arguments_timeouts_and_reader_helpers(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES=5)
    tail = shell.TailBuffer(3, bytearray())
    tail.append(b"")
    tail.append(b"abcdef")
    assert bytes(tail.data) == b"def" and tail.truncated

    assert shell._shared_tail_bytes(b"a", b"b", 5) == (b"a", b"b", False)
    out, err, truncated = shell._shared_tail_bytes(b"abcdef", b"xy", 5)
    assert len(out) + len(err) == 5 and truncated
    assert shell.clamp_output("abcdef", "xy")[-1] is True
    assert shell._effective_output_limit(None) == 5
    assert shell._effective_output_limit(100) == 5

    for executable, expected in (
        ("powershell.exe", ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "x"]),
        ("cmd.exe", ["cmd.exe", "/S", "/C", "x"]),
        ("/bin/bash", ["/bin/bash", "-lc", "x"]),
    ):
        monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
        get_settings.cache_clear()
        assert shell._shell_command_args("x") == expected
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", "powershell.exe")
    get_settings.cache_clear()
    assert shell.quote_shell_argument("a'b") == "'a''b'"
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", "cmd.exe")
    get_settings.cache_clear()
    assert "a b" in shell.quote_shell_argument("a b")
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", "/bin/bash")
    get_settings.cache_clear()
    assert shell._persistent_shell_args() == ["/bin/bash"]
    assert shell._persistent_shell_args("x")[-1] == "x"

    assert shell.public_run_shell_timeout(None) == 10
    assert shell.public_run_shell_timeout(0) == 10
    with pytest.raises(ValueError):
        shell.public_run_shell_timeout(121)

    class Stream:
        def __init__(self, values):
            self.values = list(values)

        async def read(self, size):
            return self.values.pop(0)

    tail = shell.TailBuffer(10, bytearray())
    asyncio.run(shell._read_stream_tail(None, tail))
    asyncio.run(shell._read_stream_tail(Stream([b"x", b""]), tail))
    assert bytes(tail.data) == b"x"

    class Proc:
        async def wait(self):
            await asyncio.sleep(1)

    assert asyncio.run(shell._wait_for_process_exit(Proc(), 0)) is False

    async def slow():
        await asyncio.sleep(1)

    task = None

    async def finish():
        nonlocal task
        task = asyncio.create_task(slow())
        await shell._finish_reader_tasks([task], timeout_s=0)

    asyncio.run(finish())
    assert task is not None and task.cancelled()


def test_shell_process_termination_native_sessions_and_dispatch(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Proc:
        pid = 12
        returncode = None

        def __init__(self):
            self.terminated = False
            self.killed = False
            self.stdin = None
            self._transport = SimpleNamespace(close=lambda: None)

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    proc = Proc()
    waits = iter([False, True])
    monkeypatch.setattr(shell, "_wait_for_process_exit", lambda *args: asyncio.sleep(0, result=next(waits)))
    monkeypatch.setattr(
        shell.os,
        "killpg",
        lambda *args: (_ for _ in ()).throw(OSError()),
        raising=False,
    )
    assert asyncio.run(shell._terminate_process_group(proc)) == ""
    assert proc.terminated and proc.killed

    proc = Proc()
    monkeypatch.setattr(shell, "_wait_for_process_exit", lambda *args: asyncio.sleep(0, result=False))
    assert "did not exit" in asyncio.run(shell._native_stop_process(proc))

    output = shell.TailBuffer(100, bytearray(b"one\ntwo\n"))
    alive = SimpleNamespace(returncode=None)
    session = shell.NativeShellSession("s", alive, tmp_path, "cmd", 1, output, [], asyncio.Lock())
    shell._NATIVE_SHELL_SESSIONS["s"] = session
    assert asyncio.run(shell._native_read_shell("s", 1))["output"] == "two\n"
    assert asyncio.run(shell._native_list_shells())["sessions"][0]["session_id"] == "s"
    alive.returncode = 2
    with pytest.raises(RuntimeError, match="exited"):
        shell._get_native_session("s")
    with pytest.raises(RuntimeError, match="not found"):
        shell._get_native_session("missing")
    assert asyncio.run(shell._native_kill_shell("missing"))["killed"] is False

    monkeypatch.setattr(shell, "resolve_tmux", lambda: TmuxSelection(None, "native"))
    monkeypatch.setattr(shell, "_native_send_shell", lambda *args: asyncio.sleep(0, result={"native": True}))
    monkeypatch.setattr(shell, "_native_read_shell", lambda *args: asyncio.sleep(0, result={"native": True}))
    monkeypatch.setattr(shell, "_native_kill_shell", lambda *args: asyncio.sleep(0, result={"native": True}))
    assert (asyncio.run(shell.send_shell("x", "y")))["native"]
    assert (asyncio.run(shell.read_shell("x")))["native"]
    assert (asyncio.run(shell.kill_shell("x")))["native"]

    monkeypatch.setattr(shell, "_use_windows_persistent_shell_backend", lambda: False)
    monkeypatch.setattr(shell, "resolve_tmux", lambda: TmuxSelection("/tmux", "system"))
    responses = iter([_command_result(), _command_result(), _command_result(stdout="pane"), _command_result()])
    monkeypatch.setattr(shell, "tmux", lambda *args, **kwargs: asyncio.sleep(0, result=next(responses)))
    sent = asyncio.run(shell.send_shell("tmux", "text", True))
    assert sent["enter"] is True
    assert asyncio.run(shell.read_shell("tmux"))["output"] == "pane"
    assert asyncio.run(shell.kill_shell("tmux"))["killed"] is True


def test_conpty_helpers_cleanup_start_send_read_kill_and_list(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS=1)
    assert conpty.is_available() is (conpty.winpty is not None and hasattr(conpty.winpty, "PtyProcess"))
    assert conpty._session_name("bad name") == "bad-name"
    for executable, suffix in (
        ("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", "x"]),
        ("cmd.exe", ["/S", "/C", "x"]),
        ("bash", ["-lc", "x"]),
    ):
        monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
        get_settings.cache_clear()
        assert conpty._shell_command_args("x")[1:] == suffix
    assert isinstance(conpty._spawn_command(["a", "b c"]), str)

    monkeypatch.setattr(conpty, "winpty", None)
    with pytest.raises(RuntimeError, match="not available"):
        conpty._spawn_pty(["x"], tmp_path)

    class Process:
        def __init__(self, alive=True):
            self.alive = alive
            self.exitstatus = None if alive else 1
            self.writes = []
            self.closed = False

        def isalive(self):
            return self.alive

        def read(self, *args):
            if args:
                raise TypeError
            return "data"

        def write(self, data):
            self.writes.append(data)

        def close(self, force=False):
            self.closed = True

    process = Process()
    assert conpty._pty_is_alive(process)
    assert conpty._read_pty(process) == "data"
    conpty._close_pty_process(process, True)
    assert process.closed

    terminate = SimpleNamespace(terminate=lambda: None)
    conpty._close_pty_process(terminate, True)

    dead = Process(False)
    stale = conpty.ConPtyShellSession("stale", dead, tmp_path, "x", 1, conpty.TailBuffer(10, bytearray()), None, asyncio.Lock())
    conpty._CONPTY_SHELL_SESSIONS["stale"] = stale

    spawned = Process(True)
    monkeypatch.setattr(conpty, "_spawn_pty", lambda *args: spawned)
    checked = []
    started = asyncio.run(conpty.start_shell(".", "new", "cmd", checked.append))
    assert started["backend"] == "conpty" and checked == ["cmd"]
    assert "stale" not in conpty._CONPTY_SHELL_SESSIONS
    with pytest.raises(RuntimeError, match="more than"):
        asyncio.run(conpty.start_shell(".", "other"))

    assert asyncio.run(conpty.send_shell("new", "input"))["enter"] is True
    assert spawned.writes[-1] == "input\r"
    session = conpty._CONPTY_SHELL_SESSIONS["new"]
    session.output.append(b"one\ntwo\n")
    assert asyncio.run(conpty.read_shell("new", 1))["output"] == "two\n"
    assert asyncio.run(conpty.list_shells())["sessions"][0]["backend"] == "conpty"
    killed = asyncio.run(conpty.kill_shell("new"))
    assert killed["killed"] is True
    assert asyncio.run(conpty.kill_shell("missing"))["killed"] is False
    with pytest.raises(RuntimeError, match="not found"):
        asyncio.run(conpty._get_session("missing"))


def test_conpty_reader_exception_and_cleanup_variants(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class Process:
        exitstatus = None

        def isalive(self):
            return True

    process = Process()
    session = conpty.ConPtyShellSession("s", process, tmp_path, "x", 1, conpty.TailBuffer(100, bytearray()), None, asyncio.Lock())
    monkeypatch.setattr(conpty, "_read_pty", lambda value: (_ for _ in ()).throw(RuntimeError("read")))
    asyncio.run(conpty._read_conpty_shell(session))
    assert b"reader stopped" in session.output.data

    class BadClose:
        def close(self, force=False):
            raise RuntimeError("close")

    session.process = BadClose()
    error = asyncio.run(conpty._cleanup_session(session, force=True))
    assert "close" in error

    class FakeReader:
        def get_loop(self):
            raise RuntimeError("loop")

    asyncio.run(conpty._cleanup_reader(FakeReader()))
