from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import remote
from .remote_worker_bootstrap import (
    _RESTART_PROTOCOL_ENV,
    _WORKER_LOCK_BUSY_EXIT,
    _WORKER_RESTART_EXIT,
    WorkerRestartRequested,
    needs_worker_reaper,
    supervise_worker,
)
from .remote_worker_installer import install_or_update_runtime, rollback_pending_runtime
from .remote_worker_service import (
    WorkerAlreadyRunningError,
    _wait_for_windows_worker_unlock,
    cancel_worker_lock_reexec,
    install_service,
    prepare_worker_lock_reexec,
    prepare_worker_service_environment,
    refresh_installed_service_definition,
    service_status,
    start_service,
    stop_service,
    uninstall_service,
    worker_run_lock,
)
from .remote_worker_state import (
    ensure_user_bin_on_path,
    install_launcher,
    read_worker_config,
    worker_bootstrap_path,
    worker_state_dir,
    write_worker_config,
)
from .shell_environment import is_frozen_app


def _read_invite(args: argparse.Namespace) -> str:
    invite = str(getattr(args, "invite", "") or "")
    if getattr(args, "invite_stdin", False):
        invite = sys.stdin.readline().strip()
    if not invite:
        raise ValueError("an invite is required; pass --invite or --invite-stdin")
    return invite


def _worker_payload(name: str | None, workdir: str, invite: str) -> dict[str, Any]:
    return {
        "invite": invite,
        "enrollment_id": secrets.token_urlsafe(24),
        "name": name,
        "workdir": workdir,
        "capabilities": remote.worker_capabilities(),
        "info": remote.worker_info(workdir),
    }


def _enrollment_payload(name: str | None, workdir: str, invite: str) -> dict[str, Any]:
    from .settings import get_settings

    temporary_environment = {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": workdir,
        "LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER": "true",
    }
    previous_environment = {
        variable: os.environ.get(variable) for variable in temporary_environment
    }
    present_environment = set(os.environ).intersection(temporary_environment)
    for variable, value in temporary_environment.items():
        os.environ[variable] = value
    get_settings.cache_clear()
    try:
        return _worker_payload(name, workdir, invite)
    finally:
        for variable, previous in previous_environment.items():
            if variable in present_environment:
                os.environ[variable] = previous or ""
            else:
                os.environ.pop(variable, None)
        get_settings.cache_clear()


async def enroll_worker(
    *,
    server: str,
    invite: str,
    name: str | None = None,
    workdir: str | None = None,
    runtime_digest: str = "",
    runtime_version: str = "",
) -> dict[str, Any]:
    server = server.rstrip("/")
    resolved_workdir = str(Path(workdir or os.getcwd()).expanduser().resolve())
    payload = _enrollment_payload(name, resolved_workdir, invite)
    identity = remote._read_worker_identity(server, name)  # noqa: SLF001
    body: dict[str, Any] | None = None
    access = ""
    if identity:
        access = str(identity["access"])
        headers = {"Authorization": "Bearer " + access}
        # The controller owns the canonical name for an enrolled token.  A
        # controller-side rename can make the locally cached name stale, so let
        # resume resolve the token without asserting the old name.
        resume_payload = {**payload, "name": None}
        body = await remote._worker_resume_or_none(  # noqa: SLF001
            f"{server}{remote.REMOTE_API_PREFIX}/resume", resume_payload, headers, 30
        )
    if body is None:
        body = await remote._worker_post_json_forever(  # noqa: SLF001
            f"{server}{remote.REMOTE_API_PREFIX}/register", payload, None, 30, "register"
        )
        if not body.get("ok"):
            raise RuntimeError(body.get("message") or body)
        data = body["data"]
        access = str(data["token"])
    elif not body.get("ok"):
        raise RuntimeError(body.get("message") or body)
    else:
        data = body["data"]
    machine_name = str(data["name"])
    remote._write_worker_identity(  # noqa: SLF001
        {"server": server, "name": machine_name, "access": access, "workdir": resolved_workdir}
    )
    config = write_worker_config(
        server=server,
        name=machine_name,
        workdir=resolved_workdir,
        runtime_digest=runtime_digest,
        runtime_version=runtime_version,
    )
    return config


