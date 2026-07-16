from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

from local_shell_mcp import remote_worker_state as state


def _configure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_BIN_DIR", raising=False)


def test_worker_config_round_trip_and_runtime_metadata(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    written = state.write_worker_config(
        server="https://example.test/",
        name="worker-a",
        workdir="/workspace",
        runtime_digest="abc",
        runtime_version="3.0.0",
    )

    assert written["server"] == "https://example.test"
    assert state.read_worker_config() == written
    updated = state.update_runtime_metadata("def", "3.0.1")
    assert updated["runtime_digest"] == "def"
    assert json.loads(state.worker_config_path().read_text(encoding="utf-8"))["runtime_version"] == "3.0.1"
    if os.name != "nt":
        assert stat.S_IMODE(state.worker_config_path().stat().st_mode) == 0o600


def test_worker_config_validation(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    state.worker_config_path().parent.mkdir(parents=True)
    state.worker_config_path().write_text('{"version": 2}', encoding="utf-8")
    try:
        state.read_worker_config()
    except ValueError as exc:
        assert "invalid worker config" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected invalid config")


def test_install_launcher_and_path_configuration_are_idempotent(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(state, "_is_windows", lambda: False)
    monkeypatch.setenv("PATH", "/usr/bin")
    launcher = state.install_launcher()
    script = launcher.read_text(encoding="utf-8")
    assert str(state.worker_state_dir().resolve()) in script
    assert str(Path(sys.executable).resolve()) in script
    assert "-m local_shell_mcp.main" in script
    if os.name != "nt":
        assert stat.S_IMODE(launcher.stat().st_mode) == 0o755

    private_bashrc = tmp_path / ".bashrc"
    private_bashrc.write_text("# private\n", encoding="utf-8")
    private_bashrc.chmod(0o600)
    changed = state.ensure_user_bin_on_path("bash")
    assert changed == [tmp_path / ".profile", private_bashrc]
    assert str(tmp_path / ".local" / "bin") == os.environ["PATH"].split(os.pathsep)[0]
    assert state.ensure_user_bin_on_path("bash") == []
    assert private_bashrc.read_text(encoding="utf-8").count("# local-shell-mcp") == 1
    if os.name != "nt":
        assert stat.S_IMODE(private_bashrc.stat().st_mode) == 0o600


def test_custom_bin_path_is_written_to_shell_profile(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(state, "_is_windows", lambda: False)
    custom = tmp_path / "commands"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_BIN_DIR", str(custom))
    state.ensure_user_bin_on_path("sh")
    profile = (tmp_path / ".profile").read_text(encoding="utf-8")
    assert str(custom) in profile


def test_fish_path_configuration(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(state, "_is_windows", lambda: False)
    changed = state.ensure_user_bin_on_path("fish")
    fish = tmp_path / ".config" / "fish" / "config.fish"
    assert fish in changed
    assert "fish_add_path" in fish.read_text(encoding="utf-8")


def test_windows_launcher_and_user_path(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(state, "_is_windows", lambda: True)
    monkeypatch.setattr(state.os, "pathsep", ";")
    launcher = state.install_launcher()
    assert launcher.name == "local-shell-mcp.cmd"
    script = launcher.read_text(encoding="utf-8")
    assert "@echo off" in script
    assert str(state.worker_state_dir().resolve()) in script
    assert str(Path(sys.executable).resolve()) in script

    stored = {"Path": ("C:\\Windows", 2)}
    writes = []

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def query_value(_key, name):
        if name not in stored:
            raise FileNotFoundError
        return stored[name]

    def set_value(_key, name, _reserved, value_type, value):
        stored[name] = (value, value_type)
        writes.append(value)

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_QUERY_VALUE=1,
        KEY_SET_VALUE=2,
        REG_EXPAND_SZ=2,
        CreateKeyEx=lambda *args: Key(),
        QueryValueEx=query_value,
        SetValueEx=set_value,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setenv("PATH", "C:\\Windows")
    assert state.ensure_user_bin_on_path() == []
    assert writes and str(launcher.parent) in writes[-1]


def test_user_home_falls_back_to_userprofile(tmp_path, monkeypatch):
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert state.user_home() == tmp_path
