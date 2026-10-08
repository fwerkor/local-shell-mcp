from __future__ import annotations

import contextlib
import io
import os
import plistlib
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

import local_shell_mcp.cli_call as cli_call
import local_shell_mcp.dynamic_mcp as dynamic_mcp
import local_shell_mcp.fs_ops as fs_ops
import local_shell_mcp.gui.base as gui_base
import local_shell_mcp.human_ui as human_ui
import local_shell_mcp.jobs as jobs_module
import local_shell_mcp.oauth as oauth_module
import local_shell_mcp.remote as remote_module
import local_shell_mcp.remote_worker_service as worker_service
import local_shell_mcp.tools as mcp_tools
import local_shell_mcp.transfer_ops as transfer_ops
from local_shell_mcp.auth import Principal
from local_shell_mcp.errors import PathNotFoundError
from local_shell_mcp.settings import get_settings


class _FakeHandle:
    def __init__(self, fd: int = 7) -> None:
        self._fd = fd
        self.seeks: list[tuple[int, ...]] = []

    def fileno(self) -> int:
        return self._fd

    def seek(self, *args: int) -> None:
        self.seeks.append(args)


def test_gui_action_deadline_rejects_invalid_value() -> None:
    with pytest.raises(gui_base.GuiStaleStateError, match="deadline is invalid"):
        gui_base._assert_action_fresh({"_observation_deadline": object()})


def test_gui_bounding_helpers_cover_invalid_records() -> None:
    bounded, kept = gui_base._bounded_elements([None, {"role": "button"}])
    assert bounded == [{"role": "button"}]
    assert kept == set()

    assert gui_base._bounded_window_record({"pid": "not-a-pid"}) == {"pid": 0}
    assert gui_base._bounded_window_records("not-a-list") == []
    assert gui_base._bounded_window_records([None, {"pid": "bad"}]) == [{"pid": 0}]


@pytest.mark.parametrize(
    ("action", "message"),
    [
        ({"type": "click", "x": 1}, "requires both x and y"),
        ({"type": "click"}, "requires x and y"),
        ({"type": "drag", "x": 1, "y": 2}, "drag requires to_x and to_y"),
    ],
)
def test_gui_coordinate_validation_errors(action: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        gui_base._validate_coordinate_action(
            {"bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            action,
            has_locator=False,
        )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        ({"type": "key", "keys": 123}, "must be a string or list"),
        ({"type": "key", "keys": "   "}, "must contain at least one key"),
        (
            {"type": "key", "keys": "x" * (gui_base.GUI_MAX_KEYS_BYTES + 1)},
            "may not exceed",
        ),
        ({"type": "wait", "seconds": object()}, "seconds must be numeric"),
    ],
)
def test_gui_batch_validation_edge_inputs(action: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        gui_base.GuiManager._validate_action_batch([action])


def test_prepare_gui_screenshot_path_rejects_insecure_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gui_base, "temp_dir", lambda: tmp_path)

    def fail_chmod(self: Path, mode: int) -> None:
        raise OSError("denied")

    monkeypatch.setattr(Path, "chmod", fail_chmod)
    with pytest.raises(gui_base.GuiUnavailableError, match="directory"):
        gui_base._prepare_gui_screenshot_path("shot")


def test_prepare_gui_screenshot_path_removes_insecure_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gui_base, "temp_dir", lambda: tmp_path)
    calls = 0
    original = Path.chmod

    def fail_second(self: Path, mode: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("denied")
        original(self, mode)

    monkeypatch.setattr(Path, "chmod", fail_second)
    with pytest.raises(gui_base.GuiUnavailableError, match="file"):
        gui_base._prepare_gui_screenshot_path("shot")
    assert not list(tmp_path.glob("shot-*.png"))


def test_prepare_gui_screenshot_path_cleans_up_failed_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gui_base, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(gui_base.os, "O_BINARY", 0, raising=False)

    def fail_lease(path: Path) -> None:
        raise RuntimeError("lease failed")

    monkeypatch.setattr(gui_base, "acquire_temp_file_lease", fail_lease)
    with pytest.raises(RuntimeError, match="lease failed"):
        gui_base._prepare_gui_screenshot_path("shot")
    assert not list(tmp_path.glob("shot-*.png"))


def test_secure_gui_screenshot_file_reports_chmod_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(b"")

    def fail_chmod(self: Path, mode: int) -> None:
        raise OSError("denied")

    monkeypatch.setattr(Path, "chmod", fail_chmod)
    with pytest.raises(gui_base.GuiUnavailableError, match="secure"):
        gui_base._secure_gui_screenshot_file(path)


def test_worker_lock_windows_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int, int]] = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            calls.append((fd, mode, count))

    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt)
    monkeypatch.setattr(worker_service.os, "name", "nt")
    handle = _FakeHandle()
    worker_service._lock_worker_file(handle)
    worker_service._unlock_worker_file(handle)
    assert calls == [(7, 1, 1), (7, 2, 1)]


def test_worker_lock_reexec_prepare_and_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeHandle(11)
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(worker_service, "_active_worker_lock_handle", handle)
    monkeypatch.setattr(
        worker_service.os, "set_inheritable", lambda fd, value: calls.append((fd, value))
    )

    assert worker_service.prepare_worker_lock_reexec() == 11
    assert os.environ[worker_service._WORKER_LOCK_FD_ENV] == "11"
    worker_service.cancel_worker_lock_reexec(11)
    assert worker_service._WORKER_LOCK_FD_ENV not in os.environ
    assert calls == [(11, True), (11, False)]


def test_adopt_worker_lock_handle_rejects_bad_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(worker_service._WORKER_LOCK_FD_ENV, "not-an-fd")
    assert worker_service._adopt_worker_lock_handle() is None
    assert worker_service._WORKER_LOCK_FD_ENV not in os.environ


def test_adopt_worker_lock_handle_accepts_inherited_descriptor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "lock"
    with path.open("w+b") as source:
        fd = os.dup(source.fileno())
    monkeypatch.setenv(worker_service._WORKER_LOCK_FD_ENV, str(fd))
    adopted = worker_service._adopt_worker_lock_handle()
    assert adopted is not None
    try:
        assert adopted.fileno() == fd
    finally:
        adopted.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"ProgramArguments": "bad"},
        {"ProgramArguments": []},
        {"ProgramArguments": [123]},
        {"ProgramArguments": ["relative/worker"]},
    ],
)
def test_installed_launchd_launcher_rejects_invalid_payloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: dict[str, object]
) -> None:
    plist = tmp_path / "worker.plist"
    plist.write_bytes(plistlib.dumps(payload))
    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    assert worker_service._installed_launchd_launcher_path() is None


