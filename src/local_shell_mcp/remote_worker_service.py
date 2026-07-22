from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import platform
import plistlib
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .remote_worker_state import (
    ensure_user_bin_on_path,
    install_launcher,
    user_home,
    worker_launcher_path,
    worker_lock_path,
    worker_log_path,
    worker_pid_path,
    worker_runtime_dir,
    worker_state_dir,
)

_SERVICE_NAME = "local-shell-mcp-worker"
_LAUNCHD_LABEL = "com.fwerkor.local-shell-mcp-worker"
_WORKER_MANAGED_ENV = "LOCAL_SHELL_MCP_WORKER_MANAGED"
_WORKER_LOCK_FD_ENV = "LOCAL_SHELL_MCP_WORKER_LOCK_FD"
_WORKER_LOCK_RETRY_S = 5.0
_active_worker_lock_handle: Any | None = None


class WorkerAlreadyRunningError(RuntimeError):
    pass


def _lock_worker_file(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_worker_file(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _worker_lock_is_contended(exc: OSError) -> bool:
    if isinstance(exc, BlockingIOError) or exc.errno in {errno.EACCES, errno.EAGAIN}:
        return True
    return os.name == "nt" and getattr(exc, "winerror", None) in {32, 33}


def prepare_worker_lock_reexec() -> int | None:
    handle = _active_worker_lock_handle
    if handle is None:
        return None
    fd = handle.fileno()
    os.set_inheritable(fd, True)
    os.environ[_WORKER_LOCK_FD_ENV] = str(fd)
    return fd


def cancel_worker_lock_reexec(fd: int | None) -> None:
    if fd is None:
        return
    os.environ.pop(_WORKER_LOCK_FD_ENV, None)
    with contextlib.suppress(OSError):
        os.set_inheritable(fd, False)


def _adopt_worker_lock_handle() -> Any | None:
    raw_fd = os.environ.pop(_WORKER_LOCK_FD_ENV, "")
    if not raw_fd:
        return None
    try:
        fd = int(raw_fd)
        os.fstat(fd)
    except (OSError, ValueError):
        return None
    return os.fdopen(fd, "r+b", buffering=0)


@contextlib.contextmanager
def worker_run_lock():  # noqa: ANN201
    global _active_worker_lock_handle

    path = worker_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = _adopt_worker_lock_handle()
    locked = handle is not None
    if handle is None:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        handle = os.fdopen(fd, "r+b", buffering=0)
    try:
        if path.stat().st_size == 0:
            handle.write(b"\0")
        waiting = False
        while not locked:
            try:
                _lock_worker_file(handle)
                locked = True
            except OSError as exc:
                if not _worker_lock_is_contended(exc):
                    raise
                if os.getenv(_WORKER_MANAGED_ENV) != "1":
                    raise WorkerAlreadyRunningError(
                        "remote worker is already running; stop the existing process or use "
                        "`local-shell-mcp worker restart`"
                    ) from exc
                if not waiting:
                    print(
                        "Status: another worker process is active; managed worker is waiting...",
                        file=sys.stderr,
                        flush=True,
                    )
                    waiting = True
                time.sleep(_WORKER_LOCK_RETRY_S)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
        _active_worker_lock_handle = handle
        yield
    finally:
        if _active_worker_lock_handle is handle:
            _active_worker_lock_handle = None
        if locked:
            with contextlib.suppress(OSError):
                _unlock_worker_file(handle)
        handle.close()


def _systemd_unit_path() -> Path:
    return user_home() / ".config" / "systemd" / "user" / f"{_SERVICE_NAME}.service"


def _launchd_plist_path() -> Path:
    return user_home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)  # noqa: S603


def _user_id() -> int:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid else 0


def _systemd_user_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    result = _run(["systemctl", "--user", "show-environment"], check=False)
    return result.returncode == 0


def service_kind() -> str:
    system = platform.system()
    if system == "Linux" and _systemd_user_available():
        return "systemd"
    if system == "Darwin" and shutil.which("launchctl"):
        return "launchd"
    return "process"


def _write_systemd_unit() -> Path:
    path = _systemd_unit_path()
    launcher = shlex.quote(str(worker_launcher_path()))
    content = f"""[Unit]
Description=local-shell-mcp remote worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={launcher} worker run
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=LOCAL_SHELL_MCP_WORKER_MANAGED=1

[Install]
WantedBy=default.target
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_launchd_plist() -> Path:
    path = _launchd_plist_path()
    payload = {
        "Label": _LAUNCHD_LABEL,
        "ProgramArguments": [str(worker_launcher_path()), "worker", "run"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {_WORKER_MANAGED_ENV: "1"},
        "StandardOutPath": str(worker_log_path()),
        "StandardErrorPath": str(worker_log_path()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False))
    return path


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_worker_command(command: str) -> bool:
    normalized = command.replace("\\", "/")
    module = "local_shell_mcp.main" in normalized or "local_shell_mcp.remote_worker" in normalized
    return module and "worker" in normalized and "run" in normalized


def _linux_process_identity(pid: int) -> str | None:
    proc = Path("/proc") / str(pid)
    try:
        stat_text = (proc / "stat").read_text(encoding="utf-8")
        command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        )
    except OSError:
        return None
    closing = stat_text.rfind(")")
    if closing < 0 or not _is_worker_command(command):
        return None
    fields = stat_text[closing + 2 :].split()
    if len(fields) <= 19:
        return None
    start_ticks = fields[19]
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    return f"linux:{start_ticks}:{digest}"


def _windows_process_identity(pid: int) -> str | None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return None
    script = (
        f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {pid}"; '
        'if ($p) { Write-Output ($p.CreationDate + "|" + $p.CommandLine) }'
    )
    result = _run([shell, "-NoProfile", "-Command", script], check=False)
    value = result.stdout.strip()
    if result.returncode or "|" not in value:
        return None
    created, command = value.split("|", 1)
    if not created or not _is_worker_command(command):
        return None
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    return f"windows:{created}:{digest}"


def _posix_process_identity(pid: int) -> str | None:
    result = _run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="], check=False)
    value = result.stdout.strip()
    if result.returncode or not value or not _is_worker_command(value):
        return None
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"posix:{digest}"


def _process_identity(pid: int) -> str | None:
    if not _pid_is_running(pid):
        return None
    system = platform.system()
    if system == "Linux" and Path("/proc").is_dir():
        return _linux_process_identity(pid)
    if system == "Windows":
        return _windows_process_identity(pid)
    return _posix_process_identity(pid)


def _write_pid(pid: int, identity: str) -> None:
    worker_pid_path().parent.mkdir(parents=True, exist_ok=True)
    worker_pid_path().write_text(
        json.dumps({"version": 1, "pid": pid, "identity": identity}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with contextlib.suppress(OSError):
        worker_pid_path().chmod(0o600)


def _read_pid() -> int | None:
    path = worker_pid_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    expected = ""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError
        pid = int(data["pid"])
        expected = str(data.get("identity") or "")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        try:
            pid = int(raw)
        except ValueError:
            path.unlink(missing_ok=True)
            return None
    actual = _process_identity(pid)
    if not actual or (expected and actual != expected):
        path.unlink(missing_ok=True)
        return None
    if not expected:
        _write_pid(pid, actual)
    return pid


def _process_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("LOCAL_SHELL_MCP_WORKSPACE_ROOT", None)
    env.pop("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", None)
    runtime = worker_runtime_dir()
    current = env.get("PYTHONPATH", "")
    pythonpath = os.pathsep.join((str(runtime), str(runtime / "vendor")))
    env["PYTHONPATH"] = pythonpath + (os.pathsep + current if current else "")
    env["LOCAL_SHELL_MCP_WORKER_STATE_DIR"] = str(worker_state_dir().resolve())
    env[_WORKER_MANAGED_ENV] = "1"
    return env


def _start_process() -> None:
    if _read_pid():
        return
    worker_state_dir().mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "local_shell_mcp.main", "worker", "run"]
    with worker_log_path().open("ab") as log:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                subprocess, "DETACHED_PROCESS", 0
            )
            process = subprocess.Popen(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                env=_process_environment(),
            )
        else:
            process = subprocess.Popen(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=_process_environment(),
            )
    identity = None
    for _ in range(40):
        identity = _process_identity(process.pid)
        if identity:
            break
        time.sleep(0.05)
    if not identity:
        with contextlib.suppress(OSError):
            process.terminate()
        raise RuntimeError("worker process started but its identity could not be verified")
    _write_pid(process.pid, identity)


def _stop_process() -> None:
    pid = _read_pid()
    if not pid:
        worker_pid_path().unlink(missing_ok=True)
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not _pid_is_running(pid):
            break
        time.sleep(0.1)
    else:
        if _read_pid() == pid:
            force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
            os.kill(pid, force_signal)
    worker_pid_path().unlink(missing_ok=True)


def install_service(*, start: bool = True) -> dict[str, Any]:
    launcher = install_launcher()
    changed_path_files = ensure_user_bin_on_path()
    worker_state_dir().mkdir(parents=True, exist_ok=True)
    kind = service_kind()
    if kind == "systemd":
        _stop_process()
        service_file = _write_systemd_unit()
        _run(["systemctl", "--user", "daemon-reload"])
        command = ["systemctl", "--user", "enable"]
        if start:
            command.append("--now")
        command.append(f"{_SERVICE_NAME}.service")
        _run(command)
    elif kind == "launchd":
        _stop_process()
        service_file = _write_launchd_plist()
        domain = f"gui/{_user_id()}"
        _run(["launchctl", "bootout", domain, str(service_file)], check=False)
        if start:
            _run(["launchctl", "bootstrap", domain, str(service_file)])
    else:
        service_file = None
        if start:
            _start_process()
    return {
        "kind": kind,
        "launcher": str(launcher),
        "service_file": str(service_file) if service_file else None,
        "path_files": [str(path) for path in changed_path_files],
        "started": start,
    }


def uninstall_service() -> dict[str, Any]:
    kind = service_kind()
    stop_service()
    if _systemd_unit_path().exists():
        _run(["systemctl", "--user", "disable", f"{_SERVICE_NAME}.service"], check=False)
        _systemd_unit_path().unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"], check=False)
    if _launchd_plist_path().exists():
        _launchd_plist_path().unlink(missing_ok=True)
    return {"kind": kind, "uninstalled": True}


def start_service() -> dict[str, Any]:
    kind = service_kind()
    if kind == "systemd" and _systemd_unit_path().exists():
        _run(["systemctl", "--user", "start", f"{_SERVICE_NAME}.service"])
    elif kind == "launchd" and _launchd_plist_path().exists():
        domain = f"gui/{_user_id()}"
        result = _run(["launchctl", "kickstart", "-k", f"{domain}/{_LAUNCHD_LABEL}"], check=False)
        if result.returncode:
            _run(["launchctl", "bootstrap", domain, str(_launchd_plist_path())])
    else:
        _start_process()
    return service_status()


def stop_service() -> dict[str, Any]:
    kind = service_kind()
    if kind == "systemd" and _systemd_unit_path().exists():
        _run(["systemctl", "--user", "stop", f"{_SERVICE_NAME}.service"], check=False)
    elif kind == "launchd" and _launchd_plist_path().exists():
        _run(
            ["launchctl", "bootout", f"gui/{_user_id()}", str(_launchd_plist_path())],
            check=False,
        )
    else:
        _stop_process()
    return service_status()


def service_status() -> dict[str, Any]:
    native_kind = service_kind()
    pid = None
    installed = False
    running = False
    detail = ""
    kind = native_kind
    if native_kind == "systemd" and _systemd_unit_path().exists():
        installed = True
        result = _run(
            ["systemctl", "--user", "is-active", f"{_SERVICE_NAME}.service"],
            check=False,
        )
        running = result.returncode == 0 and result.stdout.strip() == "active"
        detail = result.stdout.strip() or result.stderr.strip()
    elif native_kind == "launchd" and _launchd_plist_path().exists():
        installed = True
        result = _run(
            ["launchctl", "print", f"gui/{_user_id()}/{_LAUNCHD_LABEL}"],
            check=False,
        )
        running = result.returncode == 0
        detail = result.stdout.strip() or result.stderr.strip()
    else:
        kind = "process"
        installed = worker_launcher_path().exists()
        pid = _read_pid()
        running = pid is not None
    return {
        "kind": kind,
        "installed": installed,
        "running": running,
        "pid": pid,
        "detail": detail,
        "launcher": str(worker_launcher_path()),
        "log": str(worker_log_path()),
    }
