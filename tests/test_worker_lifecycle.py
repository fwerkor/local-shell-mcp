from __future__ import annotations

import json
import os
import signal
from types import SimpleNamespace

import pytest

from local_shell_mcp import worker_lifecycle as lifecycle


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    return tmp_path


def test_worker_state_dir_precedence(tmp_path, monkeypatch):
    configured = tmp_path / "configured"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(configured))
    assert lifecycle.worker_state_dir() == configured

    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR")
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg))
    assert lifecycle.worker_state_dir() == xdg / "local-shell-mcp-worker"

    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setattr(lifecycle.Path, "home", lambda: tmp_path)
    assert lifecycle.worker_state_dir() == tmp_path / ".local/state/local-shell-mcp-worker"


def test_config_round_trip_and_status(state_dir):
    config = {
        "version": 1,
        "server": "https://example.test",
        "name": "node",
        "workdir": str(state_dir),
    }
    lifecycle.write_worker_config(config)
    assert lifecycle.read_worker_config() == config
    status = lifecycle.worker_status()
    assert status["installed"] is True
    assert status["running"] is False
    assert status["server"] == "https://example.test"


def test_config_errors(state_dir, monkeypatch):
    with pytest.raises(RuntimeError, match="not installed"):
        lifecycle.read_worker_config()
    lifecycle.worker_config_path().write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unsupported"):
        lifecycle.read_worker_config()
    lifecycle.worker_config_path().write_text("not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        lifecycle.read_worker_config()
    lifecycle.worker_config_path().write_text(
        json.dumps({"version": 1, "server": "x", "name": "", "workdir": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="missing name"):
        lifecycle.read_worker_config()

    monkeypatch.setattr(lifecycle.Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(RuntimeError, match="unreadable"):
        lifecycle.read_worker_config()


def test_pid_is_running_branches(monkeypatch):
    assert lifecycle._pid_is_running(0) is False

    monkeypatch.setattr(lifecycle.os, "kill", lambda pid, sig: None)
    assert lifecycle._pid_is_running(1) is True

    def missing(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(lifecycle.os, "kill", missing)
    assert lifecycle._pid_is_running(1) is False

    def denied(pid, sig):
        raise PermissionError

    monkeypatch.setattr(lifecycle.os, "kill", denied)
    assert lifecycle._pid_is_running(1) is True


def test_pid_helpers_remove_stale_pid(state_dir, monkeypatch):
    assert lifecycle.read_worker_pid() is None
    lifecycle.worker_pid_path().write_text("bad", encoding="utf-8")
    assert lifecycle.read_worker_pid() is None
    lifecycle.worker_pid_path().write_text("123", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "_pid_is_running", lambda pid: False)
    assert lifecycle.read_worker_pid() is None
    assert not lifecycle.worker_pid_path().exists()

    lifecycle.worker_pid_path().write_text("123", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "_pid_is_running", lambda pid: True)
    assert lifecycle.read_worker_pid() == 123


def test_start_worker_is_idempotent(state_dir, monkeypatch):
    lifecycle.write_worker_config(
        {"version": 1, "server": "https://s", "name": "n", "workdir": str(state_dir)}
    )
    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: None)
    process = SimpleNamespace(pid=321)
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(lifecycle.subprocess, "Popen", fake_popen)
    assert lifecycle.start_worker() == 321
    assert lifecycle.worker_pid_path().read_text(encoding="utf-8") == "321"
    assert calls[0][1]["start_new_session"] is True
    assert "local_shell_mcp.remote_worker" in calls[0][0][0]
    assert str(state_dir / "runtime") in calls[0][1]["env"]["PYTHONPATH"]

    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: 321)
    assert lifecycle.start_worker() == 321
    assert len(calls) == 1


def test_start_worker_requires_install(state_dir, monkeypatch):
    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: None)
    with pytest.raises(RuntimeError, match="not installed"):
        lifecycle.start_worker()


def test_stop_worker(state_dir, monkeypatch):
    lifecycle.worker_pid_path().write_text("44", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: 44)
    states = iter([True, False, False])
    monkeypatch.setattr(lifecycle, "_pid_is_running", lambda pid: next(states, False))
    signals = []
    monkeypatch.setattr(lifecycle.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    assert lifecycle.stop_worker(timeout_s=0.1) is True
    assert signals[0] == (44, signal.SIGTERM)


def test_stop_worker_escalates_and_handles_missing_process(state_dir, monkeypatch):
    lifecycle.worker_pid_path().write_text("44", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: 44)
    monkeypatch.setattr(lifecycle, "_pid_is_running", lambda pid: True)
    times = iter([0.0, 2.0])
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(times, 2.0))
    signals = []
    monkeypatch.setattr(lifecycle.os, "kill", lambda pid, sig: signals.append(sig))
    assert lifecycle.stop_worker(timeout_s=1.0) is True
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals

    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: 44)

    def vanished(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(lifecycle.os, "kill", vanished)
    monkeypatch.setattr(lifecycle, "_pid_is_running", lambda pid: False)
    assert lifecycle.stop_worker() is True


def test_stop_worker_when_not_running(monkeypatch):
    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: None)
    assert lifecycle.stop_worker() is False


def test_status_when_not_installed(state_dir):
    status = lifecycle.worker_status()
    assert status["installed"] is False
    assert status["server"] is None
    assert status["name"] is None


@pytest.mark.asyncio
async def test_enroll_worker_persists_identity_and_config(state_dir, monkeypatch):
    async def fake_post(*args, **kwargs):
        return {"ok": True, "data": {"token": "secret", "name": "node"}}

    identities = []
    monkeypatch.setattr(lifecycle, "_worker_post_json_forever", fake_post)
    monkeypatch.setattr(lifecycle, "worker_capabilities", lambda: ["shell"])
    monkeypatch.setattr(lifecycle, "worker_info", lambda workdir: {"workdir": workdir})
    monkeypatch.setattr(lifecycle, "_write_worker_identity", identities.append)
    config = await lifecycle.enroll_worker("https://server/", "invite", None, str(state_dir))
    assert config["server"] == "https://server"
    assert config["name"] == "node"
    assert identities[0]["access"] == "secret"
    assert lifecycle.read_worker_config() == config


@pytest.mark.asyncio
async def test_enroll_worker_rejects_failed_response(state_dir, monkeypatch):
    async def fake_post(*args, **kwargs):
        return {"ok": False, "message": "denied"}

    monkeypatch.setattr(lifecycle, "_worker_post_json_forever", fake_post)
    monkeypatch.setattr(lifecycle, "worker_capabilities", lambda: [])
    monkeypatch.setattr(lifecycle, "worker_info", lambda workdir: {})
    with pytest.raises(RuntimeError, match="denied"):
        await lifecycle.enroll_worker("https://server", "invite", None, str(state_dir))


@pytest.mark.asyncio
async def test_run_installed_worker(state_dir, monkeypatch):
    lifecycle.write_worker_config(
        {"version": 1, "server": "https://s", "name": "n", "workdir": str(state_dir)}
    )
    calls = []

    async def fake_run_worker(*args):
        calls.append(args)

    monkeypatch.setattr(lifecycle, "run_worker", fake_run_worker)
    await lifecycle.run_installed_worker()
    assert calls == [("https://s", "", "n", str(state_dir), False)]


@pytest.mark.asyncio
async def test_manifest_uses_bundle_digest(monkeypatch):
    class Response:
        body = b"bundle"

    async def fake_bundle(request):
        return Response()

    monkeypatch.setattr(lifecycle, "worker_bundle", fake_bundle)
    response = await lifecycle.worker_manifest(object())
    payload = json.loads(response.body)
    assert payload["schema_version"] == 1
    assert payload["size"] == 6
    assert payload["url"].endswith("worker-bundle.tgz")
    assert len(payload["sha256"]) == 64


def test_join_script_contains_cache_path_and_path_setup():
    script = lifecycle._join_script("https://server/path with space")
    assert "worker-manifest.json" in script
    assert "runtime.sha256" in script
    assert 'export PATH="$HOME/.local/bin:$PATH"' in script
    assert lifecycle.PATH_MARKER in script
    assert "worker enroll" in script
    assert "worker start" in script
    assert "--invite \"$INVITE\"" in script
    assert "python3 -m local_shell_mcp.main" in script
    run_section = script.split("Persistent worker installed and started.", 1)[1]
    assert "remote_worker" in run_section


@pytest.mark.asyncio
async def test_join_script_response(monkeypatch):
    settings = SimpleNamespace(public_base_url="https://public/", host="127.0.0.1", port=8000)
    monkeypatch.setattr("local_shell_mcp.settings.get_settings", lambda: settings)
    response = await lifecycle.join_script(object())
    assert response.media_type == "text/x-shellscript"
    assert "SERVER=https://public" in response.body.decode()

    settings.public_base_url = None
    response = await lifecycle.join_script(object())
    assert "SERVER=http://127.0.0.1:8000" in response.body.decode()


def test_remote_routes_replace_join_and_add_manifest():
    routes = lifecycle.remote_routes()
    paths = [route.path for route in routes]
    assert paths.count(lifecycle.REMOTE_JOIN_PATH) == 1
    assert lifecycle.WORKER_MANIFEST_PATH in paths


def test_print_status_optional_fields(capsys):
    lifecycle._print_status(
        {
            "installed": False,
            "running": False,
            "pid": None,
            "server": None,
            "name": None,
            "state_dir": "/state",
            "log": "/log",
        }
    )
    output = capsys.readouterr().out
    assert "Installed: no" in output
    assert "PID:" not in output
    assert "Server:" not in output


def test_cli_status(monkeypatch, capsys):
    monkeypatch.setattr(
        lifecycle,
        "worker_status",
        lambda: {
            "installed": True,
            "running": True,
            "pid": 7,
            "server": "https://s",
            "name": "n",
            "workdir": "/tmp",
            "state_dir": "/state",
            "log": "/state/log",
        },
    )
    lifecycle.run_worker_cli(["status"])
    output = capsys.readouterr().out
    assert "Installed: yes" in output
    assert "PID:       7" in output


def test_cli_start_stop_restart(monkeypatch, capsys):
    monkeypatch.setattr(lifecycle, "start_worker", lambda: 9)
    monkeypatch.setattr(lifecycle, "stop_worker", lambda: True)
    lifecycle.run_worker_cli(["start"])
    lifecycle.run_worker_cli(["stop"])
    lifecycle.run_worker_cli(["restart"])
    output = capsys.readouterr().out
    assert "Worker started with PID 9" in output
    assert "Worker stopped" in output
    assert "Worker restarted with PID 9" in output

    monkeypatch.setattr(lifecycle, "stop_worker", lambda: False)
    lifecycle.run_worker_cli(["stop"])
    assert "not running" in capsys.readouterr().out


def test_cli_enroll_and_run(monkeypatch, capsys):
    async def fake_enroll(*args):
        return {"name": "n", "server": "https://s"}

    async def fake_run():
        return None

    monkeypatch.setattr(lifecycle, "enroll_worker", fake_enroll)
    monkeypatch.setattr(lifecycle, "run_installed_worker", fake_run)
    lifecycle.run_worker_cli(
        ["enroll", "--server", "https://s", "--invite", "i", "--workdir", "/tmp"]
    )
    lifecycle.run_worker_cli(["run"])
    assert "Enrolled worker n" in capsys.readouterr().out


def test_cli_legacy_passthrough(monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle, "legacy_run_worker_cli", calls.append)
    lifecycle.run_worker_cli(["--server", "https://s", "--invite", "i"])
    assert calls == [["--server", "https://s", "--invite", "i"]]


def test_cli_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr(lifecycle, "start_worker", lambda: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(SystemExit) as exc:
        lifecycle.run_worker_cli(["start"])
    assert exc.value.code == 130


def test_cli_failure(monkeypatch, capsys):
    monkeypatch.setattr(lifecycle, "start_worker", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(SystemExit) as exc:
        lifecycle.run_worker_cli(["start"])
    assert exc.value.code == 1
    assert "worker command failed" in capsys.readouterr().err