def test_installed_launchd_launcher_handles_missing_and_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / "worker.plist"
    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    assert worker_service._installed_launchd_launcher_path() is None

    launcher = tmp_path / "bin" / "local-shell-mcp"
    plist.write_bytes(plistlib.dumps({"ProgramArguments": [str(launcher)]}))
    assert worker_service._installed_launchd_launcher_path() == launcher


def test_windows_pythonw_executable_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(worker_service.sys, "executable", str(python))

    with pytest.raises(RuntimeError, match="pythonw.exe is required"):
        worker_service._windows_pythonw_executable()

    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_bytes(b"")
    assert worker_service._windows_pythonw_executable() == pythonw.resolve()


def test_refresh_service_definition_launchd_and_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / "worker.plist"
    plist.write_bytes(plistlib.dumps({"ProgramArguments": [str(tmp_path / "old")]}))
    launcher = tmp_path / "launcher"
    written = tmp_path / "written.plist"

    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    monkeypatch.setattr(worker_service, "worker_launcher_path", lambda: launcher)
    monkeypatch.setattr(worker_service, "_write_launchd_plist", lambda path=None: written)
    monkeypatch.setattr(worker_service, "service_kind", lambda: "launchd")
    assert worker_service.refresh_installed_service_definition() == written

    service_file = tmp_path / "worker.pyw"
    monkeypatch.setattr(worker_service, "service_kind", lambda: "scheduled-task")
    monkeypatch.setattr(worker_service, "_windows_task_status", lambda: {"state": 1})
    monkeypatch.setattr(worker_service, "_write_windows_task_launcher", lambda: service_file)
    registered: list[Path] = []
    monkeypatch.setattr(worker_service, "_register_windows_task", registered.append)
    assert worker_service.refresh_installed_service_definition() == service_file
    assert registered == [service_file]


def test_process_identity_short_circuits_dead_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_service, "_pid_is_running", lambda pid: False)
    assert worker_service._process_identity(123) is None


def test_start_service_launchd_bootstraps_after_failed_kickstart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / "worker.plist"
    plist.write_text("x")
    monkeypatch.setattr(worker_service, "service_kind", lambda: "launchd")
    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    monkeypatch.setattr(worker_service, "_user_id", lambda: 501)
    commands: list[object] = []

    def fake_run(command, check=True):
        commands.append(command)
        return SimpleNamespace(returncode=1 if "kickstart" in command else 0, stdout="", stderr="")

    monkeypatch.setattr(worker_service, "_run", fake_run)
    monkeypatch.setattr(worker_service, "service_status", lambda: {"running": True})
    assert worker_service.start_service() == {"running": True}
    assert any("bootstrap" in command for command in commands)


def _transfer_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    return tmp_path


def test_transfer_stat_reports_other_file_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    fifo = root / "pipe"
    os.mkfifo(fifo)
    result = transfer_ops.transfer_stat("pipe")
    assert result["type"] == "other"


def test_transfer_begin_write_cleans_up_when_metadata_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(
        transfer_ops,
        "_write_transfer_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("metadata failed")),
    )
    with pytest.raises(RuntimeError, match="metadata failed"):
        transfer_ops.transfer_begin_write("dest.bin")
    assert not list(root.glob(".dest.bin.local-shell-mcp-transfer-*"))


def test_transfer_prepare_and_refresh_missing_stream_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_prepare_stream_write("dest.bin", "missing")
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_refresh_stream_write("dest.bin", "missing")


def test_transfer_refresh_stream_write_detects_missing_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    begin = transfer_ops.transfer_begin_write("dest.bin")
    dst = transfer_ops.resolve_path("dest.bin", follow_final_symlink=False)
    tmp = transfer_ops._transfer_temp_path(dst, begin["transfer_id"])
    transfer_ops._transfer_metadata_path(tmp).unlink()
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_refresh_stream_write("dest.bin", begin["transfer_id"])
    tmp.unlink(missing_ok=True)


def test_transfer_mark_complete_rejects_missing_and_wrong_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_mark_complete_write("dest.bin", "missing")

    begin = transfer_ops.transfer_begin_write("dest.bin", expected_bytes=2)
    with pytest.raises(ValueError, match="size mismatch"):
        transfer_ops.transfer_mark_complete_write("dest.bin", begin["transfer_id"])
    transfer_ops.transfer_abort_write("dest.bin", begin["transfer_id"])


def test_finish_verified_write_rejects_invalid_stream_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="must be a SHA-256"):
        transfer_ops.transfer_finish_verified_write("x", "id", 0, "0" * 64, "not-a-digest")
    with pytest.raises(ValueError, match="file sha256 mismatch"):
        transfer_ops.transfer_finish_verified_write("x", "id", 0, "0" * 64, "1" * 64)


def test_archive_path_and_cancelled_pack_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    assert transfer_ops._archive_path_from_result({}) is None
    assert transfer_ops._archive_path_from_result({"archive_path": ""}) is None
    archive = root / "packed.tar"
    archive.write_bytes(b"x")
    transfer_ops.refresh_temp_file_lease(archive)
    assert transfer_ops._archive_path_from_result({"archive_path": "packed.tar"}) == archive
    transfer_ops._cleanup_cancelled_pack_result({"archive_path": "packed.tar"})
    assert not archive.exists()


def test_safe_members_rejects_duplicate_and_escape_via_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    dst = root / "dst"
    dst.mkdir()
    archive = root / "dup.tar"
    with tarfile.open(archive, "w") as tar:
        for _ in range(2):
            info = tarfile.TarInfo("same.txt")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    with (
        tarfile.open(archive, "r") as tar,
        pytest.raises(ValueError, match="duplicate archive member"),
    ):
        transfer_ops._safe_members(tar, dst)

    outside = root / "outside"
    outside.mkdir()
    (dst / "link").symlink_to(outside, target_is_directory=True)
    escape = root / "escape.tar"
    with tarfile.open(escape, "w") as tar:
        info = tarfile.TarInfo("link/file.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with (
        tarfile.open(escape, "r") as tar,
        pytest.raises(ValueError, match="escapes destination"),
    ):
        transfer_ops._safe_members(tar, dst)


def test_unpack_rejects_non_file_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    (root / "archive-dir").mkdir()
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_unpack_archive("archive-dir", "dst")


def test_unpack_handles_missing_member_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    archive = root / "payload.tar"
    archive.write_bytes(b"placeholder")
    info = tarfile.TarInfo("file.txt")
    info.size = 1

    class FakeTar:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extractfile(self, member):
            return None

    monkeypatch.setattr(transfer_ops.tarfile, "open", lambda *a, **k: FakeTar())
    monkeypatch.setattr(transfer_ops, "_safe_members", lambda *a, **k: [info])
    with pytest.raises(ValueError, match="has no file data"):
        transfer_ops.transfer_unpack_archive("payload.tar", "dst", cleanup_archive=False)