def _load_config_or_migrate() -> dict[str, Any]:
    try:
        return read_worker_config()
    except FileNotFoundError:
        path = remote._worker_identity_path()  # noqa: SLF001
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("stored worker identity is invalid") from None
        return write_worker_config(
            server=str(data.get("server") or ""),
            name=str(data.get("name") or ""),
            workdir=str(data.get("workdir") or os.getcwd()),
        )


async def run_enrolled_worker() -> None:
    config = _load_config_or_migrate()
    identity = remote._read_worker_identity(str(config["server"]))  # noqa: SLF001
    if not identity:
        raise RuntimeError("worker identity is missing or invalid; run the join command again")
    await remote.run_worker(
        str(config["server"]),
        "",
        str(identity.get("name") or config.get("name") or "") or None,
        str(config.get("workdir") or "") or None,
    )


def _worker_run_exec_argv() -> list[str]:
    if is_frozen_app():
        return [sys.executable, "worker", "run"]
    return [sys.executable, "-m", "local_shell_mcp.remote_worker", "run"]


def _reexec_worker_run() -> None:
    argv = _worker_run_exec_argv()
    lock_fd = prepare_worker_lock_reexec()
    try:
        os.execv(argv[0], argv)
    finally:
        cancel_worker_lock_reexec(lock_fd)


async def _connect(args: argparse.Namespace) -> None:
    with worker_run_lock():
        await enroll_worker(
            server=args.server,
            invite=_read_invite(args),
            name=args.name,
            workdir=args.workdir,
            runtime_digest=args.runtime_digest,
            runtime_version=args.runtime_version,
        )
        if sys.platform != "win32":
            _reexec_worker_run()
    if sys.platform == "win32":
        # Initial enrollment is complete. Do not carry a Windows region
        # lock (or invitation arguments) into the new worker process.
        _reexec_worker_run()


def _restart_windows_worker() -> None:
    if os.environ.get(_RESTART_PROTOCOL_ENV) == "1":
        raise SystemExit(_WORKER_RESTART_EXIT)
    # A directly invoked wheel or a legacy supervisor cannot understand the
    # restart status. Bridge once to the newly installed standalone supervisor
    # *after* the worker lock has been released. Its children use the protocol.
    # Wait for it so the original venv/task process remains tracked.
    env = os.environ.copy()
    env.pop("LOCAL_SHELL_MCP_WORKER_LOCK_FD", None)
    result = subprocess.run([sys.executable, str(worker_bootstrap_path())], env=env, check=False)
    raise SystemExit(result.returncode)


def _prepare_windows_maintenance() -> None:
    _wait_for_windows_worker_unlock()
    # Recover a previously interrupted trial only after the old worker has
    # stopped. Refresh the trusted bootstrap before staging another candidate.
    attempted = worker_state_dir() / "runtime.attempted"
    if attempted.exists():
        rollback_pending_runtime()
        attempted.unlink(missing_ok=True)
    install_launcher()


def _prepare_worker_start() -> None:
    config = _load_config_or_migrate()
    if sys.platform == "win32":
        _prepare_windows_maintenance()
    install_or_update_runtime(str(config["server"]))
    install_launcher()
    ensure_user_bin_on_path()
    refresh_installed_service_definition()


