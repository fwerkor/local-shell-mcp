from __future__ import annotations

import functools
import gzip
import hashlib
import io
import shlex
import tarfile
from pathlib import Path
from typing import Any

from . import __version__, remote
from .remote_transfer import remote_transfer_routes
from .settings import get_settings

REMOTE_WORKER_MANIFEST_PATH = "/remote/worker-manifest.json"
REMOTE_WORKER_PUBLIC_MANIFEST_URL = remote.REMOTE_WORKER_BUNDLE_PATH + "?manifest=1"


def _normalized_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


@functools.lru_cache(maxsize=1)
def worker_bundle_bytes() -> bytes:
    package_root = Path(remote.__file__).resolve().parent
    buffer = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as tar,
    ):
        for path in sorted(package_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(package_root)
            is_python = path.suffix == ".py"
            is_helper = relative.parts[:1] == ("helpers",) and path.name in {
                "tmux",
                "tmux.LICENSE",
            }
            if is_python or is_helper:
                tar.add(
                    path,
                    arcname=str(path.relative_to(package_root.parent)),
                    filter=_normalized_tar_info,
                )
        seen: set[str] = set()
        for dist_name in remote.REMOTE_WORKER_DISTRIBUTIONS:
            remote._add_distribution_to_tar(tar, dist_name, seen)  # noqa: SLF001
    return buffer.getvalue()


def _worker_manifest_data() -> dict[str, Any]:
    settings = get_settings()
    server = (settings.public_base_url or f"http://{settings.host}:{settings.port}").rstrip("/")
    payload = worker_bundle_bytes()
    return {
        "schema_version": 1,
        "bundle_version": __version__,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "url": server + remote.REMOTE_WORKER_BUNDLE_PATH,
    }


async def worker_bundle(request: Any):  # noqa: ANN201
    from starlette.responses import JSONResponse, Response

    query = getattr(request, "query_params", {}) if request is not None else {}
    if query.get("manifest") == "1":
        return JSONResponse(_worker_manifest_data())
    return Response(worker_bundle_bytes(), media_type="application/gzip")


async def worker_manifest(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import JSONResponse

    return JSONResponse(_worker_manifest_data())


async def join_script(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import PlainTextResponse

    settings = get_settings()
    server = (settings.public_base_url or f"http://{settings.host}:{settings.port}").rstrip("/")
    script = r'''#!/usr/bin/env bash
set -euo pipefail
SERVER=__SERVER__
MANIFEST_URL="$SERVER__PUBLIC_MANIFEST_URL__"
INVITE=""
NAME=""
WORKDIR=""
BACKGROUND=0
PERSIST=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --invite) INVITE="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --workdir) WORKDIR="${2:-}"; shift 2 ;;
    --background) BACKGROUND=1; shift ;;
    --persist) PERSIST=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$INVITE" ]; then echo "--invite is required" >&2; exit 2; fi
if [ -z "$WORKDIR" ]; then WORKDIR="$PWD"; fi
if ! command -v python3 >/dev/null 2>&1; then echo "python3 is required" >&2; exit 2; fi
if ! command -v curl >/dev/null 2>&1; then echo "curl is required" >&2; exit 2; fi
if ! command -v tar >/dev/null 2>&1; then echo "tar is required" >&2; exit 2; fi
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT
curl -fsSL "$MANIFEST_URL" -o "$TMPDIR/manifest.json"
manifest_value() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$TMPDIR/manifest.json" "$1"
}
BUNDLE_URL="$(manifest_value url)"
REMOTE_DIGEST="$(manifest_value sha256)"
REMOTE_VERSION="$(manifest_value bundle_version)"
STATE_HOME="${LOCAL_SHELL_MCP_WORKER_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/local-shell-mcp-worker}"
RUNTIME_ROOT="$TMPDIR/runtime"
if [ "$BACKGROUND" = "1" ] || [ "$PERSIST" = "1" ]; then
  RUNTIME_ROOT="$STATE_HOME/runtime"
  LOCAL_DIGEST=""
  if [ -f "$STATE_HOME/bundle.sha256" ]; then LOCAL_DIGEST="$(cat "$STATE_HOME/bundle.sha256")"; fi
  if [ ! -d "$RUNTIME_ROOT/local_shell_mcp" ] || [ "$LOCAL_DIGEST" != "$REMOTE_DIGEST" ]; then
    echo "Downloading worker bundle..." >&2
    curl -fL --progress-bar "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
    ACTUAL_DIGEST="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$TMPDIR/worker.tgz")"
    if [ "$ACTUAL_DIGEST" != "$REMOTE_DIGEST" ]; then
      echo "worker bundle checksum mismatch" >&2
      exit 1
    fi
    mkdir -p "$STATE_HOME"
    RUNTIME_NEXT="$STATE_HOME/runtime.next.$$"
    RUNTIME_PREVIOUS="$STATE_HOME/runtime.previous.$$"
    rm -rf "$RUNTIME_NEXT" "$RUNTIME_PREVIOUS"
    mkdir -p "$RUNTIME_NEXT"
    tar -xzf "$TMPDIR/worker.tgz" -C "$RUNTIME_NEXT"
    if [ -d "$RUNTIME_ROOT" ]; then mv "$RUNTIME_ROOT" "$RUNTIME_PREVIOUS"; fi
    if ! mv "$RUNTIME_NEXT" "$RUNTIME_ROOT"; then
      if [ -d "$RUNTIME_PREVIOUS" ]; then mv "$RUNTIME_PREVIOUS" "$RUNTIME_ROOT"; fi
      exit 1
    fi
    rm -rf "$RUNTIME_PREVIOUS"
    printf '%s\n' "$REMOTE_DIGEST" > "$STATE_HOME/bundle.sha256"
  else
    echo "Worker bundle is already current ($REMOTE_VERSION)." >&2
  fi
else
  echo "Downloading worker bundle..." >&2
  curl -fL --progress-bar "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
  ACTUAL_DIGEST="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$TMPDIR/worker.tgz")"
  if [ "$ACTUAL_DIGEST" != "$REMOTE_DIGEST" ]; then
    echo "worker bundle checksum mismatch" >&2
    exit 1
  fi
  mkdir -p "$RUNTIME_ROOT"
  tar -xzf "$TMPDIR/worker.tgz" -C "$RUNTIME_ROOT"
fi
export PYTHONPATH="$RUNTIME_ROOT:$RUNTIME_ROOT/vendor${PYTHONPATH:+:$PYTHONPATH}"
ENROLL_ARGS=(enroll --server "$SERVER" --invite-stdin --workdir "$WORKDIR" --runtime-digest "$REMOTE_DIGEST" --runtime-version "$REMOTE_VERSION")
if [ -n "$NAME" ]; then ENROLL_ARGS+=(--name "$NAME"); fi
printf '%s\n' "$INVITE" | python3 -m local_shell_mcp.remote_worker "${ENROLL_ARGS[@]}"
unset INVITE
if [ "$PERSIST" = "1" ]; then
  python3 -m local_shell_mcp.remote_worker install-service
  export PATH="$HOME/.local/bin:$PATH"
  echo "local-shell-mcp worker installed and started."
  echo "Management: local-shell-mcp worker status"
  exit 0
fi
if [ "$BACKGROUND" = "1" ]; then
  python3 -m local_shell_mcp.remote_worker install-launcher
  python3 -m local_shell_mcp.remote_worker start
  export PATH="$HOME/.local/bin:$PATH"
  echo "local-shell-mcp worker started in background."
  echo "Management: local-shell-mcp worker status"
  exit 0
fi
exec python3 -m local_shell_mcp.remote_worker run
'''
    script = script.replace("__SERVER__", shlex.quote(server))
    script = script.replace("__PUBLIC_MANIFEST_URL__", REMOTE_WORKER_PUBLIC_MANIFEST_URL)
    return PlainTextResponse(script, media_type="text/x-shellscript")


def remote_routes() -> list[Any]:
    from starlette.routing import Route

    return [
        Route(remote.REMOTE_JOIN_PATH, join_script, methods=["GET"]),
        Route(REMOTE_WORKER_MANIFEST_PATH, worker_manifest, methods=["GET"]),
        Route(remote.REMOTE_WORKER_BUNDLE_PATH, worker_bundle, methods=["GET"]),
        Route(f"{remote.REMOTE_API_PREFIX}/register", remote.register_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/resume", remote.resume_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/poll", remote.poll_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/heartbeat", remote.heartbeat_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/result", remote.result_endpoint, methods=["POST"]),
        *remote_transfer_routes(),
    ]