def test_unpack_rejects_unknown_member_after_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    archive = root / "payload.tar"
    archive.write_bytes(b"placeholder")
    info = tarfile.TarInfo("odd")
    info.type = tarfile.FIFOTYPE

    class FakeTar:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(transfer_ops.tarfile, "open", lambda *a, **k: FakeTar())
    monkeypatch.setattr(transfer_ops, "_safe_members", lambda *a, **k: [info])
    with pytest.raises(ValueError, match="unsupported archive member type"):
        transfer_ops.transfer_unpack_archive("payload.tar", "dst", cleanup_archive=False)


def test_unpack_restores_backup_when_publish_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    dst = root / "dst"
    dst.mkdir()
    (dst / "old.txt").write_text("old")
    payload = root / "new.txt"
    payload.write_text("new")
    archive = root / "payload.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(payload, arcname="new.txt")

    original_replace = transfer_ops.os.replace
    calls = 0

    def fail_publish(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publish failed")
        return original_replace(source, target)

    monkeypatch.setattr(transfer_ops.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publish failed"):
        transfer_ops.transfer_unpack_archive("payload.tar", "dst", cleanup_archive=False)
    assert (dst / "old.txt").read_text() == "old"


def test_unpack_reports_archive_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    payload = root / "new.txt"
    payload.write_text("new")
    archive = root / "payload.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(payload, arcname="new.txt")
    original_unlink = Path.unlink

    def fail_archive_unlink(self: Path, *args, **kwargs):
        if self == archive:
            raise OSError("archive cleanup failed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_archive_unlink)
    result = transfer_ops.transfer_unpack_archive("payload.tar", "dst")
    assert result["archive_deleted"] is False
    assert "archive cleanup failed" in result["cleanup_errors"][0]


def test_pack_dir_detects_source_change_before_add(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "src" / "file.txt").write_text("x")
    original_signature = transfer_ops._entry_signature
    seen = 0

    def changed(path: Path):
        nonlocal seen
        value = original_signature(path)
        if path.name == "file.txt":
            seen += 1
            if seen >= 2:
                return ("file", value[1] + 1, *value[2:])
        return value

    monkeypatch.setattr(transfer_ops, "_entry_signature", changed)
    with pytest.raises(RuntimeError, match="changed during packing"):
        transfer_ops.transfer_pack_dir("src", compression="none")


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected"),
    [
        (
            "run_shell",
            {"timeout_s": mcp_tools.PUBLIC_RUN_SHELL_TIMEOUT_CAP_S + 1},
            mcp_tools.PUBLIC_RUN_SHELL_TIMEOUT_CAP_S + 15,
        ),
        ("run_shell", {"timeout_s": 5, "machine": "node"}, 155.0),
        ("browser_run_script", {"timeout_s": 5}, 20.0),
        ("browser_run_script", {"timeout_s": 5, "machine": "node"}, 155.0),
        ("browser_snapshot", {}, 300.0),
        ("file_read", {"machine": "node"}, 120.0),
    ],
)
def test_public_tool_timeout_uncovered_paths(
    tool_name: str, arguments: dict[str, object], expected: float
) -> None:
    assert mcp_tools._public_tool_timeout_s(tool_name, arguments) == expected


def test_current_principal_allows_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: None)
    assert mcp_tools._current_principal_allows("shell:write")

    local = Principal(None, "local", {"auth": "local-cli"})
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: local)
    assert mcp_tools._current_principal_allows("anything")

    oauth = Principal("user@example.com", "subject", {"auth": "oauth", "scope": "shell:read"})
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: oauth)
    assert mcp_tools._current_principal_allows("shell:read")
    assert not mcp_tools._current_principal_allows("shell:write")


class _AuditAction(BaseModel):
    text: str | None = None
    keys: list[str] | None = None


def test_safe_audit_call_argument_redaction_edges() -> None:
    assert mcp_tools._safe_audit_call_arguments(
        "mcp_tool_call", {"name": "x:y", "arguments": "bad", "timeout_s": 1}
    ) == {"name": "x:y", "argument_keys": [], "timeout_s": 1}

    managed = mcp_tools._safe_audit_call_arguments(
        "mcp_manage",
        {"action": "env_set", "env": {"TOKEN": "secret"}, "headers": {"X": "y"}, "value": "z"},
    )
    assert managed["env"] == {"TOKEN": "<redacted>"}
    assert managed["headers"] == {"X": "<redacted>"}
    assert managed["value"] == "<redacted>"

    gui = mcp_tools._safe_audit_call_arguments(
        "gui_action",
        {
            "actions": [
                _AuditAction(text="secret", keys=["A"]),
                {"type": "type", "text": "secret"},
                "opaque",
            ]
        },
    )
    assert gui["actions"][0]["text"] == "<redacted>"
    assert gui["actions"][0]["keys"] == "<redacted>"
    assert gui["actions"][1]["text"] == "<redacted>"
    assert gui["actions"][2] == "opaque"

    browser = mcp_tools._safe_audit_call_arguments(
        "browser_act", {"actions": [{"value": "secret", "action": "fill"}, "opaque"]}
    )
    assert browser["actions"] == [
        {"value": "<redacted>", "action": "fill"},
        "opaque",
    ]


def test_secret_scan_candidates_falls_back_when_ripgrep_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    (base / ".gitignore").write_text("ignored.txt\n")
    (base / "ignored.txt").write_text("ignore")
    (base / "keep.txt").write_text("keep")
    (base / "skip.py").write_text("skip")
    (base / ".git").mkdir()
    (base / ".git" / "secret.txt").write_text("hidden")

    monkeypatch.setattr(
        mcp_tools.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rg missing")),
    )
    candidates = mcp_tools._secret_scan_candidates(base, "*.txt")
    assert candidates == [base / "keep.txt"]


def test_secret_scan_sync_handles_binary_truncated_errors_and_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = _transfer_workspace(tmp_path, monkeypatch)
    files = [base / name for name in ("bad", "binary", "truncated", "secret")]
    for path in files:
        path.write_text("x")
    monkeypatch.setattr(mcp_tools, "_secret_scan_candidates", lambda *args, **kwargs: files)

    def fake_read(path: str) -> dict[str, object]:
        name = Path(path).name
        if name == "bad":
            raise OSError("unreadable")
        if name == "binary":
            return {"binary": True, "content": ""}
        if name == "truncated":
            return {"binary": False, "truncated": True, "content": 'token="dummy-value"'}
        return {"binary": False, "truncated": False, "content": "ghp_" + "a" * 40}

    monkeypatch.setattr(mcp_tools, "read_text", fake_read)
    result = mcp_tools._secret_scan_sync(".", max_results=1)
    assert result["truncated"] is True
    assert result["truncated_files"] == 1
    assert len(result["findings"]) == 1


