from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import local_shell_mcp.human_ui as human_ui


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ({"info": {"version": "1.2.3"}}, "1.2.3"),
        ({"info": {"lsm_version": "2.0"}}, "2.0"),
        ({"info": {"local_shell_mcp": {"version": "3.0"}}}, "3.0"),
        ({"info": {"local_shell_mcp": {}}}, None),
        ({"info": "bad"}, None),
    ],
)
def test_human_ui_remote_version_shapes(machine: dict[str, object], expected: str | None) -> None:
    assert human_ui._remote_version(machine) == expected

def test_human_ui_linux_cpu_time_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProc:
        def __init__(self, text: str) -> None:
            self.text = text

        def read_text(self, **kwargs) -> str:
            return self.text

    monkeypatch.setattr(human_ui, "Path", lambda path: FakeProc("cpu 1 2 3\n"))
    assert human_ui._read_linux_cpu_times() is None
    monkeypatch.setattr(human_ui, "Path", lambda path: FakeProc("cpu 1 2 3 4\n"))
    assert human_ui._read_linux_cpu_times() == (10, 4)
    monkeypatch.setattr(human_ui, "Path", lambda path: FakeProc("cpu 1 2 3 4 5\n"))
    assert human_ui._read_linux_cpu_times() == (15, 9)
    monkeypatch.setattr(human_ui, "Path", lambda path: FakeProc("bad"))
    assert human_ui._read_linux_cpu_times() is None

