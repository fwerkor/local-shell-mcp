from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from contextlib import nullcontext

import pytest

from local_shell_mcp import audit as audit_module
from local_shell_mcp import remote_worker
from local_shell_mcp import remote_worker_cli as cli
from local_shell_mcp import remote_worker_service as service
from local_shell_mcp import remote_worker_state as state


def test_worker_cli_import_does_not_require_zstandard():
    script = r'''
import builtins
import sys

real_import = builtins.__import__


def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "zstandard":
        raise ModuleNotFoundError("zstandard must not be imported by the worker startup path")
    return real_import(name, globals, locals, fromlist, level)


builtins.__import__ = guarded_import
import local_shell_mcp.remote_worker_cli  # noqa: F401
assert "local_shell_mcp.audit_archive_codec" not in sys.modules
'''
    subprocess.run([sys.executable, "-c", script], check=True, env=os.environ.copy())


def test_worker_entrypoint_only_dispatches_worker_management(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(remote_worker, "run_worker_cli", lambda args: calls.append(args))

    remote_worker.main(["worker", "status"])
    remote_worker.main(["status"])
    assert calls == [["status"], ["status"]]

    monkeypatch.setattr(remote_worker, "run_worker_cli", cli.run_worker_cli)
    with pytest.raises(SystemExit) as exc:
        remote_worker.main(["worker", "call", "run_shell", "--direct"])
    assert exc.value.code == 2
    assert "invalid choice: 'call'" in capsys.readouterr().err


def test_worker_entrypoint_preserves_required_subprocess_helpers(monkeypatch, tmp_path):
    from local_shell_mcp import jobs
    from local_shell_mcp.gui import windows

    calls = []
    monkeypatch.setattr(jobs, "run_job_runner_cli", lambda args: calls.append(("job", args)))
    monkeypatch.setattr(
        windows,
        "_capture_window_image_native",
        lambda hwnd, path: calls.append(("capture", hwnd, path)),
    )
    destination = tmp_path / "window.png"
    remote_worker.main(["job-runner", "--help"])
    remote_worker.main(["_gui-capture-window", "123", str(destination)])
    assert calls == [("job", ["--help"]), ("capture", 123, destination)]
    with pytest.raises(SystemExit, match="requires HWND and destination"):
        remote_worker.main(["_gui-capture-window", "123"])


def _configure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))


def test_enrollment_payload_restores_temporary_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", raising=False)

    def capabilities():
        assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == str(tmp_path)
        assert os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER"] == "true"
        return ["shell"]

    monkeypatch.setattr(cli.remote, "worker_capabilities", capabilities)
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {"workdir": workdir})
    payload = cli._enrollment_payload("worker", str(tmp_path), "invite")  # noqa: SLF001
    assert payload["capabilities"] == ["shell"]
    assert "LOCAL_SHELL_MCP_WORKSPACE_ROOT" not in os.environ
    assert "LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER" not in os.environ


def test_enrollment_payload_overrides_and_restores_existing_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", "/stale/workspace")
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")

    def capabilities():
        assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == str(tmp_path)
        assert os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER"] == "true"
        return ["shell"]

    monkeypatch.setattr(cli.remote, "worker_capabilities", capabilities)
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {"workdir": workdir})
    cli._enrollment_payload("worker", str(tmp_path), "invite")  # noqa: SLF001
    assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == "/stale/workspace"
    assert os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER"] == "false"


@pytest.mark.asyncio
async def test_run_worker_overrides_stale_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", "/stale/workspace")
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    monkeypatch.setattr(cli.remote, "worker_capabilities", lambda: [])
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {})
    monkeypatch.setattr(cli.remote, "_read_worker_identity", lambda server, name=None: None)
    monkeypatch.setattr(cli.remote, "_write_worker_identity", lambda data: None)
    calls = 0
    poll_payloads = []

    async def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == str(tmp_path)
        assert os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER"] == "true"
        if calls == 1:
            return {"ok": True, "data": {"token": "access", "name": "worker"}}
        poll_payloads.append(args[1])
        raise RuntimeError("stop polling")

    monkeypatch.setattr(cli.remote, "_worker_post_json_forever", fake_post)
    with pytest.raises(RuntimeError, match="stop polling"):
        await cli.remote.run_worker(
            "https://example.test", "invite", workdir=str(tmp_path)
        )

    assert len(poll_payloads) == 1
    assert "lane" not in poll_payloads[0]