def test_gui_temp_path_rejects_outside_and_symlink_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    temp = transfer_ops.temp_dir()
    outside = root / "outside.png"
    with pytest.raises(ValueError, match="outside"):
        mcp_tools._gui_temp_path(str(outside), must_exist=False)

    escaped = root / "escaped.png"
    escaped.write_bytes(b"x")
    link = temp / "shot.png"
    link.symlink_to(escaped)
    with pytest.raises(ValueError, match="escapes"):
        mcp_tools._gui_temp_path(str(link), must_exist=True)


def test_remote_inline_gui_image_rejects_invalid_payloads() -> None:
    assert mcp_tools._remote_inline_gui_image({}, "shot.png") is None
    with pytest.raises(RuntimeError, match="payload is invalid"):
        mcp_tools._remote_inline_gui_image({"screenshot_inline_b64": 3}, "shot.png")
    with pytest.raises(RuntimeError, match="payload is invalid"):
        mcp_tools._remote_inline_gui_image({"screenshot_inline_b64": "!!!"}, "shot.png")
    with pytest.raises(RuntimeError, match="size does not match"):
        mcp_tools._remote_inline_gui_image(
            {"screenshot_inline_b64": "aGVsbG8=", "screenshot_inline_size": 99},
            "shot.png",
        )


def test_read_audit_tail_from_state_store(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b'partial\n{"event":"one"}\ninvalid\n{"event":"three"}\n'

    class Store:
        def read_bytes(self, key: str) -> bytes:
            assert key == "audit.jsonl"
            return payload

    settings = SimpleNamespace(state_backend="redis", max_audit_tail_bytes=38)
    monkeypatch.setattr(mcp_tools, "get_settings", lambda: settings)
    monkeypatch.setattr(mcp_tools, "get_state_store", lambda: Store())
    result = mcp_tools._read_audit_tail_entries(10)
    assert result["bytes_read"] == 38
    assert result["truncated_bytes"] == len(payload) - 38
    assert result["entries"][-2:] == [{"raw": "invalid"}, {"event": "three"}]


@pytest.mark.asyncio
async def test_remote_call_disabled_and_failure_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    disabled = SimpleNamespace(remote_enabled=False)
    result = await mcp_tools._remote_call(disabled, "node", "file_read", {})
    assert result.isError is True

    class Manager:
        def __init__(self, result):
            self.result = result
            self.calls = []

        async def call(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self.result

    settings = SimpleNamespace(
        remote_enabled=True,
        remote_peer_transfer_timeout_s=77,
        remote_job_timeout_s=222,
    )
    manager = Manager({"ok": False, "message": "bad", "data": "oops"})
    monkeypatch.setattr(mcp_tools, "remote_manager", lambda: manager)
    failure = await mcp_tools._remote_call(settings, "node", "transfer_stat", {})
    assert failure.isError is True
    assert manager.calls[-1][1]["rpc_timeout_s"] == 77.0

    manager.result = {"ok": True, "data": {"status": "not_found", "message": "gone"}}
    missing = await mcp_tools._remote_call(settings, "node", "file_read", {})
    assert missing.isError is True

    manager.result = {"ok": True, "data": {"value": 1}}
    ok = await mcp_tools._remote_call(settings, "node", "browser_snapshot", {}, timeout_s=9)
    assert ok["data"] == {"value": 1}
    assert manager.calls[-1][1]["rpc_timeout_s"] == 9.0


def test_current_session_subject_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: None)
    assert mcp_tools._current_session_subject() == "local-mcp-client"

    oauth = Principal("mail@example.com", "", {"auth": "oauth"})
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: oauth)
    assert mcp_tools._current_session_subject() == "mail@example.com"

    trusted = Principal(None, "local", {"auth": "local-cli"})
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: trusted)
    assert mcp_tools._current_session_subject() is None

    monkeypatch.setattr(mcp_tools, "get_settings", lambda: SimpleNamespace(auth_mode="none"))
    assert mcp_tools._current_session_subject(create=True) == "anonymous"
    monkeypatch.setattr(mcp_tools, "get_settings", lambda: SimpleNamespace(auth_mode="oauth"))
    assert mcp_tools._current_session_subject(create=True) == "local-user"
    monkeypatch.setattr(mcp_tools, "get_settings", lambda: SimpleNamespace(auth_mode="other"))
    assert mcp_tools._current_session_subject(create=True) == "local-mcp-client"


def _raw_tool(mcp, name: str):
    wrapped = mcp._tool_manager._tools[name].fn
    return wrapped.__kwdefaults__["__original"]


@pytest.mark.asyncio
async def test_remote_manage_remaining_validation_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    mcp = mcp_tools.build_mcp()
    tool = _raw_tool(mcp, "remote_manage")

    missing_revoke = await tool(action="revoke")
    assert missing_revoke.isError is True
    missing_rename_machine = await tool(action="rename", new_name="new")
    assert missing_rename_machine.isError is True
    invalid = await tool(action="unknown")
    assert invalid.isError is True


class _MemoryStateStore:
    def __init__(self, values: dict[str, bytes | None] | None = None) -> None:
        self.values = dict(values or {})
        self.deleted: list[str] = []

    def read_bytes(self, key: str) -> bytes | None:
        return self.values.get(key)

    def write_bytes(self, key: str, value: bytes) -> None:
        self.values[key] = value

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.values if key.startswith(prefix))

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


def test_jobs_nonfile_store_recovers_and_rejects_invalid_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        jobs_module, "get_settings", lambda: SimpleNamespace(state_backend="memory")
    )
    valid = (
        '{"version":' + str(jobs_module.JOB_STORE_VERSION) + ',"jobs":[{"job_id":"ok"}]}'
    ).encode()

    store = _MemoryStateStore(
        {
            jobs_module.JOB_STORE_FILE_NAME: b"[]",
            jobs_module.JOB_STORE_BACKUP_FILE_NAME: valid,
        }
    )
    monkeypatch.setattr(jobs_module, "get_state_store", lambda: store)
    assert jobs_module._load_store()["jobs"] == [{"job_id": "ok"}]

    store.values = {
        jobs_module.JOB_STORE_FILE_NAME: b'{"version":999,"jobs":[]}',
        jobs_module.JOB_STORE_BACKUP_FILE_NAME: (
            '{"version":' + str(jobs_module.JOB_STORE_VERSION) + ',"jobs":"bad"}'
        ).encode(),
    }
    with pytest.raises(RuntimeError, match="unreadable"):
        jobs_module._load_store()

    store.values = {
        jobs_module.JOB_STORE_FILE_NAME: None,
        jobs_module.JOB_STORE_BACKUP_FILE_NAME: valid,
    }
    assert jobs_module._load_store()["jobs"] == [{"job_id": "ok"}]


