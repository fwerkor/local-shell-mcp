from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .remote import (
    REMOTE_API_PREFIX,
    REMOTE_JOIN_PATH,
    REMOTE_WORKER_BUNDLE_PATH,
    _worker_post_json_forever,
    _write_worker_identity,
    run_worker,
    worker_bundle,
    worker_capabilities,
    worker_info,
)
from .remote import remote_routes as legacy_remote_routes
from .remote import run_worker_cli as legacy_run_worker_cli

WORKER_MANIFEST_PATH = "/remote/worker-manifest.json"
WORKER_CONFIG_FILE_NAME = "config.json"
WORKER_PID_FILE_NAME = "worker.pid"
WORKER_LOG_FILE_NAME = "worker.log"
PATH_MARKER = "# local-shell-mcp user bin"


def worker_state_dir() -> Path:
    configured = os.getenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "local-shell-mcp-worker"
    return Path.home() / ".local" / "state" / "local-shell-mcp-worker"


def worker_config_path() -> Path:
    return worker_state_dir() / WORKER_CONFIG_FILE_NAME


def worker_pid_path() -> Path:
    return worker_state_dir() / WORKER_PID_FILE_NAME


def worker_log_path() -> Path:
    return worker_state_dir() / WORKER_LOG_FILE_NAME


def read_worker_config() -> dict[str, Any]:
    path = worker_config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("worker is not installed; run the persistent join command first") from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"worker configuration is unreadable: {path}") from exc
    if not isinstance(data, dict) or int(data.get("version") or 0) != 1:
        raise RuntimeError(f"unsupported worker configuration: {path}")
    for key in ("server", "name", "workdir"):
        if not str(data.get(key) or "").strip():
            raise RuntimeError(f"worker configuration is missing {key}: {path}")
    return data


