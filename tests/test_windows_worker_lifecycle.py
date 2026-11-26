"""Process-level Windows venv regression (also exercises the protocol on POSIX)."""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from local_shell_mcp import remote_worker_bootstrap as bootstrap


def test_venv_supervisor_restarts_twice_without_lock_inheritance(tmp_path):
    # Use a real venv: on Windows its python.exe redirector adds another
    # process between the supervisor and the actual worker.
    venv_root = tmp_path / "worker-venv"
    venv.EnvBuilder(with_pip=False).create(venv_root)
    python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    state = tmp_path / "state"
    runtime = state / "runtime" / "local_shell_mcp"
    runtime.mkdir(parents=True)
    source = Path(bootstrap.__file__).resolve().parent
    (runtime / "__init__.py").write_text(f"__path__.append({str(source)!r})\n", encoding="utf-8")
    (runtime / "remote_worker.py").write_text(
        r'''
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from local_shell_mcp.remote_worker_service import worker_run_lock, _pid_is_running

state = Path(os.environ["LOCAL_SHELL_MCP_WORKER_STATE_DIR"])
history = state / "worker-pids.json"
pending = state / "runtime.pending.json"
attempted = state / "runtime.attempted"
previous = state / "runtime.previous"
pids = json.loads(history.read_text()) if history.exists() else []
assert os.environ["LOCAL_SHELL_MCP_WORKER_RESTART_PROTOCOL"] == "1"
assert "LOCAL_SHELL_MCP_WORKER_LOCK_FD" not in os.environ

with worker_run_lock():
    assert all(not _pid_is_running(pid) for pid in pids)
    if pids:
        assert pending.exists() and attempted.exists()
        pending.unlink()
        attempted.unlink()
        shutil.rmtree(previous)
    # The previous process must have exited, but a new competitor must
    # still be excluded by the current process's own real OS lock.
    env = os.environ.copy()
    env.pop("LOCAL_SHELL_MCP_WORKER_MANAGED", None)
    probe = subprocess.run(
        [sys.executable, "-c",
         "from local_shell_mcp.remote_worker_service import worker_run_lock, WorkerAlreadyRunningError\n"
         "try:\n with worker_run_lock(): pass\n"
         "except WorkerAlreadyRunningError: raise SystemExit(2)\n"],
        env=env, capture_output=True, timeout=10,
    )
    assert probe.returncode == 2, (probe.returncode, probe.stderr)
    pids.append(os.getpid())
    history.write_text(json.dumps(pids))
    if len(pids) < 3:
        shutil.copytree(state / "runtime", previous)
        pending.write_text(json.dumps({"previous_digest": "stable", "previous_version": "v1"}))
        raise SystemExit(75)
    print("TWO_RESTARTS_OK", flush=True)
''',
        encoding="utf-8",
    )
    script = state / "worker-bootstrap.py"
    script.write_bytes(Path(bootstrap.__file__).read_bytes())
    env = os.environ.copy()
    env.update({
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "LOCAL_SHELL_MCP_WORKER_MANAGED": "1",
        "PYTHONPATH": "",
    })
    env.pop("LOCAL_SHELL_MCP_WORKER_LOCK_FD", None)
    if os.name == "nt":
        env["LOCAL_SHELL_MCP_WORKER_LOCK_FD"] = "9999"
    result = subprocess.run(
        [str(python), str(script)], env=env, capture_output=True, text=True,
        timeout=45, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "TWO_RESTARTS_OK" in result.stdout
    assert "rolled back" not in result.stderr
    assert not (state / "runtime.pending.json").exists()
    assert not (state / "runtime.attempted").exists()
    assert not (state / "runtime.previous").exists()
    assert not (state / "worker.owner.json").exists()

@pytest.mark.skipif(os.name != "nt", reason="requires Windows Job Objects")
def test_windows_supervisor_job_terminates_descendants(tmp_path):
    import _winapi
    import json
    import time

    source = Path(bootstrap.__file__).resolve().parents[1]
    marker = tmp_path / "pids.json"
    script = r"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from local_shell_mcp.remote_worker_bootstrap import _bind_windows_supervisor_lifetime

bound = _bind_windows_supervisor_lifetime()
child = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-c", "import time; time.sleep(60)"])
try:
    marker = Path(sys.argv[1])
    temp = marker.with_suffix(".tmp")
    temp.write_text(json.dumps([bound, os.getpid(), child.pid]))
    temp.replace(marker)
    time.sleep(60)
finally:
    child.terminate()
    child.wait(timeout=10)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source)
    env["LOCAL_SHELL_MCP_WORKER_MANAGED"] = "1"
    supervisor = subprocess.Popen([sys.executable, "-c", script, str(marker)], env=env)
    handles = []
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and supervisor.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), "supervisor did not create a child"
        bound, supervisor_pid, child_pid = json.loads(marker.read_text())
        for pid in (supervisor_pid, child_pid):
            handles.append(_winapi.OpenProcess(0x00100001, False, pid))
        if not bound:
            pytest.skip("host job restrictions prohibit nested Job Objects")
        _winapi.TerminateProcess(handles[0], 1)
        assert _winapi.WaitForSingleObject(handles[1], 10000) == _winapi.WAIT_OBJECT_0
    finally:
        for handle in reversed(handles):
            if _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT:
                _winapi.TerminateProcess(handle, 1)
            _winapi.CloseHandle(handle)
        if supervisor.poll() is None:
            supervisor.terminate()
        supervisor.wait(timeout=10)