def test_jobs_remove_attempt_files_stateless_keeps_requested_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemoryStateStore(
        {
            "job-logs/job_x/1.log": b"1",
            "job-logs/job_x/2.log": b"2",
            "job-logs/job_x/3.log": b"3",
        }
    )
    monkeypatch.setattr(
        jobs_module, "get_settings", lambda: SimpleNamespace(stateless_controller=True)
    )
    monkeypatch.setattr(jobs_module, "get_state_store", lambda: store)
    jobs_module._remove_attempt_files("job_x", keep_attempt=2)
    assert store.deleted == ["job-logs/job_x/1.log", "job-logs/job_x/3.log"]


def test_jobs_windows_lock_helpers_and_contention(monkeypatch: pytest.MonkeyPatch) -> None:
    modes: list[int] = []

    class FakeMsvcrt:
        LK_NBLCK = 3
        LK_UNLCK = 4

        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            assert (fd, count) == (7, 1)
            modes.append(mode)

    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt)
    monkeypatch.setattr(jobs_module.os, "name", "nt")
    handle = _FakeHandle()
    assert jobs_module._try_lock_store_file(handle) is True
    jobs_module._unlock_store_file(handle)
    assert modes == [3, 4]

    class ContendedMsvcrt(FakeMsvcrt):
        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            raise OSError(11, "busy")

    monkeypatch.setitem(sys.modules, "msvcrt", ContendedMsvcrt)
    assert jobs_module._try_lock_store_file(handle) is False

    class BrokenMsvcrt(FakeMsvcrt):
        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            raise OSError(5, "broken")

    monkeypatch.setitem(sys.modules, "msvcrt", BrokenMsvcrt)
    with pytest.raises(OSError):
        jobs_module._try_lock_store_file(handle)


def test_jobs_idempotency_scans_malformed_and_conflicting_records() -> None:
    fingerprint = "fp"
    key_hash = jobs_module._idempotency_key_hash("key")
    job = {
        "job_id": "j",
        "idempotency_requests": [
            "bad",
            {"action": "other", "key_hash": key_hash, "fingerprint": fingerprint},
            {"action": "retry", "key_hash": key_hash, "fingerprint": fingerprint},
        ],
    }
    store = {"jobs": [{"job_id": "skip", "idempotency_requests": "bad"}, job]}
    assert (
        jobs_module._find_idempotent_job(store, action="retry", key="key", fingerprint=fingerprint)
        is job
    )
    with pytest.raises(ValueError, match="different request"):
        jobs_module._find_idempotent_job(
            {
                "jobs": [
                    {
                        "idempotency_requests": [
                            {
                                "action": "retry",
                                "key_hash": key_hash,
                                "fingerprint": "different",
                            }
                        ]
                    }
                ]
            },
            action="retry",
            key="key",
            fingerprint=fingerprint,
        )