@pytest.mark.asyncio
async def test_run_worker_resume_omits_stale_name_and_persists_canonical_name(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    monkeypatch.setattr(cli.remote, "worker_capabilities", lambda: [])
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {})
    monkeypatch.setattr(
        cli.remote,
        "_read_worker_identity",
        lambda server, name=None: {"access": "stored", "name": "old-name"},
    )
    persisted = []
    monkeypatch.setattr(cli.remote, "_write_worker_identity", lambda data: persisted.append(data))

    async def fake_resume(url, payload, headers, timeout=None):
        assert payload["name"] is None
        assert headers["Authorization"] == "Bearer stored"
        return {"ok": True, "data": {"name": "renamed"}}

    async def stop_poll(*args, **kwargs):
        raise RuntimeError("stop polling")

    monkeypatch.setattr(cli.remote, "_worker_resume_or_none", fake_resume)
    monkeypatch.setattr(cli.remote, "_worker_post_json_forever", stop_poll)
    with pytest.raises(RuntimeError, match="stop polling"):
        await cli.remote.run_worker(
            "https://example.test",
            "",
            name="old-name",
            workdir=str(tmp_path),
        )
    assert persisted[-1]["name"] == "renamed"


@pytest.mark.asyncio
async def test_run_worker_reports_version_and_applies_poll_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    monkeypatch.setattr(cli.remote, "worker_capabilities", lambda: [])
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {})
    monkeypatch.setattr(cli.remote, "_read_worker_identity", lambda server, name=None: None)
    monkeypatch.setattr(cli.remote, "_write_worker_identity", lambda data: None)
    calls = []
    upgrade_called = False

    async def fake_post(url, payload, headers=None, timeout=None, operation="request"):
        calls.append((url, payload, headers, timeout, operation))
        if url.endswith("/remote/register"):
            return {
                "ok": True,
                "data": {
                    "token": "access",
                    "name": "worker",
                    "poll_timeout_s": 17,
                    "poll_protocol_version": cli.remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
                },
            }
        if upgrade_called:
            raise RuntimeError("stop polling")
        return {
            "ok": True,
            "data": {
                "job": None,
                "upgrade": {"required": True, "version": "9.9.9"},
            },
        }

    async def fake_upgrade(server, target_version):
        nonlocal upgrade_called
        assert server == "https://example.test"
        assert target_version == "9.9.9"
        upgrade_called = True
        raise RuntimeError("upgrade failed")

    monkeypatch.setattr(cli.remote, "_worker_post_json_forever", fake_post)
    monkeypatch.setattr(cli.remote, "_upgrade_worker_runtime", fake_upgrade)
    monkeypatch.setattr(cli.remote, "_worker_retry_delay", lambda attempt: 0)
    monkeypatch.setattr(
        cli.remote,
        "_worker_resource_snapshot",
        lambda: {"cpu_percent": 12.5, "memory_percent": 34.5},
    )

    with pytest.raises(RuntimeError, match="stop polling"):
        await cli.remote.run_worker(
            "https://example.test", "invite", workdir=str(tmp_path)
        )

    assert upgrade_called is True
    assert calls[1][3] == 27
    poll_payload = calls[1][1]
    assert poll_payload == {
        "protocol_version": cli.remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
        "worker_version": cli.remote.__version__,
        "poll_timeout_s": 17,
        "lane": "interactive",
        "resources": {"cpu_percent": 12.5, "memory_percent": 34.5},
    }


