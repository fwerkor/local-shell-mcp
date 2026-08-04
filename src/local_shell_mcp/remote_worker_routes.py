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
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "schema_version": 1,
        "bundle_version": __version__,
        "sha256": digest,
        "size": len(payload),
        "url": server + remote.REMOTE_WORKER_BUNDLE_PATH + f"?sha256={digest}",
    }


async def worker_bundle(request: Any):  # noqa: ANN201
    from starlette.responses import JSONResponse, Response

    query = getattr(request, "query_params", {}) if request is not None else {}
    if query.get("manifest") == "1":
        return JSONResponse(_worker_manifest_data(), headers={"Cache-Control": "no-store"})
    return Response(
        worker_bundle_bytes(),
        media_type="application/gzip",
        headers={"Cache-Control": "no-store"},
    )


async def worker_manifest(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import JSONResponse

    return JSONResponse(_worker_manifest_data(), headers={"Cache-Control": "no-store"})


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


async def powershell_join_script(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import PlainTextResponse

    settings = get_settings()
    server = (settings.public_base_url or f"http://{settings.host}:{settings.port}").rstrip("/")
    script = r'''param(
  [Parameter(Mandatory = $true)][string]$Invite,
  [string]$Name = "",
  [string]$Workdir = "",
  [switch]$Background,
  [switch]$Persist
)
$ErrorActionPreference = "Stop"
$Server = __SERVER__
$ManifestUrl = "$Server__PUBLIC_MANIFEST_URL__"
if (-not $Workdir) { $Workdir = (Get-Location).Path }

$PythonExe = $null
$PythonPrefix = @()
$PythonCandidates = @(
  [pscustomobject]@{ Name = "python.exe"; Prefix = @() }
  [pscustomobject]@{ Name = "py.exe"; Prefix = @("-3") }
)
foreach ($Candidate in $PythonCandidates) {
  $PythonCommand = Get-Command $Candidate.Name -ErrorAction SilentlyContinue
  if ($null -eq $PythonCommand) { continue }
  $ProbeArgs = @($Candidate.Prefix) + @(
    "-c",
    "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
  )
  & $PythonCommand.Source @ProbeArgs
  if ($LASTEXITCODE -eq 0) {
    $PythonExe = $PythonCommand.Source
    $PythonPrefix = @($Candidate.Prefix)
    break
  }
}
if ($null -eq $PythonExe) { throw "Python 3.11 or newer is required" }

$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("local-shell-mcp-worker-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempDir | Out-Null
try {
  $Manifest = (Invoke-WebRequest -UseBasicParsing -Uri $ManifestUrl).Content | ConvertFrom-Json
  $BundleUrl = [string]$Manifest.url
  $RemoteDigest = ([string]$Manifest.sha256).ToLowerInvariant()
  $RemoteVersion = [string]$Manifest.bundle_version
  if ($env:LOCAL_SHELL_MCP_WORKER_STATE_DIR) {
    $StateHome = $env:LOCAL_SHELL_MCP_WORKER_STATE_DIR
  } else {
    $StateHome = Join-Path $HOME ".local\state\local-shell-mcp-worker"
  }
  $RuntimeRoot = Join-Path $TempDir "runtime"
  $Persistent = $Background -or $Persist
  if ($Persistent) {
    $RuntimeRoot = Join-Path $StateHome "runtime"
    $DigestPath = Join-Path $StateHome "bundle.sha256"
    $LocalDigest = ""
    if (Test-Path $DigestPath) { $LocalDigest = (Get-Content -Raw $DigestPath).Trim() }
    $RuntimePackage = Join-Path $RuntimeRoot "local_shell_mcp"
    if (-not (Test-Path $RuntimePackage) -or $LocalDigest -ne $RemoteDigest) {
      Write-Host "Downloading worker bundle..."
      $BundlePath = Join-Path $TempDir "worker.tgz"
      Invoke-WebRequest -UseBasicParsing -Uri $BundleUrl -OutFile $BundlePath
      $ActualDigest = (Get-FileHash -Algorithm SHA256 $BundlePath).Hash.ToLowerInvariant()
      if ($ActualDigest -ne $RemoteDigest) { throw "worker bundle checksum mismatch" }
      New-Item -ItemType Directory -Force -Path $StateHome | Out-Null
      $RuntimeNext = "$RuntimeRoot.next.$PID"
      $RuntimePrevious = "$RuntimeRoot.previous.$PID"
      Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $RuntimeNext, $RuntimePrevious
      New-Item -ItemType Directory -Path $RuntimeNext | Out-Null
      $ExtractArgs = @($PythonPrefix) + @(
        "-c",
        "import sys,tarfile; tarfile.open(sys.argv[1], 'r:gz').extractall(sys.argv[2])",
        $BundlePath,
        $RuntimeNext
      )
      & $PythonExe @ExtractArgs
      if ($LASTEXITCODE -ne 0) { throw "worker bundle extraction failed" }
      if (Test-Path $RuntimeRoot) { Move-Item $RuntimeRoot $RuntimePrevious }
      try {
        Move-Item $RuntimeNext $RuntimeRoot
      } catch {
        if (Test-Path $RuntimePrevious) { Move-Item $RuntimePrevious $RuntimeRoot }
        throw
      }
      Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $RuntimePrevious
      Set-Content -Encoding Ascii -Path $DigestPath -Value $RemoteDigest
    } else {
      Write-Host "Worker bundle is already current ($RemoteVersion)."
    }
  } else {
    Write-Host "Downloading worker bundle..."
    $BundlePath = Join-Path $TempDir "worker.tgz"
    Invoke-WebRequest -UseBasicParsing -Uri $BundleUrl -OutFile $BundlePath
    $ActualDigest = (Get-FileHash -Algorithm SHA256 $BundlePath).Hash.ToLowerInvariant()
    if ($ActualDigest -ne $RemoteDigest) { throw "worker bundle checksum mismatch" }
    New-Item -ItemType Directory -Path $RuntimeRoot | Out-Null
    $ExtractArgs = @($PythonPrefix) + @(
      "-c",
      "import sys,tarfile; tarfile.open(sys.argv[1], 'r:gz').extractall(sys.argv[2])",
      $BundlePath,
      $RuntimeRoot
    )
    & $PythonExe @ExtractArgs
    if ($LASTEXITCODE -ne 0) { throw "worker bundle extraction failed" }
  }

  $env:LOCAL_SHELL_MCP_WORKER_STATE_DIR = $StateHome
  $WorkerPythonPath = "$RuntimeRoot;$RuntimeRoot\vendor"
  if ($env:PYTHONPATH) { $WorkerPythonPath += ";$env:PYTHONPATH" }
  $env:PYTHONPATH = $WorkerPythonPath
  $EnrollArgs = @($PythonPrefix) + @(
    "-m", "local_shell_mcp.remote_worker", "enroll",
    "--server", $Server,
    "--invite-stdin",
    "--workdir", $Workdir,
    "--runtime-digest", $RemoteDigest,
    "--runtime-version", $RemoteVersion
  )
  if ($Name) { $EnrollArgs += @("--name", $Name) }
  $Invite | & $PythonExe @EnrollArgs
  if ($LASTEXITCODE -ne 0) { throw "worker enrollment failed" }
  $Invite = $null

  if ($Persist) {
    $InstallArgs = @($PythonPrefix) + @("-m", "local_shell_mcp.remote_worker", "install-service")
    & $PythonExe @InstallArgs
    if ($LASTEXITCODE -ne 0) { throw "worker service installation failed" }
    if ($env:LOCAL_SHELL_MCP_WORKER_BIN_DIR) {
      $WorkerBinDir = $env:LOCAL_SHELL_MCP_WORKER_BIN_DIR
    } else {
      $WorkerBinDir = Join-Path $HOME ".local\bin"
    }
    $env:PATH = "$WorkerBinDir;$env:PATH"
    Write-Host "local-shell-mcp worker installed and started."
    Write-Host "Management: local-shell-mcp worker status"
    return
  }
  if ($Background) {
    $LauncherArgs = @($PythonPrefix) + @("-m", "local_shell_mcp.remote_worker", "install-launcher")
    & $PythonExe @LauncherArgs
    if ($LASTEXITCODE -ne 0) { throw "worker launcher installation failed" }
    $StartArgs = @($PythonPrefix) + @("-m", "local_shell_mcp.remote_worker", "start")
    & $PythonExe @StartArgs
    if ($LASTEXITCODE -ne 0) { throw "worker startup failed" }
    if ($env:LOCAL_SHELL_MCP_WORKER_BIN_DIR) {
      $WorkerBinDir = $env:LOCAL_SHELL_MCP_WORKER_BIN_DIR
    } else {
      $WorkerBinDir = Join-Path $HOME ".local\bin"
    }
    $env:PATH = "$WorkerBinDir;$env:PATH"
    Write-Host "local-shell-mcp worker started in background."
    Write-Host "Management: local-shell-mcp worker status"
    return
  }
  $RunArgs = @($PythonPrefix) + @("-m", "local_shell_mcp.remote_worker", "run")
  & $PythonExe @RunArgs
  if ($LASTEXITCODE -ne 0) { throw "worker exited with status $LASTEXITCODE" }
} finally {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $TempDir
}
'''
    script = script.replace("__SERVER__", remote._powershell_quote(server))  # noqa: SLF001
    script = script.replace("__PUBLIC_MANIFEST_URL__", REMOTE_WORKER_PUBLIC_MANIFEST_URL)
    return PlainTextResponse(script, media_type="text/plain")


def remote_routes() -> list[Any]:
    from starlette.routing import Route

    return [
        Route(remote.REMOTE_JOIN_PATH, join_script, methods=["GET"]),
        Route(remote.REMOTE_POWERSHELL_JOIN_PATH, powershell_join_script, methods=["GET"]),
        Route(REMOTE_WORKER_MANIFEST_PATH, worker_manifest, methods=["GET"]),
        Route(remote.REMOTE_WORKER_BUNDLE_PATH, worker_bundle, methods=["GET"]),
        Route(f"{remote.REMOTE_API_PREFIX}/register", remote.register_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/resume", remote.resume_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/poll", remote.poll_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/heartbeat", remote.heartbeat_endpoint, methods=["POST"]),
        Route(f"{remote.REMOTE_API_PREFIX}/result", remote.result_endpoint, methods=["POST"]),
        *remote_transfer_routes(),
    ]