def write_worker_config(data: dict[str, Any]) -> None:
    path = worker_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    tmp.replace(path)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_worker_pid() -> int | None:
    try:
        pid = int(worker_pid_path().read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    if _pid_is_running(pid):
        return pid
    worker_pid_path().unlink(missing_ok=True)
    return None


def _runtime_pythonpath() -> str:
    root = worker_state_dir() / "runtime"
    return os.pathsep.join((str(root), str(root / "vendor")))


def _worker_command() -> list[str]:
    return [sys.executable, "-m", "local_shell_mcp.remote_worker", "run"]


def start_worker() -> int:
    existing = read_worker_pid()
    if existing:
        return existing
    read_worker_config()
    state = worker_state_dir()
    state.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = _runtime_pythonpath() + (os.pathsep + current if current else "")
    with worker_log_path().open("ab") as log:
        process = subprocess.Popen(
            _worker_command(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    worker_pid_path().write_text(str(process.pid), encoding="utf-8")
    return process.pid


def stop_worker(timeout_s: float = 10.0) -> bool:
    pid = read_worker_pid()
    if not pid:
        return False
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_s
    while _pid_is_running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _pid_is_running(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    worker_pid_path().unlink(missing_ok=True)
    return True


def worker_status() -> dict[str, Any]:
    try:
        config: dict[str, Any] | None = read_worker_config()
    except RuntimeError:
        config = None
    pid = read_worker_pid()
    return {
        "installed": config is not None,
        "running": pid is not None,
        "pid": pid,
        "server": config.get("server") if config else None,
        "name": config.get("name") if config else None,
        "workdir": config.get("workdir") if config else None,
        "state_dir": str(worker_state_dir()),
        "log": str(worker_log_path()),
    }


async def enroll_worker(server: str, invite: str, name: str | None, workdir: str) -> dict[str, Any]:
    server = server.rstrip("/")
    workdir = str(Path(workdir).expanduser().resolve())
    payload = {
        "invite": invite,
        "name": name,
        "workdir": workdir,
        "capabilities": worker_capabilities(),
        "info": worker_info(workdir),
    }
    body = await _worker_post_json_forever(
        f"{server}{REMOTE_API_PREFIX}/register", payload, None, 30, "register"
    )
    if not body.get("ok"):
        raise RuntimeError(body.get("message") or body)
    data = body["data"]
    access = str(data["token"])
    machine_name = str(data["name"])
    _write_worker_identity(
        {"server": server, "name": machine_name, "access": access, "workdir": workdir}
    )
    config = {"version": 1, "server": server, "name": machine_name, "workdir": workdir}
    write_worker_config(config)
    return config


async def run_installed_worker() -> None:
    config = read_worker_config()
    await run_worker(
        str(config["server"]),
        "",
        str(config["name"]),
        str(config["workdir"]),
        False,
    )


async def worker_manifest(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import JSONResponse

    from . import __version__

    response = await worker_bundle(request)
    payload = bytes(response.body)
    return JSONResponse(
        {
            "schema_version": 1,
            "bundle_version": __version__,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "url": REMOTE_WORKER_BUNDLE_PATH,
        }
    )


def _join_script(server: str) -> str:
    return f'''#!/usr/bin/env bash
set -euo pipefail
SERVER={shlex.quote(server)}
BUNDLE_URL="$SERVER{REMOTE_WORKER_BUNDLE_PATH}"
MANIFEST_URL="$SERVER{WORKER_MANIFEST_PATH}"
INVITE=""
NAME=""
WORKDIR=""
BACKGROUND=0
PERSIST=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --invite) INVITE="${{2:-}}"; shift 2 ;;
    --name) NAME="${{2:-}}"; shift 2 ;;
    --workdir) WORKDIR="${{2:-}}"; shift 2 ;;
    --background) BACKGROUND=1; shift ;;
    --persist) PERSIST=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$INVITE" ] || {{ echo "--invite is required" >&2; exit 2; }}
[ -n "$WORKDIR" ] || WORKDIR="$PWD"
command -v python3 >/dev/null 2>&1 || {{ echo "python3 is required" >&2; exit 2; }}
command -v curl >/dev/null 2>&1 || {{ echo "curl is required" >&2; exit 2; }}
command -v tar >/dev/null 2>&1 || {{ echo "tar is required" >&2; exit 2; }}
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
if [ "$PERSIST" = "1" ]; then
  STATE_HOME="${{XDG_STATE_HOME:-$HOME/.local/state}}/local-shell-mcp-worker"
  RUNTIME="$STATE_HOME/runtime"
  mkdir -p "$STATE_HOME"
  curl -fsSL "$MANIFEST_URL" -o "$TMPDIR/manifest.json"
  EXPECTED="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$TMPDIR/manifest.json")"
  CURRENT="$(cat "$STATE_HOME/runtime.sha256" 2>/dev/null || true)"
  if [ "$CURRENT" != "$EXPECTED" ] || [ ! -d "$RUNTIME/local_shell_mcp" ]; then
    echo "Downloading worker bundle..." >&2
    curl -fL --progress-bar "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
    ACTUAL="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$TMPDIR/worker.tgz")"
    [ "$ACTUAL" = "$EXPECTED" ] || {{ echo "worker bundle checksum mismatch" >&2; exit 1; }}
    NEXT="$STATE_HOME/runtime.next.$$"
    rm -rf "$NEXT"
    mkdir -p "$NEXT"
    tar -xzf "$TMPDIR/worker.tgz" -C "$NEXT"
    rm -rf "$RUNTIME"
    mv "$NEXT" "$RUNTIME"
    printf '%s\n' "$EXPECTED" > "$STATE_HOME/runtime.sha256"
  else
    echo "Worker bundle is up to date." >&2
  fi
  BIN_DIR="$HOME/.local/bin"
  mkdir -p "$BIN_DIR"
  cat > "$BIN_DIR/local-shell-mcp" <<'EOF'
#!/bin/sh
STATE_HOME="${{XDG_STATE_HOME:-$HOME/.local/state}}/local-shell-mcp-worker"
export PYTHONPATH="$STATE_HOME/runtime:$STATE_HOME/runtime/vendor${{PYTHONPATH:+:$PYTHONPATH}}"
exec python3 -m local_shell_mcp.main "$@"
EOF
  chmod 755 "$BIN_DIR/local-shell-mcp"
  PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
  case "${{SHELL:-}}" in
    */zsh) RC="$HOME/.zshrc" ;;
    */bash) RC="$HOME/.bashrc" ;;
    *) RC="$HOME/.profile" ;;
  esac
  touch "$RC"
  grep -Fqx '{PATH_MARKER}' "$RC" || printf '\n%s\n%s\n' '{PATH_MARKER}' "$PATH_LINE" >> "$RC"
  export PATH="$BIN_DIR:$PATH"
  export PYTHONPATH="$RUNTIME:$RUNTIME/vendor${{PYTHONPATH:+:$PYTHONPATH}}"
  ARGS=(worker enroll --server "$SERVER" --invite "$INVITE" --workdir "$WORKDIR")
  [ -n "$NAME" ] && ARGS+=(--name "$NAME")
  "$BIN_DIR/local-shell-mcp" "${{ARGS[@]}}"
  "$BIN_DIR/local-shell-mcp" worker start
  echo "Persistent worker installed and started."
  echo "Management command: local-shell-mcp worker status"
  exit 0
fi
echo "Downloading worker bundle..." >&2
curl -fL --progress-bar "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
RUNTIME="$TMPDIR/runtime"
mkdir -p "$RUNTIME"
tar -xzf "$TMPDIR/worker.tgz" -C "$RUNTIME"
export PYTHONPATH="$RUNTIME:$RUNTIME/vendor${{PYTHONPATH:+:$PYTHONPATH}}"
ARGS=(--server "$SERVER" --invite "$INVITE" --workdir "$WORKDIR")
[ -n "$NAME" ] && ARGS+=(--name "$NAME")
if [ "$BACKGROUND" = "1" ]; then
  mkdir -p "$HOME/.local/state/local-shell-mcp-worker"
  nohup python3 -m local_shell_mcp.remote_worker "${{ARGS[@]}}" > "$HOME/.local/state/local-shell-mcp-worker/worker.log" 2>&1 &
  echo "local-shell-mcp worker started in background."
else
  exec python3 -m local_shell_mcp.remote_worker "${{ARGS[@]}}"
fi
'''


async def join_script(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import PlainTextResponse

    from .settings import get_settings

    settings = get_settings()
    server = (settings.public_base_url or f"http://{settings.host}:{settings.port}").rstrip("/")
    return PlainTextResponse(_join_script(server), media_type="text/x-shellscript")


def remote_routes() -> list[Any]:
    from starlette.routing import Route

    routes = [
        Route(REMOTE_JOIN_PATH, join_script, methods=["GET"])
        if getattr(route, "path", None) == REMOTE_JOIN_PATH
        else route
        for route in legacy_remote_routes()
    ]
    routes.append(Route(WORKER_MANIFEST_PATH, worker_manifest, methods=["GET"]))
    return routes


def _print_status(status: dict[str, Any]) -> None:
    print(f"Installed: {'yes' if status['installed'] else 'no'}")
    print(f"Running:   {'yes' if status['running'] else 'no'}")
    if status["pid"]:
        print(f"PID:       {status['pid']}")
    if status["server"]:
        print(f"Server:    {status['server']}")
    if status["name"]:
        print(f"Name:      {status['name']}")
    print(f"State:     {status['state_dir']}")
    print(f"Log:       {status['log']}")


def run_worker_cli(argv: list[str] | None = None) -> None:
    argv = list(argv or [])
    if argv and argv[0].startswith("-"):
        legacy_run_worker_cli(argv)
        return

    parser = argparse.ArgumentParser(description="Manage the local-shell-mcp remote worker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    enroll = subparsers.add_parser("enroll")
    enroll.add_argument("--server", required=True)
    enroll.add_argument("--invite", required=True)
    enroll.add_argument("--name", default=None)
    enroll.add_argument("--workdir", default=os.getcwd())
    for command in ("run", "start", "stop", "restart", "status"):
        subparsers.add_parser(command)

    args = parser.parse_args(argv)
    try:
        if args.command == "enroll":
            config = asyncio.run(enroll_worker(args.server, args.invite, args.name, args.workdir))
            print(f"Enrolled worker {config['name']} for {config['server']}")
        elif args.command == "run":
            asyncio.run(run_installed_worker())
        elif args.command == "start":
            print(f"Worker started with PID {start_worker()}")
        elif args.command == "stop":
            print("Worker stopped" if stop_worker() else "Worker is not running")
        elif args.command == "restart":
            stop_worker()
            print(f"Worker restarted with PID {start_worker()}")
        elif args.command == "status":
            _print_status(worker_status())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001
        print(f"Status: worker command failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


__all__ = [
    "WORKER_MANIFEST_PATH",
    "enroll_worker",
    "join_script",
    "read_worker_config",
    "remote_routes",
    "run_worker_cli",
    "start_worker",
    "stop_worker",
    "worker_manifest",
    "worker_status",
    "write_worker_config",
]
