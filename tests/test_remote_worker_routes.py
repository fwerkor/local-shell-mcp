from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote_worker_routes as routes
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_worker_bundle_and_manifest_are_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    routes.worker_bundle_bytes.cache_clear()
    first = routes.worker_bundle_bytes()
    routes.worker_bundle_bytes.cache_clear()
    second = routes.worker_bundle_bytes()
    assert first == second
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:gz") as archive:
        names = set(archive.getnames())
        assert "local_shell_mcp/remote_worker.py" in names
        assert archive.extractfile("local_shell_mcp/main.py").read() == (
            routes._LEGACY_WORKER_MAIN  # noqa: SLF001
        )
        expected_python = {
            f"local_shell_mcp/{name}" for name in routes._WORKER_PYTHON_FILES  # noqa: SLF001
        }
        actual_python = {name for name in names if name.endswith(".py")}
        assert actual_python == expected_python | {"local_shell_mcp/main.py"}
        assert not any("tui" in name or "human_ui" in name for name in names)
        assert not any("agent_bridge" in name or "session_runtime" in name for name in names)
        assert "local_shell_mcp/cli_call.py" not in names
        assert "local_shell_mcp/tools.py" not in names

    response = await routes.worker_manifest(None)  # type: ignore[arg-type]
    data = json.loads(response.body)
    assert data["sha256"] == hashlib.sha256(first).hexdigest()
    assert data["url"] == (
        "https://example.test/remote/worker-bundle.tgz?sha256=" + data["sha256"]
    )
    assert response.headers["cache-control"] == "no-store"

    public_manifest = await routes.worker_bundle(SimpleNamespace(query_params={"manifest": "1"}))
    assert json.loads(public_manifest.body) == data
    assert public_manifest.headers["cache-control"] == "no-store"
    bundle = await routes.worker_bundle(None)  # type: ignore[arg-type]
    assert bundle.body == first
    assert bundle.headers["cache-control"] == "no-store"


def test_worker_bundle_entrypoint_isolated_from_controller_cli(tmp_path):
    payload = routes.worker_bundle_bytes()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        archive.extractall(tmp_path, filter="data")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)
    isolation = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util, local_shell_mcp; "
            "print(local_shell_mcp.__file__); "
            "assert all(importlib.util.find_spec('local_shell_mcp.' + name) is None "
            "for name in ('human_ui', 'tui_runtime', 'cli_call', 'tools', "
            "'session_runtime', 'remote_transfer', 'skill_ops', 'oauth'))",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert isolation.returncode == 0, isolation.stderr
    assert isolation.stdout.strip() == str(tmp_path / "local_shell_mcp" / "__init__.py")
    denied = subprocess.run(
        [sys.executable, "-m", "local_shell_mcp.remote_worker", "worker", "call", "run_shell"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert denied.returncode == 2
    assert "invalid choice: 'call'" in denied.stderr
    controller_cli = subprocess.run(
        [sys.executable, "-m", "local_shell_mcp.main", "call", "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert controller_cli.returncode == 2
    assert "invalid choice: 'call'" in controller_cli.stderr
    legacy = subprocess.run(
        [sys.executable, "-m", "local_shell_mcp.main", "worker", "call", "run_shell"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert legacy.returncode == 2
    assert "invalid choice: 'call'" in legacy.stderr
    for command in ("tui", "call"):
        denied = subprocess.run(
            [sys.executable, "-m", "local_shell_mcp.remote_worker", command],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
            check=False,
        )
        assert denied.returncode == 2
        assert f"invalid choice: '{command}'" in denied.stderr


@pytest.mark.asyncio
async def test_join_script_caches_bundle_and_removes_invite_from_worker_process(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    response = await routes.join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")
    assert "/remote/worker-bundle.tgz?manifest=1" in script
    assert "bundle.sha256" in script
    assert "checksum mismatch" in script
    assert "install-service" in script
    assert "install-launcher" in script
    assert 'export PATH="$HOME/.local/bin:$PATH"' in script
    assert "--invite-stdin" in script
    assert "exec python3 -m local_shell_mcp.remote_worker run" in script
    assert "remote_worker run --invite" not in script


@pytest.mark.asyncio
async def test_powershell_join_script_supports_persistent_windows_workers(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    response = await routes.powershell_join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")
    assert "/remote/worker-bundle.tgz?manifest=1" in script
    assert "Get-FileHash -Algorithm SHA256" in script
    assert "tarfile.open" in script
    assert '"--invite-stdin"' in script
    assert '"install-service"' in script
    assert "[switch]$Persist" in script
    assert "$Invite | & $PythonExe @EnrollArgs" in script
    assert "-Invite $Invite" not in script
    assert "sys.version_info >= (3, 11)" in script
    assert script.index("sys.version_info >= (3, 11)") < script.index("Downloading worker bundle")


@pytest.mark.asyncio
async def test_powershell_join_script_escapes_server_url(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://example.test/worker's")
    get_settings.cache_clear()
    response = await routes.powershell_join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")
    assert "$Server = 'https://example.test/worker''s'" in script


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell")
@pytest.mark.asyncio
async def test_powershell_join_script_parses_on_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    response = await routes.powershell_join_script(None)  # type: ignore[arg-type]
    script_path = tmp_path / "join.ps1"
    script_path.write_bytes(response.body)
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell
    script_literal = "'" + str(script_path).replace("'", "''") + "'"
    parser = """
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(__SCRIPT_PATH__, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -gt 0) {
  $errors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }
  exit 1
}
""".replace("__SCRIPT_PATH__", script_literal)
    result = subprocess.run(  # noqa: S603
        [shell, "-NoProfile", "-NonInteractive", "-Command", parser],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_remote_routes_replace_worker_bootstrap_endpoints():
    paths = [route.path for route in routes.remote_routes()]
    assert paths[:4] == [
        "/join",
        "/join.ps1",
        "/remote/worker-manifest.json",
        "/remote/worker-bundle.tgz",
    ]
    assert "/remote/register" in paths
    assert "/remote/resume" in paths
