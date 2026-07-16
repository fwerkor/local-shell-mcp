from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from local_shell_mcp import worker_lifecycle as lifecycle


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    return tmp_path


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


def test_config_errors(state_dir):
    with pytest.raises(RuntimeError, match="not installed"):
        lifecycle.read_worker_config()
    lifecycle.worker_config_path().write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unsupported"):
        lifecycle.read_worker_config()
    lifecycle.worker_config_path().write_text(
        json.dumps({"version": 1, "server": "x", "name": "", "workdir": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="missing name"):
        lifecycle.read_worker_config()


def test_pid_helpers_remove_stale_pid(state_dir, monkeypatch):
    lifecycle.worker_pid_path().write_text("123", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "_pid_is_running", lambda pid: False)
    assert lifecycle.read_worker_pid() is None
    assert not lifecycle.worker_pid_path().exists()


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

    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: 321)
    assert lifecycle.start_worker() == 321
    assert len(calls) == 1


def test_stop_worker(state_dir, monkeypatch):
    lifecycle.worker_pid_path().write_text("44", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: 44)
    states = iter([True, False, False])
    monkeypatch.setattr(lifecycle, "_pid_is_running", lambda pid: next(states, False))
    signals = []
    monkeypatch.setattr(lifecycle.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    assert lifecycle.stop_worker(timeout_s=0.1) is True
    assert signals[0][0] == 44


def test_stop_worker_when_not_running(monkeypatch):
    monkeypatch.setattr(lifecycle, "read_worker_pid", lambda: None)
    assert lifecycle.stop_worker() is False


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


def test_join_script_contains_cache_path_and_path_setup():
    script = lifecycle._join_script("https://server")
    assert "worker-manifest.json" in script
    assert "runtime.sha256" in script
    assert 'export PATH="$HOME/.local/bin:$PATH"' in script
    assert "worker enroll" in script
    assert "worker start" in script
    assert "--invite \"$INVITE\"" in script
    run_section = script.split("Persistent worker installed and started.", 1)[1]
    assert "remote_worker" in run_section


def test_remote_routes_replace_join_and_add_manifest():
    routes = lifecycle.remote_routes()
    paths = [route.path for route in routes]
    assert paths.count(lifecycle.REMOTE_JOIN_PATH) == 1
    assert lifecycle.WORKER_MANIFEST_PATH in paths


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


def test_cli_failure(monkeypatch, capsys):
    monkeypatch.setattr(lifecycle, "start_worker", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(SystemExit) as exc:
        lifecycle.run_worker_cli(["start"])
    assert exc.value.code == 1
    assert "worker command failed" in capsys.readouterr().err