def _add_enrollment_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", required=True)
    invite = parser.add_mutually_exclusive_group(required=True)
    invite.add_argument("--invite")
    invite.add_argument("--invite-stdin", action="store_true")
    parser.add_argument("--name", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--runtime-digest", default="")
    parser.add_argument("--runtime-version", default="")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the local-shell-mcp remote worker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_enrollment_arguments(subparsers.add_parser("enroll", help="register this machine once"))
    _add_enrollment_arguments(
        subparsers.add_parser("connect", help="register if needed and run in the foreground")
    )
    subparsers.add_parser("run", help="run using the stored worker identity")
    subparsers.add_parser("start", help="start the installed worker")
    subparsers.add_parser("stop", help="stop the installed worker")
    subparsers.add_parser("restart", help="restart the installed worker")
    subparsers.add_parser("status", help="show worker service status")
    update = subparsers.add_parser("update", help="update the cached worker runtime")
    update.add_argument("--force", action="store_true")
    install = subparsers.add_parser("install-service", help="install the user service")
    install.add_argument("--no-start", action="store_true")
    subparsers.add_parser("uninstall-service", help="remove the user service")
    subparsers.add_parser("install-launcher", help="install the management command and PATH entry")
    return parser


def _print_result(result: Any) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def _run_command(args: argparse.Namespace) -> None:
    if args.command == "enroll":
        result = asyncio.run(
            enroll_worker(
                server=args.server,
                invite=_read_invite(args),
                name=args.name,
                workdir=args.workdir,
                runtime_digest=args.runtime_digest,
                runtime_version=args.runtime_version,
            )
        )
        _print_result(result)
    elif args.command == "connect":
        asyncio.run(_connect(args))
    elif args.command == "run":
        prepare_worker_service_environment()
        asyncio.run(run_enrolled_worker())
    elif args.command == "start":
        if sys.platform == "win32":
            before = service_status()
            if before["running"]:
                _print_result(before)
                return
        _prepare_worker_start()
        _print_result(start_service())
    elif args.command == "stop":
        _print_result(stop_service())
    elif args.command == "restart":
        stop_service()
        _prepare_worker_start()
        _print_result(start_service())
    elif args.command == "status":
        _print_result(service_status())
    elif args.command == "update":
        config = _load_config_or_migrate()
        before = service_status()
        if sys.platform == "win32" and (before["running"] or before.get("installed")):
            stop_service()
        try:
            if sys.platform == "win32":
                _prepare_windows_maintenance()
            result = install_or_update_runtime(str(config["server"]), force=args.force)
            install_launcher()
            if result["updated"]:
                refresh_installed_service_definition()
        except Exception:
            if sys.platform == "win32" and before["running"]:
                start_service()
            raise
        if before["running"]:
            if sys.platform == "win32":
                start_service()
            elif result["updated"]:
                stop_service()
                start_service()
        _print_result(result)
    elif args.command == "install-service":
        config = _load_config_or_migrate()
        if sys.platform == "win32":
            before = service_status()
            if before["running"] or before.get("installed"):
                stop_service()
            _prepare_windows_maintenance()
        install_or_update_runtime(str(config["server"]))
        _print_result(install_service(start=not args.no_start))
    elif args.command == "uninstall-service":
        _print_result(uninstall_service())
    elif args.command == "install-launcher":
        launcher = install_launcher()
        changed = ensure_user_bin_on_path()
        _print_result({"launcher": str(launcher), "path_files": [str(path) for path in changed]})
    else:  # pragma: no cover - argparse enforces the command choices
        raise AssertionError(args.command)


def run_worker_cli(argv: list[str] | None = None) -> None:
    # The full Controller CLI also dispatches worker commands here.  Restore
    # its SQLite setting when a short-lived CLI invocation returns.
    old_backend = os.environ.get("LOCAL_SHELL_MCP_STATE_BACKEND")
    os.environ["LOCAL_SHELL_MCP_STATE_BACKEND"] = "file"
    from .settings import get_settings

    get_settings.cache_clear()
    try:
        argv = sys.argv[1:] if argv is None else list(argv)
        try:
            args = _parser().parse_args(argv)
            if args.command in {"run", "connect"} and needs_worker_reaper():
                raise SystemExit(supervise_worker([*_worker_run_exec_argv()[:-1], *argv]))
            _run_command(args)
        except WorkerRestartRequested:
            _restart_windows_worker()
        except WorkerAlreadyRunningError as exc:
            print(f"Status: worker command failed: {exc}", file=sys.stderr, flush=True)
            raise SystemExit(_WORKER_LOCK_BUSY_EXIT) from None
        except KeyboardInterrupt:
            print("\nStatus: disconnected by user.", file=sys.stderr, flush=True)
            raise SystemExit(130) from None
        except Exception as exc:  # noqa: BLE001
            print(f"Status: worker command failed: {exc}", file=sys.stderr, flush=True)
            raise SystemExit(1) from None
    finally:
        if old_backend is None:
            os.environ.pop("LOCAL_SHELL_MCP_STATE_BACKEND", None)
        else:
            os.environ["LOCAL_SHELL_MCP_STATE_BACKEND"] = old_backend
        get_settings.cache_clear()
