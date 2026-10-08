from __future__ import annotations

from pathlib import Path

import pytest

import local_shell_mcp.gui.base as gui_base


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