@pytest.mark.asyncio
async def test_run_worker_transfer_does_not_block_interactive_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    monkeypatch.setattr(cli.remote, "worker_capabilities", lambda: [])
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {})
    monkeypatch.setattr(cli.remote, "_read_worker_identity", lambda server, name=None: None)
    monkeypatch.setattr(cli.remote, "_write_worker_identity", lambda data: None)

    transfer_started = asyncio.Event()
    interactive_result_submitted = asyncio.Event()
    served_lanes = set()
    submitted_results = []

    async def fake_execute(tool, args):
        if tool == "transfer_upload_url":
            transfer_started.set()
            await asyncio.Event().wait()
        assert tool == "run_shell"
        assert transfer_started.is_set()
        return {"exit_code": 0, "stdout": "ok\n"}

    async def fake_post(url, payload, headers=None, timeout=None, operation="request"):
        if url.endswith("/remote/register"):
            return {
                "ok": True,
                "data": {
                    "token": "access",
                    "name": "worker",
                    "poll_protocol_version": cli.remote.REMOTE_WORKER_POLL_PROTOCOL_VERSION,
                },
            }
        if url.endswith("/remote/poll"):
            lane = payload["lane"]
            if lane not in served_lanes:
                served_lanes.add(lane)
                if lane == "transfer":
                    return {
                        "ok": True,
                        "data": {
                            "job": {
                                "id": "transfer",
                                "tool": "transfer_upload_url",
                                "args": {},
                            },
                        },
                    }
                return {
                    "ok": True,
                    "data": {"job": {"id": "interactive", "tool": "run_shell", "args": {}}},
                }
            await asyncio.wait_for(interactive_result_submitted.wait(), timeout=1)
            raise RuntimeError("stop polling")
        if url.endswith("/remote/heartbeat"):
            assert payload.get("starting") is True
            assert payload.get("job_id") in {"transfer", "interactive"}
            return {"ok": True, "data": {"accepted": True}}
        if url.endswith("/remote/result"):
            submitted_results.append(payload)
            if payload.get("job_id") == "interactive":
                interactive_result_submitted.set()
            return {"ok": True, "data": {"accepted": True}}
        raise AssertionError(url)

    monkeypatch.setattr(cli.remote, "execute_worker_tool", fake_execute)
    monkeypatch.setattr(cli.remote, "_worker_post_json_forever", fake_post)

    with pytest.raises(RuntimeError, match="stop polling"):
        await cli.remote.run_worker("https://example.test", "invite", workdir=str(tmp_path))

    assert interactive_result_submitted.is_set()
    assert [result["job_id"] for result in submitted_results] == ["interactive"]


@pytest.mark.asyncio
async def test_enroll_worker_registers_and_persists(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.remote, "worker_capabilities", lambda: ["shell"])
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {"workdir": workdir})
    monkeypatch.setattr(cli.remote, "_read_worker_identity", lambda server, name=None: None)
    captured = {}
    monkeypatch.setattr(
        cli.remote,
        "_write_worker_identity",
        lambda data: captured.update(identity=data),
    )

    async def fake_post(url, payload, headers=None, timeout=None, operation="request"):
        assert url.endswith("/remote/register")
        assert payload["invite"] == "invite"
        return {"ok": True, "data": {"token": "access", "name": "worker-a"}}

    monkeypatch.setattr(cli.remote, "_worker_post_json_forever", fake_post)
    result = await cli.enroll_worker(
        server="https://example.test/",
        invite="invite",
        name="worker-a",
        workdir=str(tmp_path),
        runtime_digest="abc",
        runtime_version="3.0.0",
    )
    assert result["server"] == "https://example.test"
    assert result["runtime_digest"] == "abc"
    assert captured["identity"]["access"] == "access"
    assert state.read_worker_config()["name"] == "worker-a"


@pytest.mark.asyncio
async def test_enroll_worker_reuses_stored_identity(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.remote, "worker_capabilities", lambda: [])
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {})
    monkeypatch.setattr(
        cli.remote,
        "_read_worker_identity",
        lambda server, name=None: {"access": "stored", "name": "worker-a"},
    )
    monkeypatch.setattr(cli.remote, "_write_worker_identity", lambda data: None)

    async def fake_resume(url, payload, headers, timeout=None):
        assert headers["Authorization"] == "Bearer stored"
        assert payload["name"] is None
        return {"ok": True, "data": {"name": "worker-a"}}

    monkeypatch.setattr(cli.remote, "_worker_resume_or_none", fake_resume)
    monkeypatch.setattr(
        cli.remote,
        "_worker_post_json_forever",
        lambda *args, **kwargs: pytest.fail("registered again"),
    )
    result = await cli.enroll_worker(
        server="https://example.test", invite="unused", workdir=str(tmp_path)
    )
    assert result["name"] == "worker-a"


