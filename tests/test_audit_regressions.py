from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request

import local_shell_mcp.http_app as http_app_module
import local_shell_mcp.human_ui as human_ui
import local_shell_mcp.jobs as jobs_module
import local_shell_mcp.playwright_ops as playwright_module
import local_shell_mcp.remote as remote_module
import local_shell_mcp.tools as tools_module
from local_shell_mcp.auth import required_scopes_for_http_tool
from local_shell_mcp.fs_ops import edit_text, resolve_path
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.models import CommandResult
from local_shell_mcp.remote import RemoteManager, RemoteWorker
from local_shell_mcp.remote_transfer import create_download_ticket, remote_transfer_routes
from local_shell_mcp.settings import Settings, get_settings
from local_shell_mcp.shell_ops import _tmux_session_name, check_command_policy
from local_shell_mcp.tools import build_mcp
from local_shell_mcp.transfer_ops import (
    transfer_abort_write,
    transfer_begin_write,
    transfer_finish_write,
    transfer_pack_dir,
    transfer_write_chunk,
)


def _configure_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "updates",
    [
        {"remote_poll_timeout_s": 0},
        {"file_download_max_ttl_s": -1},
        {"port": 70000},
        {"default_timeout_s": 20, "max_timeout_s": 10},
        {"file_download_default_ttl_s": 20, "file_download_max_ttl_s": 10},
    ],
)
def test_settings_reject_invalid_numeric_ranges(updates):
    with pytest.raises(ValueError):
        Settings(**updates)


def test_path_policy_uses_components_and_edit_rejects_empty_search(tmp_path, monkeypatch):
    workspace = tmp_path / "secrets-project"
    workspace.mkdir()
    _configure_workspace(workspace, monkeypatch)
    (workspace / "README.md").write_text("abc", encoding="utf-8")
    (workspace / ".environment").write_text("safe", encoding="utf-8")

    assert resolve_path("README.md").name == "README.md"
    assert resolve_path(".environment").name == ".environment"

    (workspace / "secrets").mkdir()
    (workspace / "secrets" / "value.txt").write_text("hidden", encoding="utf-8")
    with pytest.raises(PermissionError):
        resolve_path("secrets/value.txt")

    with pytest.raises(ValueError, match="must not be empty"):
        edit_text("README.md", [{"old": "", "new": "Z", "replace_all": True}])
    with pytest.raises(ValueError, match="must not be empty"):
        edit_text("README.md", [{"old": "", "new": "Z"}])
    assert (workspace / "README.md").read_text(encoding="utf-8") == "abc"


def test_command_policy_is_case_insensitive_and_session_names_never_empty(
    tmp_path, monkeypatch
):
    _configure_workspace(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match="shutdown"):
        check_command_policy("SHUTDOWN /s /t 0")
    assert _tmux_session_name("   ").startswith("mcp-")
    assert _tmux_session_name("💥").startswith("mcp-")