def test_jobs_read_log_tail_state_and_file_edges(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _MemoryStateStore({"job-logs/j/1.log": b"one\ntwo\nthree\n"})
    monkeypatch.setattr(jobs_module, "get_state_store", lambda: store)
    monkeypatch.setattr(
        jobs_module,
        "get_settings",
        lambda: SimpleNamespace(max_job_log_bytes=1024),
    )
    assert jobs_module._read_log_tail("state://job-logs/j/1.log", 2) == "two\nthree\n"
    assert jobs_module._read_log_tail(str(tmp_path / "missing.log"), 3) == ""
    log = tmp_path / "job.log"
    log.write_bytes(b"a\nb\nc\n")
    assert jobs_module._read_log_tail(str(log), 2) == "b\nc\n"


def test_jobs_managed_store_update_timeout_nonfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextlib.contextmanager
    def busy_store():
        raise TimeoutError("busy")
        yield {}

    monkeypatch.setattr(jobs_module, "_store_transaction", busy_store)
    monkeypatch.setattr(jobs_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(jobs_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        jobs_module, "get_settings", lambda: SimpleNamespace(state_backend="memory")
    )
    with pytest.raises(TimeoutError, match="unable to update"):
        jobs_module._managed_store_update("update_progress", "job_x", {})


def test_remote_handled_exception_shapes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        remote_module,
        "missing_path_context",
        lambda path: {"path": str(path), "cwd": str(tmp_path)},
    )
    missing = remote_module._handled_remote_exception(PathNotFoundError("missing.txt"))
    assert missing["data"]["status"] == "not_found"
    generic = remote_module._handled_remote_exception(ValueError())
    assert generic["message"] == "ValueError"


def test_remote_worker_gui_temp_path_and_stat_edges(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    root = remote_module.temp_dir()
    valid = root / ("gui-" + "a" * 32 + ".png")
    valid.write_bytes(b"payload")
    stat = remote_module._worker_gui_temp_stat(str(valid), sha256=True)
    assert stat["size"] == 7
    assert len(stat["sha256"]) == 64

    invalid = root / "bad.png"
    with pytest.raises(ValueError, match="invalid filename"):
        remote_module._worker_gui_temp_path(str(invalid), must_exist=False)

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    escaped = root / ("gui-" + "b" * 32 + ".png")
    escaped.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        remote_module._worker_gui_temp_path(str(escaped), must_exist=True)


def test_remote_gui_relay_optimizer_invalid_large_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    root = remote_module.temp_dir()
    path = root / ("gui-" + "c" * 32 + ".png")
    path.write_bytes(b"x" * (128 * 1024))
    assert remote_module._optimize_gui_temp_for_relay(str(path)) == {
        "optimized": False,
        "bytes": 128 * 1024,
        "format": "original",
    }
    assert remote_module._optimize_gui_temp_for_relay(str(root / "missing.png")) == {
        "optimized": False,
        "bytes": 0,
        "format": "original",
    }


@pytest.mark.asyncio
async def test_remote_transfer_dispatch_remaining_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        remote_module,
        "transfer_refresh_stream_write",
        lambda path, transfer_id: calls.append(("refresh", (path, transfer_id))),
    )
    monkeypatch.setattr(
        remote_module,
        "open_peer_receiver",
        lambda **kwargs: {"receiver": kwargs},
    )
    monkeypatch.setattr(
        remote_module, "close_peer_receiver", lambda receiver_id: {"closed": receiver_id}
    )

    async def put(*args, **kwargs):
        calls.append(("put", args))
        return {"put": True}

    async def get(*args, **kwargs):
        calls.append(("get", args))
        return {"get": True}

    monkeypatch.setattr(remote_module, "_worker_put_url_cancellable", put)
    monkeypatch.setattr(remote_module, "_worker_download_url_cancellable", get)

    assert await remote_module._execute_transfer_worker_tool(
        "transfer_refresh_stream_write", {"path": "p", "transfer_id": "t"}
    ) == {"refreshed": True}
    opened = await remote_module._execute_transfer_worker_tool(
        "transfer_open_receiver",
        {"path": "p", "expected_bytes": 1, "expected_sha256": "x"},
    )
    assert opened["receiver"]["bind_host"] == "0.0.0.0"
    assert await remote_module._execute_transfer_worker_tool(
        "transfer_close_receiver", {"receiver_id": "r"}
    ) == {"closed": "r"}
    assert (
        await remote_module._execute_transfer_worker_tool(
            "transfer_put_url",
            {"path": "p", "url": "https://x", "expected_bytes": 1},
        )
    ) == {"put": True}
    assert (
        await remote_module._execute_transfer_worker_tool(
            "transfer_get_url",
            {
                "path": "p",
                "url": "https://x",
                "expected_bytes": 1,
                "expected_sha256": "x",
            },
        )
    ) == {"get": True}
    with pytest.raises(ValueError, match="unsupported"):
        await remote_module._execute_transfer_worker_tool("unknown", {})


def test_remote_registry_load_recovers_backup_and_sanitizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = b"good-generation"
    backup = {
        "version": 1,
        "generation": generation.decode(),
        "workers": [
            {
                "name": "node",
                "access": "token",
                "last_seen": "bad",
                "created_at": 1,
                "reset_generation": "bad",
            },
            {"name": "", "access": "ignored"},
        ],
        "invites": [
            {"code": "", "expires_at": 99999999999},
            {"code": "invite", "expires_at": 99999999999, "used": False},
        ],
    }
    store = _MemoryStateStore(
        {
            remote_module.REMOTE_WORKER_REGISTRY_FILE_NAME: b"not-json",
            remote_module.REMOTE_WORKER_REGISTRY_BACKUP_FILE_NAME: __import__("json")
            .dumps(backup)
            .encode(),
            remote_module.REMOTE_WORKER_REGISTRY_GENERATION_FILE_NAME: generation,
        }
    )
    monkeypatch.setattr(remote_module, "get_state_store", lambda: store)
    monkeypatch.setattr(remote_module, "audit", lambda *args, **kwargs: None)
    manager = remote_module.RemoteManager()
    manager._load_registry_unlocked()
    assert set(manager.workers) == {"node"}
    assert manager.workers["node"].last_seen == 0.0
    assert manager.workers["node"].reset_generation == 0
    assert set(manager.invites) == {"invite"}
    assert manager._registry_loaded is True


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
    monkeypatch.setattr(human_ui.os, "getloadavg", lambda: (0.5, 0.0, 0.0))
    monkeypatch.setattr(human_ui.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(human_ui, "_read_linux_cpu_times", lambda: (200, 60))
    monkeypatch.setattr(human_ui, "_read_linux_network", lambda: (1600, 2600))
    monkeypatch.setattr(human_ui, "_read_linux_memory", lambda: (1000, 250))
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


def test_cli_dotenv_value_edge_cases() -> None:
    assert cli_call._parse_dotenv_value("") == ""
    assert cli_call._parse_dotenv_value("'unterminated") == "unterminated"
    assert cli_call._parse_dotenv_value("'quoted' ignored") == "quoted"
    assert (
        cli_call._parse_dotenv_value('"hello\\n${NAME}\\q"', variables={"NAME": "world"})
        == "hello\nworld\\q"
    )
    assert cli_call._parse_dotenv_value('"trailing\\', variables={}) == "trailing\\"
    assert cli_call._parse_dotenv_value("value # comment") == "value"


def test_cli_dotenv_interpolation_edge_paths() -> None:
    variables = {"NAME": "world", "EMPTY": ""}
    assert cli_call._interpolate_dotenv("x$$y$", variables) == "x$y$"
    assert cli_call._interpolate_dotenv("$NAME-$MISSING-$9", variables) == "world--$9"
    assert (
        cli_call._interpolate_dotenv(r"\n\r\t\"\\\$\q", variables, decode_escapes=True)
        == '\n\r\t"\\$\\q'
    )
    assert cli_call._interpolate_dotenv("${MISSING:-${NAME}}", variables) == "world"
    with pytest.raises(ValueError, match="missing"):
        cli_call._interpolate_dotenv("${NAME", variables)
    with pytest.raises(ValueError, match="nested too deeply"):
        cli_call._interpolate_dotenv("x", variables, depth=21)


@pytest.mark.parametrize(
    ("value", "start", "decode", "expected"),
    [
        ("a}", 0, False, 1),
        ("${A}}", 0, False, 4),
        (r"\${A}}", 0, True, 5),
        (r"\q}", 0, True, 2),
        (r"\n}", 0, True, 2),
        ("unterminated", 0, False, None),
    ],
)
def test_cli_dotenv_interpolation_end_paths(
    value: str, start: int, decode: bool, expected: int | None
) -> None:
    assert cli_call._dotenv_interpolation_end(value, start, decode_escapes=decode) == expected


def test_fs_file_actions_cover_existing_and_copy_variants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    fs_ops.perform_file_action("mkdir", "dir")
    assert fs_ops.perform_file_action("mkdir", "dir", exist_ok=True)["action"] == "mkdir"
    with pytest.raises(FileExistsError):
        fs_ops.perform_file_action("touch", "dir", exist_ok=True)

    fs_ops.perform_file_action("touch", "file.txt")
    assert fs_ops.perform_file_action("touch", "file.txt", exist_ok=True)["action"] == "touch"
    with pytest.raises(ValueError, match="destination is required"):
        fs_ops.perform_file_action("copy", "file.txt")

    (tmp_path / "target-parent").mkdir()
    fs_ops.perform_file_action("copy", "file.txt", "target-parent/copied.txt")
    assert (tmp_path / "target-parent" / "copied.txt").is_file()

    (tmp_path / "link").symlink_to("file.txt")
    fs_ops.perform_file_action("copy", "link", "target-parent/link-copy")
    assert (tmp_path / "target-parent" / "link-copy").is_symlink()

    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "x").write_text("x")
    with pytest.raises(ValueError, match="inside"):
        fs_ops.perform_file_action("move", "tree", "tree/nested")


def test_fs_edit_text_error_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    target = tmp_path / "edit.txt"
    target.write_text("same same")
    with pytest.raises(ValueError, match="occurs 2 times"):
        fs_ops.edit_text("edit.txt", [{"old": "same", "new": "x"}])
    with pytest.raises(ValueError, match="not found"):
        fs_ops.edit_text("edit.txt", [{"old": "missing", "new": "x"}])
    result = fs_ops.edit_text("edit.txt", [{"old": "same", "new": "x", "replace_all": True}])
    assert result["replacements"] == 2


def test_oauth_client_store_loader_handles_bad_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = SimpleNamespace(
        state_backend="memory",
        state_backend_url=None,
        state_backend_prefix="test",
        state_dir=tmp_path,
    )
    monkeypatch.setattr(oauth_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oauth_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(oauth_module, "_CLIENTS", {})
    monkeypatch.setattr(oauth_module, "_LOADED_CLIENT_STORE_SIGNATURE", None)
    payload = {
        "version": oauth_module.OAUTH_CLIENT_STORE_VERSION,
        "clients": {
            "good": {
                "redirect_uris": ["https://example/callback"],
                "client_name": 123,
                "created_at": "bad",
            },
            "bad-redirect": {"redirect_uris": "nope"},
            3: {"redirect_uris": []},
        },
    }
    store = _MemoryStateStore(
        {oauth_module.OAUTH_CLIENT_STORE_FILE_NAME: __import__("json").dumps(payload).encode()}
    )
    monkeypatch.setattr(oauth_module, "get_state_store", lambda: store)
    oauth_module._load_clients_locked()
    assert set(oauth_module._CLIENTS) == {"good", "3"}
    assert oauth_module._CLIENTS["good"].client_name is None
    assert oauth_module._CLIENTS["good"].created_at > 0

    store.values[oauth_module.OAUTH_CLIENT_STORE_FILE_NAME] = b'{"version":999}'
    oauth_module._load_clients_locked()
    assert oauth_module._CLIENTS == {}


def test_oauth_code_store_loader_handles_rows_and_invalid_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(state_backend="memory")
    monkeypatch.setattr(oauth_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oauth_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(oauth_module, "_CODES", {})
    payload = {
        "version": oauth_module.OAUTH_CODE_STORE_VERSION,
        "codes": [
            "bad",
            {"code": ""},
            {
                "code": "code",
                "client_id": "client",
                "redirect_uri": "https://example/callback",
                "scope": "shell:read",
                "resource": "resource",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
                "created_at": 1,
                "used": True,
            },
        ],
    }
    store = _MemoryStateStore(
        {oauth_module.OAUTH_CODE_STORE_FILE_NAME: __import__("json").dumps(payload).encode()}
    )
    monkeypatch.setattr(oauth_module, "get_state_store", lambda: store)
    oauth_module._load_codes_locked()
    assert set(oauth_module._CODES) == {"code"}
    assert oauth_module._CODES["code"].used is True

    store.values[oauth_module.OAUTH_CODE_STORE_FILE_NAME] = b'{"version":1,"codes":"bad"}'
    oauth_module._load_codes_locked()
    assert oauth_module._CODES == {}


def test_dynamic_mcp_memory_load_save_and_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = SimpleNamespace(state_backend="memory", disable_local=False)
    monkeypatch.setattr(dynamic_mcp, "get_settings", lambda: settings)
    store = _MemoryStateStore()
    monkeypatch.setattr(dynamic_mcp, "get_state_store", lambda: store)
    monkeypatch.setattr(dynamic_mcp, "resolve_path", lambda path: tmp_path)
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)

    assert manager._load() == {}
    payload = {
        "version": dynamic_mcp._REGISTRY_VERSION,
        "servers": [
            "bad",
            {
                "name": "stdio",
                "transport": "stdio",
                "command": "tool",
                "cwd": None,
            },
        ],
    }
    store.values["dynamic-mcp.json"] = __import__("json").dumps(payload).encode()
    loaded = manager._load()
    assert loaded["stdio"].cwd == str(tmp_path)
    manager._save(loaded)
    assert store.values["dynamic-mcp.json"].endswith(b"\n")

    with pytest.raises(ValueError, match="url is only valid"):
        manager._validate_config(
            dynamic_mcp.DynamicMCPServer(
                name="bad", transport="stdio", command="tool", url="https://example"
            )
        )


@pytest.mark.asyncio
async def test_dynamic_mcp_search_scoring_and_disabled_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)
    enabled = dynamic_mcp.DynamicMCPServer(
        name="alpha",
        transport="streamable_http",
        url="https://example",
        tools=[
            {"name": "find", "title": "Search Docs", "description": "lookup"},
            {"name": "other", "title": "Misc", "description": "search docs"},
        ],
    )
    empty = dynamic_mcp.DynamicMCPServer(
        name="empty", transport="streamable_http", url="https://empty", tools=[]
    )
    disabled = dynamic_mcp.DynamicMCPServer(
        name="off",
        transport="streamable_http",
        url="https://off",
        enabled=False,
        tools=[{"name": "hidden"}],
    )
    monkeypatch.setattr(
        manager, "_load", lambda: {"alpha": enabled, "empty": empty, "off": disabled}
    )
    result = await manager.search("search docs")
    assert [item["name"] for item in result["tools"]] == ["alpha:find", "alpha:other"]
    assert result["unrefreshed_servers"] == ["empty"]
    assert (await manager.search("", server="off"))["count"] == 0
    with pytest.raises(ValueError, match="unknown"):
        await manager.search("", server="missing")


@pytest.mark.asyncio
async def test_dynamic_mcp_local_disable_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)
    server = dynamic_mcp.DynamicMCPServer(
        name="stdio",
        transport="stdio",
        command="tool",
        tools=[{"name": "run"}],
    )
    monkeypatch.setattr(manager, "_load", lambda: {"stdio": server})
    monkeypatch.setattr(
        dynamic_mcp,
        "get_settings",
        lambda: SimpleNamespace(disable_local=True),
    )
    with pytest.raises(ValueError, match="local access is disabled"):
        await manager.refresh("stdio")
    with pytest.raises(ValueError, match="local access is disabled"):
        await manager.call("stdio:run")