@pytest.mark.asyncio
async def test_run_enrolled_worker_and_migrate_legacy_identity(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "server": "https://example.test",
                "name": "worker-a",
                "access": "stored",
                "workdir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.remote, "_worker_identity_path", lambda: identity_path)
    monkeypatch.setattr(
        cli.remote, "_read_worker_identity", lambda server, name=None: {"access": "stored"}
    )
    calls = []

    async def fake_run(server, invite, name=None, workdir=None, persist=False):
        calls.append((server, invite, name, workdir, persist))

    monkeypatch.setattr(cli.remote, "run_worker", fake_run)
    await cli.run_enrolled_worker()
    assert calls == [("https://example.test", "", "worker-a", str(tmp_path), False)]
    assert state.worker_config_path().exists()


@pytest.mark.asyncio
async def test_run_enrolled_worker_prefers_persisted_identity_name(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    state.write_worker_config(
        server="https://example.test",
        name="old-name",
        workdir=str(tmp_path),
    )
    monkeypatch.setattr(
        cli.remote,
        "_read_worker_identity",
        lambda server, name=None: {
            "server": server,
            "name": "renamed",
            "access": "stored",
            "workdir": str(tmp_path),
        },
    )
    calls = []

    async def fake_run(server, invite, name=None, workdir=None, persist=False):
        calls.append((server, invite, name, workdir, persist))

    monkeypatch.setattr(cli.remote, "run_worker", fake_run)
    await cli.run_enrolled_worker()
    assert calls == [("https://example.test", "", "renamed", str(tmp_path), False)]


@pytest.mark.asyncio
async def test_run_enrolled_worker_rejects_missing_identity(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    state.write_worker_config(server="https://example.test", name="worker", workdir=str(tmp_path))
    monkeypatch.setattr(cli.remote, "_read_worker_identity", lambda server, name=None: None)
    with pytest.raises(RuntimeError, match="join command again"):
        await cli.run_enrolled_worker()


def test_legacy_worker_cli_suppresses_audit_archives(monkeypatch):
    monkeypatch.setattr(service, "worker_run_lock", nullcontext)
    observed = []

    async def fake_locked(server, invite, name=None, workdir=None, persist=False):
        observed.append(audit_module._AUDIT_ARCHIVE_ENABLED.get())  # noqa: SLF001

    monkeypatch.setattr(cli.remote, "_run_worker_locked", fake_locked)
    cli.remote.run_worker_cli(["--server", "https://example.test", "--invite", "x"])

    assert observed == [False]
    assert audit_module._AUDIT_ARCHIVE_ENABLED.get() is True  # noqa: SLF001


def test_cli_legacy_and_lifecycle_dispatch(tmp_path, monkeypatch, capsys):
    _configure(tmp_path, monkeypatch)
    legacy = []
    monkeypatch.setattr(cli.remote, "run_worker_cli", lambda argv: legacy.append(argv))
    cli.run_worker_cli(["--server", "https://example.test", "--invite", "x"])
    assert legacy

    monkeypatch.setattr(cli, "service_status", lambda: {"running": True})
    cli.run_worker_cli(["status"])
    assert '"running": true' in capsys.readouterr().out

    calls = []
    monkeypatch.setattr(cli, "_prepare_worker_start", lambda: calls.append("prepare"))
    monkeypatch.setattr(cli, "start_service", lambda: calls.append("start") or {"running": True})
    monkeypatch.setattr(cli, "stop_service", lambda: calls.append("stop") or {"running": False})
    cli.run_worker_cli(["start"])
    cli.run_worker_cli(["restart"])
    assert calls == ["prepare", "start", "stop", "prepare", "start"]


def test_cli_run_prepares_managed_service_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli, "prepare_worker_service_environment", lambda: calls.append("prepare")
    )

    async def fake_run():
        calls.append("run")

    monkeypatch.setattr(cli, "run_enrolled_worker", fake_run)
    cli.run_worker_cli(["run"])
    assert calls == ["prepare", "run"]


def test_cli_update_restarts_running_service(tmp_path, monkeypatch, capsys):
    _configure(tmp_path, monkeypatch)
    state.write_worker_config(server="https://example.test", name="worker", workdir=str(tmp_path))
    calls = []
    monkeypatch.setattr(cli, "service_status", lambda: {"running": True})
    monkeypatch.setattr(
        cli,
        "install_or_update_runtime",
        lambda server, force=False: {"updated": True, "server": server, "force": force},
    )
    monkeypatch.setattr(
        cli,
        "refresh_installed_service_definition",
        lambda: calls.append("refresh"),
    )
    monkeypatch.setattr(cli, "stop_service", lambda: calls.append("stop"))
    monkeypatch.setattr(cli, "start_service", lambda: calls.append("start"))
    cli.run_worker_cli(["update", "--force"])
    assert calls == ["refresh", "stop", "start"]
    assert '"force": true' in capsys.readouterr().out


def test_cli_update_refreshes_stopped_service_definition(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    state.write_worker_config(server="https://example.test", name="worker", workdir=str(tmp_path))
    calls = []
    monkeypatch.setattr(cli, "service_status", lambda: {"running": False})
    monkeypatch.setattr(
        cli,
        "install_or_update_runtime",
        lambda server, force=False: {"updated": True, "server": server, "force": force},
    )
    monkeypatch.setattr(
        cli,
        "refresh_installed_service_definition",
        lambda: calls.append("refresh"),
    )
    monkeypatch.setattr(cli, "stop_service", lambda: pytest.fail("stopped inactive service"))
    monkeypatch.setattr(cli, "start_service", lambda: pytest.fail("started inactive service"))

    cli.run_worker_cli(["update"])
    assert calls == ["refresh"]


def test_cli_errors_are_clean(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run_command", lambda args: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(SystemExit) as exc:
        cli.run_worker_cli(["status"])
    assert exc.value.code == 1
    assert "Status: worker command failed: bad" in capsys.readouterr().err


def test_read_invite_sources_and_validation(monkeypatch):
    direct = cli.argparse.Namespace(invite="direct", invite_stdin=False)
    assert cli._read_invite(direct) == "direct"  # noqa: SLF001
    monkeypatch.setattr(cli.sys, "stdin", __import__("io").StringIO("from-stdin\n"))
    stdin = cli.argparse.Namespace(invite=None, invite_stdin=True)
    assert cli._read_invite(stdin) == "from-stdin"  # noqa: SLF001
    with pytest.raises(ValueError, match="invite is required"):
        cli._read_invite(cli.argparse.Namespace(invite="", invite_stdin=False))  # noqa: SLF001


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_enroll_worker_rejects_unsuccessful_server_response(tmp_path, monkeypatch, resume):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.remote, "worker_capabilities", lambda: [])
    monkeypatch.setattr(cli.remote, "worker_info", lambda workdir: {})
    identity = {"access": "stored", "name": "worker-a"} if resume else None
    monkeypatch.setattr(cli.remote, "_read_worker_identity", lambda server, name=None: identity)
    if resume:
        async def failed_resume(*args, **kwargs):
            return {"ok": False, "message": "resume denied"}
        monkeypatch.setattr(cli.remote, "_worker_resume_or_none", failed_resume)
    else:
        async def failed_register(*args, **kwargs):
            return {"ok": False, "message": "register denied"}
        monkeypatch.setattr(cli.remote, "_worker_post_json_forever", failed_register)
    with pytest.raises(RuntimeError, match="denied"):
        await cli.enroll_worker(server="https://example.test", invite="invite", workdir=str(tmp_path))


def test_load_config_rejects_non_mapping_legacy_identity(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    identity_path = tmp_path / "legacy.json"
    identity_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cli.remote, "_worker_identity_path", lambda: identity_path)
    with pytest.raises(ValueError, match="stored worker identity is invalid"):
        cli._load_config_or_migrate()  # noqa: SLF001


@pytest.mark.asyncio
async def test_connect_enrolls_then_reexecs_without_invite(monkeypatch):
    calls = []

    async def fake_enroll(**kwargs):
        calls.append(("enroll", kwargs))

    monkeypatch.setattr(cli, "enroll_worker", fake_enroll)
    monkeypatch.setattr(cli, "_reexec_worker_run", lambda: calls.append(("reexec", None)))
    args = cli.argparse.Namespace(
        server="https://s", invite="i", invite_stdin=False, name="n", workdir="/w",
        runtime_digest="d", runtime_version="v",
    )
    await cli._connect(args)  # noqa: SLF001
    assert [item[0] for item in calls] == ["enroll", "reexec"]
    assert calls[0][1]["invite"] == "i"


def test_worker_run_reexec_uses_token_free_argv(monkeypatch):
    monkeypatch.setattr(cli, "is_frozen_app", lambda: False)
    assert cli._worker_run_exec_argv() == [  # noqa: SLF001
        cli.sys.executable,
        "-m",
        "local_shell_mcp.remote_worker",
        "run",
    ]
    monkeypatch.setattr(cli, "is_frozen_app", lambda: True)
    assert cli._worker_run_exec_argv() == [cli.sys.executable, "worker", "run"]  # noqa: SLF001

    calls = []
    monkeypatch.setattr(cli.os, "execv", lambda executable, argv: calls.append((executable, argv)))
    cli._reexec_worker_run()  # noqa: SLF001
    assert calls == [(cli.sys.executable, [cli.sys.executable, "worker", "run"])]


def test_prepare_worker_start_installs_runtime_before_launcher(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    state.write_worker_config(server="https://example.test", name="worker", workdir=str(tmp_path))
    calls = []
    monkeypatch.setattr(
        cli,
        "install_or_update_runtime",
        lambda server: calls.append(("runtime", server)),
    )
    monkeypatch.setattr(cli, "install_launcher", lambda: calls.append(("launcher", None)))
    monkeypatch.setattr(cli, "ensure_user_bin_on_path", lambda: calls.append(("path", None)))
    cli._prepare_worker_start()  # noqa: SLF001
    assert calls == [
        ("runtime", "https://example.test"),
        ("launcher", None),
        ("path", None),
    ]


@pytest.mark.asyncio
async def test_connect_rejects_duplicate_before_enrollment(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    args = cli._parser().parse_args(  # noqa: SLF001
        ["connect", "--server", "https://example.test", "--invite", "invite"]
    )
    monkeypatch.setattr(
        cli,
        "enroll_worker",
        lambda **kwargs: pytest.fail("consumed invitation before acquiring worker lock"),
    )

    with cli.worker_run_lock(), pytest.raises(service.WorkerAlreadyRunningError):
        await cli._connect(args)  # noqa: SLF001


def test_all_remaining_lifecycle_command_branches(tmp_path, monkeypatch, capsys):
    _configure(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(cli.asyncio, "run", lambda value: calls.append(("async", value)) or {"ok": True})
    monkeypatch.setattr(cli, "enroll_worker", lambda **kwargs: ("enroll", kwargs))
    monkeypatch.setattr(cli, "_connect", lambda args: ("connect", args.server))
    monkeypatch.setattr(cli, "run_enrolled_worker", lambda: "run")
    monkeypatch.setattr(cli, "stop_service", lambda: calls.append(("stop", None)) or {"running": False})
    monkeypatch.setattr(cli, "service_status", lambda: {"running": False})
    monkeypatch.setattr(cli, "_load_config_or_migrate", lambda: {"server": "https://s"})
    runtime_installs = []
    monkeypatch.setattr(
        cli,
        "install_or_update_runtime",
        lambda server, force=False: runtime_installs.append((server, force))
        or {"updated": False},
    )
    monkeypatch.setattr(cli, "install_service", lambda start=True: {"service": start})
    monkeypatch.setattr(cli, "uninstall_service", lambda: {"uninstalled": True})
    monkeypatch.setattr(cli, "install_launcher", lambda: tmp_path / "local-shell-mcp")
    monkeypatch.setattr(cli, "ensure_user_bin_on_path", lambda: [tmp_path / ".profile"])

    cli._run_command(cli._parser().parse_args(["enroll", "--server", "https://s", "--invite", "i"]))  # noqa: SLF001
    cli._run_command(cli._parser().parse_args(["connect", "--server", "https://s", "--invite", "i"]))  # noqa: SLF001
    cli._run_command(cli._parser().parse_args(["run"]))  # noqa: SLF001
    cli._run_command(cli._parser().parse_args(["stop"]))  # noqa: SLF001
    cli._run_command(cli._parser().parse_args(["update"]))  # noqa: SLF001
    cli._run_command(cli._parser().parse_args(["install-service", "--no-start"]))  # noqa: SLF001
    cli._run_command(cli._parser().parse_args(["uninstall-service"]))  # noqa: SLF001
    cli._run_command(cli._parser().parse_args(["install-launcher"]))  # noqa: SLF001
    output = capsys.readouterr().out
    assert '"service": false' in output
    assert '"uninstalled": true' in output
    assert json.dumps(str(tmp_path / ".profile")) in output
    assert runtime_installs == [("https://s", False), ("https://s", False)]


def test_cli_keyboard_interrupt_is_clean(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run_command", lambda args: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(SystemExit) as exc:
        cli.run_worker_cli(["status"])
    assert exc.value.code == 130
    assert "disconnected by user" in capsys.readouterr().err
