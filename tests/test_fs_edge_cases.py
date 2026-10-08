from __future__ import annotations

from pathlib import Path

import pytest
from edge_case_support import symlink_or_skip
from edge_case_support import workspace as _transfer_workspace

import local_shell_mcp.fs_ops as fs_ops


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

    symlink_or_skip(tmp_path / "link", "file.txt")
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

def test_fs_additional_file_action_and_edit_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
