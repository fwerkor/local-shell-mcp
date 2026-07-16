from __future__ import annotations

import json
import os

import pytest

from local_shell_mcp import remote_worker_cli as cli
from local_shell_mcp import remote_worker_state as state


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
async def test_run_enrolled_worker_rejects_missing_identity(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    state.write_worker_config(server="https://example.test", name="worker", workdir=str(tmp_path))
    monkeypatch.setattr(cli.remote, "_read_worker_identity", lambda server, name=None: None)
    with pytest.raises(RuntimeError, match="join command again"):
        await cli.run_enrolled_worker()


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
    monkeypatch.setattr(cli, "install_launcher", lambda: tmp_path / "bin" / "local-shell-mcp")
    monkeypatch.setattr(cli, "ensure_user_bin_on_path", lambda: [tmp_path / ".profile"])
    monkeypatch.setattr(cli, "start_service", lambda: calls.append("start") or {"running": True})
    monkeypatch.setattr(cli, "stop_service", lambda: calls.append("stop") or {"running": False})
    cli.run_worker_cli(["start"])
    cli.run_worker_cli(["restart"])
    assert calls == ["start", "stop", "start"]


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
    monkeypatch.setattr(cli, "stop_service", lambda: calls.append("stop"))
    monkeypatch.setattr(cli, "start_service", lambda: calls.append("start"))
    cli.run_worker_cli(["update", "--force"])
    assert calls == ["stop", "start"]
    assert '"force": true' in capsys.readouterr().out


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
async def test_connect_enrolls_then_runs(monkeypatch):
    calls = []
    async def fake_enroll(**kwargs):
        calls.append(("enroll", kwargs))
    async def fake_run():
        calls.append(("run", None))
    monkeypatch.setattr(cli, "enroll_worker", fake_enroll)
    monkeypatch.setattr(cli, "run_enrolled_worker", fake_run)
    args = cli.argparse.Namespace(
        server="https://s", invite="i", invite_stdin=False, name="n", workdir="/w",
        runtime_digest="d", runtime_version="v",
    )
    await cli._connect(args)  # noqa: SLF001
    assert [item[0] for item in calls] == ["enroll", "run"]


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
    monkeypatch.setattr(cli, "install_or_update_runtime", lambda server, force=False: {"updated": False})
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
    assert str(tmp_path / ".profile") in output


def test_cli_keyboard_interrupt_is_clean(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run_command", lambda args: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(SystemExit) as exc:
        cli.run_worker_cli(["status"])
    assert exc.value.code == 130
    assert "disconnected by user" in capsys.readouterr().err