def test_human_ui_local_system_snapshot_delta_and_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    human_ui._CPU_SAMPLE = (100, 40)
    human_ui._NETWORK_SAMPLE = (9.0, 1000, 2000)
    monkeypatch.setattr(human_ui.time, "time", lambda: 100.0)
    monkeypatch.setattr(human_ui.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(human_ui.os, "getloadavg", lambda: (0.5, 0.0, 0.0), raising=False)
    monkeypatch.setattr(human_ui.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(human_ui, "_read_linux_cpu_times", lambda: (200, 60))
    monkeypatch.setattr(human_ui, "_read_linux_network", lambda: (1600, 2600))
    monkeypatch.setattr(human_ui, "_read_linux_memory", lambda: (1000, 250))
    monkeypatch.setattr(human_ui, "_read_worker_memory", lambda: (1000, 250))
    monkeypatch.setattr(
        human_ui.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=2000, used=500),
    )

    class UptimePath:
        def read_text(self, **kwargs) -> str:
            return "42.5 0"

    monkeypatch.setattr(human_ui, "Path", lambda path: UptimePath())
    monkeypatch.setattr(human_ui, "get_settings", lambda: SimpleNamespace(workspace_root=tmp_path))
    snapshot = human_ui._local_system_snapshot()
    assert snapshot["cpu_percent"] == 80.0
    assert snapshot["network_rx_bps"] == 600.0
    assert snapshot["memory_percent"] == 25.0
    assert snapshot["disk_percent"] == 25.0
    assert snapshot["uptime_s"] == 42

    human_ui._CPU_SAMPLE = None
    human_ui._NETWORK_SAMPLE = None
    monkeypatch.setattr(human_ui, "_read_linux_cpu_times", lambda: None)
    monkeypatch.setattr(human_ui, "_read_linux_network", lambda: None)
    monkeypatch.setattr(human_ui, "_read_linux_memory", lambda: None)
    monkeypatch.setattr(human_ui, "_read_worker_memory", lambda: None)
    monkeypatch.setattr(
        human_ui.shutil,
        "disk_usage",
        lambda path: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    fallback = human_ui._local_system_snapshot()
    assert fallback["cpu_percent"] == 12.5
    assert fallback["memory_percent"] is None
    assert fallback["disk_percent"] is None

def test_human_ui_bounded_float_validation() -> None:
    assert (
        human_ui._bounded_float(None, default=1.5, minimum=1.0, maximum=2.0, label="ratio") == 1.5
    )
    with pytest.raises(ValueError, match="must be a number"):
        human_ui._bounded_float("bad", default=1.5, minimum=1.0, maximum=2.0, label="ratio")
    with pytest.raises(ValueError, match="between"):
        human_ui._bounded_float("3", default=1.5, minimum=1.0, maximum=2.0, label="ratio")

@pytest.mark.asyncio
async def test_human_ui_remote_call_python_and_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        def __init__(self) -> None:
            self.result = {"ok": True, "data": {"value": 1}}
            self.calls = []

        async def call(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self.result

    manager = Manager()
    monkeypatch.setattr(human_ui, "remote_manager", lambda: manager)
    assert await human_ui._remote_call(
        "node", "run_python_tool", {"code": "print(1)", "timeout_s": 5}
    ) == {"value": 1}
    assert manager.calls[-1][1]["execution_timeout_s"] == 5
    manager.result = {"ok": True, "data": {"status": "error", "error_type": "Boom"}}
    with pytest.raises(RuntimeError, match="Boom"):
        await human_ui._remote_call("node", "file_read", {})

def test_human_ui_spawn_tui_process_unix_and_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(human_ui, "get_settings", lambda: SimpleNamespace(port=9999))
    monkeypatch.setattr(human_ui, "resolve_tui_command", lambda: ["lsm", "tui"])
    monkeypatch.setattr(
        human_ui,
        "_UnixPtyProcess",
        lambda command, env, cols, rows, ui_token=None: (
            "unix",
            command,
            env,
            cols,
            rows,
            ui_token,
        ),
    )
    monkeypatch.setattr(
        human_ui,
        "_WindowsPtyProcess",
        lambda command, env, cols, rows: ("windows", command, env, cols, rows),
    )
    monkeypatch.setattr(human_ui.os, "name", "posix")
    unix = human_ui._spawn_tui_process(80, 24, ui_token="secret")
    assert unix[0] == "unix"
    assert unix[-1] == "secret"
    monkeypatch.setattr(human_ui.os, "name", "nt")
    windows = human_ui._spawn_tui_process(80, 24, ui_token="secret")
    assert windows[0] == "windows"
    assert windows[2][human_ui.UI_LOCAL_TOKEN_ENV] == "secret"

@pytest.mark.asyncio
async def test_human_ui_pty_exit_code_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    unix = object.__new__(human_ui._UnixPtyProcess)

    class Exited:
        def poll(self):
            return 7

    unix.process = Exited()
    assert await unix.exit_code() == 7

    class Running:
        def poll(self):
            return None

        def wait(self):
            return 9

    unix.process = Running()
    assert await unix.exit_code() == 9

    windows = object.__new__(human_ui._WindowsPtyProcess)

    class WindowsExited:
        exitstatus = 3

        def isalive(self):
            return False

    windows.process = WindowsExited()
    assert await windows.exit_code() == 3

    class WindowsBroken:
        def isalive(self):
            raise RuntimeError("broken")

    windows.process = WindowsBroken()
    assert await windows.exit_code() is None

def _tmux_result(*, ok: bool = True, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(ok=ok, stdout=stdout, stderr=stderr)

@pytest.mark.asyncio
async def test_human_ui_tmux_scrollback_baseline_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = SimpleNamespace(_tmux_session_id="session")
    responses = [
        _tmux_result(ok=False, stderr="tmux failed"),
        _tmux_result(stdout="bad\n"),
        _tmux_result(stdout="%1\t10\tcopy-mode\t3\n"),
    ]

    async def command(args):
        return responses.pop(0)

    monkeypatch.setattr(human_ui, "_tmux_scrollback_command", command)
    with pytest.raises(RuntimeError, match="tmux failed"):
        await human_ui._tmux_scrollback_baseline(process)
    with pytest.raises(RuntimeError, match="Unexpected"):
        await human_ui._tmux_scrollback_baseline(process)
    state, pane = await human_ui._tmux_scrollback_baseline(process)
    assert pane == "%1"
    assert state["history"] == 10
    assert state["position"] == 3

@pytest.mark.asyncio
async def test_human_ui_tmux_scroll_and_restore_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = SimpleNamespace(_tmux_session_id="session")
    state = {"supported": True, "history": 10, "position": 0, "copy_mode": False}
    commands: list[list[str]] = []

    async def current(process, pane_id=None):
        return dict(state)

    async def command(args):
        commands.append(args)
        return _tmux_result()

    monkeypatch.setattr(human_ui, "_tmux_scrollback_state", current)
    monkeypatch.setattr(human_ui, "_tmux_scrollback_command", command)
    await human_ui._tmux_scroll_to(process, 4)
    assert any("copy-mode" in row for row in commands)
    assert any("scroll-up" in row for row in commands)

    commands.clear()
    state.update({"position": 4, "copy_mode": True})
    assert await human_ui._tmux_scroll_to(process, 4) == state
    state.update({"position": 2, "copy_mode": True})
    await human_ui._tmux_scroll_to(process, 0)
    assert any("cancel" in row for row in commands)

    commands.clear()
    state.update({"position": 0, "copy_mode": False})
    await human_ui._tmux_restore_copy_mode_position(process, 3)
    assert any("copy-mode" in row for row in commands)
    assert any("history-bottom" in row for row in commands)
    assert any("scroll-up" in row for row in commands)