def test_job_runner_filters_service_environment(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_PRIVATE_VALUE", "blocked")
    monkeypatch.setenv("DOCKER_HOST", "blocked")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", "blocked")
    monkeypatch.setenv("SAFE_JOB_VALUE", "visible")
    command_path = tmp_path / "command.txt"
    log_path = tmp_path / "job.log"
    status_path = tmp_path / "status.json"
    command_path.write_text("true", encoding="utf-8")
    captured = {}

    class FakeProcess:
        stdout = io.BytesIO(b"")

        def wait(self):
            return 0

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(jobs_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        jobs_module,
        "get_settings",
        lambda: (_ for _ in ()).throw(AssertionError("runner must not reload settings")),
    )
    with pytest.raises(SystemExit) as raised:
        jobs_module.run_job_runner_cli(
            [
                "--command-file",
                str(command_path),
                "--log-file",
                str(log_path),
                "--status-file",
                str(status_path),
                "--cwd",
                str(tmp_path),
                "--shell",
                "/bin/sh",
                "--max-log-bytes",
                "1024",
            ]
        )

    assert raised.value.code == 0
    assert captured["env"]["SAFE_JOB_VALUE"] == "visible"
    assert "LOCAL_SHELL_MCP_PRIVATE_VALUE" not in captured["env"]
    assert "DOCKER_HOST" not in captured["env"]
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in captured["env"]


def test_transfer_requires_complete_non_overlapping_ranges(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    begin = transfer_begin_write("sparse.bin", expected_bytes=8)
    transfer_write_chunk("sparse.bin", begin["transfer_id"], 7, "WA==")
    with pytest.raises(ValueError, match="missing or non-contiguous"):
        transfer_finish_write("sparse.bin", begin["transfer_id"], expected_bytes=8)
    transfer_abort_write("sparse.bin", begin["transfer_id"])

    begin = transfer_begin_write("overlap.bin", expected_bytes=4)
    transfer_write_chunk("overlap.bin", begin["transfer_id"], 0, "YWJj")
    with pytest.raises(ValueError, match="overlaps"):
        transfer_write_chunk("overlap.bin", begin["transfer_id"], 2, "eg==")
    transfer_abort_write("overlap.bin", begin["transfer_id"])


def test_directory_pack_rejects_invalid_compression_and_special_files(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "regular.txt").write_text("ok", encoding="utf-8")
    with pytest.raises(ValueError, match="compression"):
        transfer_pack_dir("source", "zip")

    if hasattr(os, "mkfifo"):
        os.mkfifo(source / "pipe")
        with pytest.raises(ValueError, match="special files"):
            transfer_pack_dir("source", "gz")


def test_remote_registry_recovers_backup_and_refuses_total_corruption(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    manager = RemoteManager()
    manager._registry_loaded = True
    worker = RemoteWorker(name="saved-worker", token="saved-token")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    manager._save_registry_unlocked()

    registry = manager._registry_path()
    backup = manager._registry_backup_path()
    registry.write_text("{broken", encoding="utf-8")
    recovered = RemoteManager().list_machines()
    assert [row["name"] for row in recovered["machines"]] == ["saved-worker"]
    assert json.loads(registry.read_text(encoding="utf-8"))["version"] == 1

    registry.write_text("{broken again", encoding="utf-8")
    backup.write_text("{also broken", encoding="utf-8")
    manager_with_corruption = RemoteManager()
    with pytest.raises(RuntimeError, match="refusing to reset"):
        manager_with_corruption.list_machines()
    with pytest.raises(RuntimeError, match="refusing to reset"):
        manager_with_corruption.list_machines()
    assert registry.read_text(encoding="utf-8") == "{broken again"
    assert backup.read_text(encoding="utf-8") == "{also broken"


def test_remote_download_ticket_serves_verified_snapshot(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    original = b"abcdefgh"
    source = tmp_path / "source.bin"
    source.write_bytes(original)
    ticket = create_download_ticket(
        "source.bin", len(original), hashlib.sha256(original).hexdigest()
    )
    source.write_bytes(b"12345678")

    client = TestClient(Starlette(routes=remote_transfer_routes()))
    response = client.get(urlsplit(ticket["url"]).path)
    assert response.status_code == 200
    assert response.content == original
    assert response.headers["x-content-sha256"] == hashlib.sha256(original).hexdigest()


@pytest.mark.asyncio
async def test_controller_timeout_is_visible_to_running_worker(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    manager = RemoteManager()
    manager._registry_loaded = True
    worker = RemoteWorker(name="worker-a", token="token-a")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    call = asyncio.create_task(
        manager.call("worker-a", "list_files", {"path": "."}, timeout_s=0.01)
    )
    polled = await manager.poll(worker.token)
    job_id = polled["job"]["id"]
    with pytest.raises(TimeoutError, match="remote job timed out"):
        await call

    heartbeat = await manager.heartbeat(worker.token, {"job_id": job_id})
    assert heartbeat["accepted"] is False
    assert heartbeat["cancelled"] is True


@pytest.mark.asyncio
async def test_claimed_remote_mutation_waits_for_definitive_result(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    manager = RemoteManager()
    manager._registry_loaded = True
    worker = RemoteWorker(name="worker-a", token="token-a")
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    call = asyncio.create_task(
        manager.call(
            "worker-a",
            "write_file",
            {"path": "target.txt", "content": "done"},
            timeout_s=0.01,
        )
    )
    polled = await manager.poll(worker.token)
    await asyncio.sleep(0.03)
    assert call.done() is False

    accepted = await manager.submit_result(
        worker.token,
        {"job_id": polled["job"]["id"], "ok": True, "data": {"path": "target.txt"}},
    )
    assert accepted["accepted"] is True
    result = await call
    assert result["data"]["path"] == "target.txt"


@pytest.mark.asyncio
async def test_worker_cancels_cooperative_task_when_controller_rejects_heartbeat(monkeypatch):
    completed = False

    async def fake_execute(tool, args):
        nonlocal completed
        del tool, args
        await asyncio.sleep(1)
        completed = True
        return {"done": True}

    def cancelled_heartbeat(url, payload, headers=None, timeout=None):
        del url, headers, timeout
        assert payload == {"job_id": "job-cancelled"}
        return {"ok": True, "data": {"accepted": False, "cancelled": True}}

    monkeypatch.setattr(remote_module, "execute_worker_tool", fake_execute)
    monkeypatch.setattr(remote_module, "_worker_post_json", cancelled_heartbeat)

    with pytest.raises(remote_module.RemoteJobCancelled):
        await remote_module._execute_worker_job_with_heartbeat(
            {"id": "job-cancelled", "tool": "slow", "args": {}},
            "https://controller.test",
            {"Authorization": "Bearer token"},
            0.01,
        )
    assert completed is False


@pytest.mark.asyncio
async def test_mcp_mutation_does_not_return_before_thread_finishes(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(tools_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    marker = tmp_path / "completed.txt"

    def delayed_write(path, content, overwrite=True, expected_sha256=None):
        del path, overwrite, expected_sha256
        time.sleep(0.05)
        marker.write_text(content, encoding="utf-8")
        return {"path": "target.txt", "bytes": len(content), "created": True}

    monkeypatch.setattr(tools_module, "write_text", delayed_write)
    response = await build_mcp().call_tool(
        "write_file", {"path": "target.txt", "content": "done"}
    )
    payload = json.loads(response[0][0].text)
    assert payload["data"]["path"] == "target.txt"
    assert marker.read_text(encoding="utf-8") == "done"


def test_rest_mutation_does_not_return_before_thread_finishes(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    marker = tmp_path / "rest-completed.txt"

    def delayed_write(path, content, overwrite=True):
        del path, overwrite
        time.sleep(0.05)
        marker.write_text(content, encoding="utf-8")
        return {"path": "target.txt", "bytes": len(content), "created": True}

    monkeypatch.setattr(http_app_module, "write_text", delayed_write)
    response = TestClient(build_http_app()).post(
        "/tools/write_file", json={"path": "target.txt", "content": "done"}
    )
    assert response.status_code == 200
    assert marker.read_text(encoding="utf-8") == "done"


@pytest.mark.asyncio
async def test_python_and_playwright_tools_honor_configured_interpreter_and_clear_stale_output(
    tmp_path, monkeypatch
):
    _configure_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_PYTHON_BIN", "/opt/custom python")
    get_settings.cache_clear()
    commands = []

    async def fake_run(command, **kwargs):
        del kwargs
        commands.append(command)
        return CommandResult(
            ok=False,
            exit_code=1,
            timed_out=False,
            duration_ms=1,
            cwd=".",
            command=command,
            stdout="",
            stderr="failed",
            truncated=False,
        )

    monkeypatch.setattr(tools_module, "run_shell", fake_run)
    await tools_module._run_python("print('x')")
    assert commands[-1].startswith("'/opt/custom python' ")

    stale = tmp_path / "screenshots" / "page.png"
    stale.parent.mkdir()
    stale.write_bytes(b"old")
    monkeypatch.setattr(playwright_module, "run_shell", fake_run)
    result = await playwright_module.browser_capture(
        "https://invalid.test", "screenshots/page.png", capture_format="png"
    )
    assert commands[-1].startswith("'/opt/custom python' ")
    assert result["capture_path"] is None
    assert not stale.exists()


def test_rest_validation_readiness_and_todo_scope(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    client = TestClient(build_http_app())

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"ok": True}

    invalid_bool = client.post(
        "/tools/list_files", json={"path": ".", "recursive": "false"}
    )
    assert invalid_bool.status_code == 400
    assert invalid_bool.json()["error"] == "validation_error"

    invalid_integer = client.post(
        "/tools/list_files", json={"path": ".", "max_entries": "many"}
    )
    assert invalid_integer.status_code == 400
    assert invalid_integer.json()["error"] == "validation_error"

    assert required_scopes_for_http_tool("/tools/todo", "GET") == ("shell:read",)
    assert required_scopes_for_http_tool("/tools/todo", "POST") == (
        "shell:read",
        "shell:write",
    )


def test_secret_scan_fallback_respects_gitignore(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_RG_BIN", str(tmp_path / "missing-rg"))
    get_settings.cache_clear()
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text(
        'api_key="ignored-secret-value"\n', encoding="utf-8"
    )
    (tmp_path / "visible.txt").write_text(
        'api_key="visible-secret-value"\n', encoding="utf-8"
    )

    findings = tools_module._secret_scan_sync(".", None, 20)["findings"]
    assert {item["path"] for item in findings} == {"visible.txt"}


@pytest.mark.asyncio
async def test_fetch_reports_truncation_and_encoded_actual_file_uri(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "5")
    get_settings.cache_clear()
    path = tmp_path / "a b#c.txt"
    path.write_text("0123456789", encoding="utf-8")

    response = await build_mcp().call_tool("fetch", {"id": "a b#c.txt"})
    payload = json.loads(response[0][0].text)
    assert payload["text"] == "01234"
    assert payload["metadata"]["truncated"] is True
    assert payload["metadata"]["truncated_bytes"] == 5
    assert "%20" in payload["url"]
    assert "%23" in payload["url"]
    assert payload["url"] == path.resolve().as_uri()


@pytest.mark.asyncio
async def test_failed_remote_directory_pull_removes_local_archive(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    archive = tmp_path / "temporary.tar.gz"

    async def fake_remote_data(machine, tool, args, timeout_s=None):
        del machine, args, timeout_s
        if tool == "transfer_pack_dir":
            return {
                "archive_path": "remote.tar.gz",
                "path": "source",
                "bytes": 7,
                "sha256": "digest",
            }
        raise AssertionError(tool)

    async def fake_copy(*args, **kwargs):
        del args, kwargs
        archive.write_bytes(b"archive")
        return {
            "bytes": 7,
            "sha256": "digest",
            "chunks": 1,
            "chunk_size": 7,
            "source": {},
            "destination": {},
        }

    async def fake_cleanup(*args, **kwargs):
        del args, kwargs

    monkeypatch.setattr(tools_module, "_remote_transfer_data", fake_remote_data)
    monkeypatch.setattr(
        tools_module, "transfer_alloc_temp_path", lambda suffix: {"path": archive.name}
    )
    monkeypatch.setattr(tools_module, "_copy_remote_file_to_local", fake_copy)
    monkeypatch.setattr(
        tools_module,
        "transfer_unpack_archive",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("unpack failed")),
    )
    monkeypatch.setattr(tools_module, "_remote_cleanup_file", fake_cleanup)

    with pytest.raises(ValueError, match="unpack failed"):
        await tools_module._copy_remote_dir_to_local("node", "source", "dest")
    assert not archive.exists()


@pytest.mark.asyncio
async def test_wallpaper_retries_after_transient_failure(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_WALLPAPER", "bing")
    get_settings.cache_clear()
    calls = 0

    class FailingClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args
            return False

        async def get(self, *args, **kwargs):
            nonlocal calls
            del args, kwargs
            calls += 1
            raise RuntimeError("network unavailable")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ui/wallpaper",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("localhost", 80),
            "scheme": "http",
        }
    )
    first = await human_ui.ui_wallpaper(request)
    second = await human_ui.ui_wallpaper(request)
    assert first.status_code == 204
    assert second.status_code == 204
    assert calls == 2


def test_vscode_extension_uses_posix_process_group_shutdown():
    source = Path("vscode-extension/src/extension.ts").read_text(encoding="utf-8")
    assert "detached: process.platform !== 'win32'" in source
    assert "killProcess(-proc.pid, signal)" in source
    assert "await wait(proc, 2000)" in source
    assert '"test": "npm run compile && node --test test/*.test.cjs"' in Path(
        "vscode-extension/package.json"
    ).read_text(encoding="utf-8")