def test_tools_transport_security_ipv6_and_invalid_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_tools,
        "get_settings",
        lambda: SimpleNamespace(host="::1", public_base_url=None, port=8000),
    )
    security = mcp_tools._transport_security_settings()
    assert "[::1]" in security.allowed_hosts
    monkeypatch.setattr(
        mcp_tools,
        "get_settings",
        lambda: SimpleNamespace(host="not-an-ip", public_base_url="relative/path", port=8000),
    )
    security = mcp_tools._transport_security_settings()
    assert "not-an-ip" not in security.allowed_hosts


def test_tools_live_workspace_html_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePath:
        def __init__(self, *args):
            pass

        def resolve(self):
            return self

        @property
        def parent(self):
            return self

        def __truediv__(self, other):
            return self

        def read_text(self, **kwargs):
            raise OSError("missing")

    monkeypatch.setattr(mcp_tools, "Path", FakePath)
    assert "assets are not built" in mcp_tools._live_workspace_html()


@pytest.mark.asyncio
async def test_tools_session_cleanup_retry_failure_then_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        def __init__(self):
            self.calls = 0

        def retry_tool_call_cleanup(self, lease):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("backend unavailable")
            return True

    manager = Manager()
    key = (id(manager), "session")
    monkeypatch.setattr(mcp_tools, "audit", lambda *args, **kwargs: None)
    original_sleep = mcp_tools.asyncio.sleep

    async def no_delay(delay):
        await original_sleep(0)

    monkeypatch.setattr(mcp_tools.asyncio, "sleep", no_delay)
    mcp_tools._SESSION_LEASE_CLEANUP_QUEUES[key] = {
        "call": ({"session_id": "session"}, "run_shell", float("inf"))
    }
    await mcp_tools._retry_session_tool_cleanups(manager, queue_key=key)
    assert manager.calls == 2
    assert key not in mcp_tools._SESSION_LEASE_CLEANUP_QUEUES


