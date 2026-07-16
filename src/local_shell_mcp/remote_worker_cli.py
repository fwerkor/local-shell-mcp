from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import remote
from .remote_worker_installer import install_or_update_runtime
from .remote_worker_service import (
    install_service,
    service_status,
    start_service,
    stop_service,
    uninstall_service,
)
from .remote_worker_state import (
    ensure_user_bin_on_path,
    install_launcher,
    read_worker_config,
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
        resume_payload = {**payload, "name": str(identity["name"])}
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
    identity = remote._read_worker_identity(
        str(config["server"]), str(config.get("name") or "")
    )  # noqa: SLF001
    if not identity:
        raise RuntimeError("worker identity is missing or invalid; run the join command again")
    await remote.run_worker(
        str(config["server"]),
        "",
        str(config.get("name") or "") or None,
        str(config.get("workdir") or "") or None,
    )


def _worker_run_exec_argv() -> list[str]:
    if is_frozen_app():
        return [sys.executable, "worker", "run"]
    return [sys.executable, "-m", "local_shell_mcp.main", "worker", "run"]


def _reexec_worker_run() -> None:
    argv = _worker_run_exec_argv()
    os.execv(argv[0], argv)


async def _connect(args: argparse.Namespace) -> None:
    await enroll_worker(
        server=args.server,
        invite=_read_invite(args),
        name=args.name,
        workdir=args.workdir,
        runtime_digest=args.runtime_digest,
        runtime_version=args.runtime_version,
    )
    _reexec_worker_run()


def _prepare_worker_start() -> None:
    config = _load_config_or_migrate()
    install_or_update_runtime(str(config["server"]))
    install_launcher()
    ensure_user_bin_on_path()


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
        asyncio.run(run_enrolled_worker())
    elif args.command == "start":
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
        result = install_or_update_runtime(str(config["server"]), force=args.force)
        if result["updated"] and before["running"]:
            stop_service()
            start_service()
        _print_result(result)
    elif args.command == "install-service":
        config = _load_config_or_migrate()
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
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0].startswith("-"):
        remote.run_worker_cli(argv)
        return
    try:
        _run_command(_parser().parse_args(argv))
    except KeyboardInterrupt:
        print("\nStatus: disconnected by user.", file=sys.stderr, flush=True)
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001
        print(f"Status: worker command failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