@pytest.mark.asyncio
async def test_tools_finish_session_activity_exception_schedules_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        def finish_tool_call(self, *args, **kwargs):
            raise RuntimeError("store down")

    scheduled = []
    monkeypatch.setattr(mcp_tools, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mcp_tools,
        "_schedule_session_tool_cleanup_retry",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    await mcp_tools._finish_session_tool_activity(
        Manager(),
        {"session_id": "s"},
        "tool_finished",
        {},
        tool_name="run_shell",
        call_id="c",
        stage="finish",
    )
    assert scheduled
    mcp_tools._schedule_session_tool_cleanup_retry(
        Manager(), {}, tool_name="run_shell", call_id="missing-session"
    )


def test_tools_staging_parent_symlink_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / ".local-shell-mcp").symlink_to(outside, target_is_directory=True)
    settings = SimpleNamespace(workspace_root=root, remote_job_timeout_s=60)
    monkeypatch.setattr(mcp_tools, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="relay staging parent escapes"):
        mcp_tools._controller_relay_staging_path()
    with pytest.raises(ValueError, match="GUI staging parent escapes"):
        mcp_tools._controller_gui_staging_path()


def test_final_margin_simple_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Dotenv escaped backslash and escaped dollar-without-brace paths.
    assert cli_call._dotenv_interpolation_end(r"\\}", 0, decode_escapes=True) == 2
    assert cli_call._dotenv_interpolation_end(r"\$}", 0, decode_escapes=True) == 2
    assert cli_call._interpolate_dotenv("${NAME:+yes}", {"NAME": "x"}) == "yes"
    assert cli_call._interpolate_dotenv("${MISSING:+yes}", {}) == ""

    # File-action and edit validation branches that protect destructive operations.
    _transfer_workspace(tmp_path, monkeypatch)
    fs_ops.perform_file_action("touch", "exists.txt")
    with pytest.raises(FileExistsError):
        fs_ops.perform_file_action("touch", "exists.txt")
    (tmp_path / "srcdir").mkdir()
    (tmp_path / "srcdir" / "x").write_text("x")
    (tmp_path / "dst").mkdir()
    fs_ops.perform_file_action("copy", "srcdir", "dst/copied")
    assert (tmp_path / "dst" / "copied" / "x").read_text() == "x"
    with pytest.raises(ValueError, match="must not be empty"):
        fs_ops._validated_text_edits([])
    with pytest.raises(ValueError, match="must be an object"):
        fs_ops._validated_text_edits(["bad"])  # type: ignore[list-item]


def test_oauth_invalid_top_level_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        state_backend="memory",
        state_backend_url=None,
        state_backend_prefix="test",
        state_dir=tmp_path,
    )
    monkeypatch.setattr(oauth_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oauth_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(oauth_module, "_CLIENTS", {})
    monkeypatch.setattr(oauth_module, "_CODES", {})
    monkeypatch.setattr(oauth_module, "_LOADED_CLIENT_STORE_SIGNATURE", None)
    store = _MemoryStateStore(
        {
            oauth_module.OAUTH_CLIENT_STORE_FILE_NAME: (
                '{"version":' + str(oauth_module.OAUTH_CLIENT_STORE_VERSION) + ',"clients":[]}'
            ).encode(),
            oauth_module.OAUTH_CODE_STORE_FILE_NAME: b'{"version":999,"codes":[]}',
        }
    )
    monkeypatch.setattr(oauth_module, "get_state_store", lambda: store)
    oauth_module._load_clients_locked()
    oauth_module._load_codes_locked()
    assert oauth_module._CLIENTS == {}
    assert oauth_module._CODES == {}


@pytest.mark.asyncio
async def test_dynamic_mcp_search_filter_and_inspect_continuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = dynamic_mcp.DynamicMCPManager(tmp_path)
    server = dynamic_mcp.DynamicMCPServer(
        name="alpha",
        transport="streamable_http",
        url="https://example",
        tools=[{"name": "first"}, {"name": "second", "description": "target"}],
    )
    monkeypatch.setattr(manager, "_load", lambda: {"alpha": server})
    assert (await manager.search("not-present"))["count"] == 0
    inspected = await manager.inspect("alpha:second")
    assert inspected["tool"]["name"] == "second"


def test_remote_small_validation_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported remote worker lane"):
        remote_module._worker_job_lane("tool", "bad")
    assert (
        remote_module._worker_job_lane("transfer_stat") == remote_module.REMOTE_WORKER_TRANSFER_LANE
    )
    assert (
        remote_module._worker_job_lane("file_read") == remote_module.REMOTE_WORKER_INTERACTIVE_LANE
    )

    invalid_registry = {
        "version": 1,
        "generation": "",
        "workers": [],
        "invites": [],
    }
    with pytest.raises(ValueError, match="generation is invalid"):
        remote_module.RemoteManager._read_registry(
            __import__("json").dumps(invalid_registry).encode()
        )

    assert remote_module._worker_reset_generation({"reset_generation": "bad"}) is None

    _transfer_workspace(tmp_path, monkeypatch)
    root = remote_module.temp_dir()
    directory = root / ("gui-" + "d" * 32 + ".png")
    directory.mkdir()
    with pytest.raises(IsADirectoryError):
        remote_module._worker_gui_temp_stat(str(directory))


@pytest.mark.asyncio
async def test_tools_empty_cleanup_queue_and_missing_session_schedule() -> None:
    key = (123456789, "missing")
    await mcp_tools._retry_session_tool_cleanups(object(), queue_key=key)
    mcp_tools._schedule_session_tool_cleanup_retry(
        object(), {}, tool_name="run_shell", call_id="call"
    )
