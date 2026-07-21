from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.patch_ops import normalize_patch_text


def _git_apply(root: Path, patch: str) -> None:
    patch_path = root / "change.diff"
    patch_path.write_text(patch, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=root, check=True)
    subprocess.run(["git", "apply", str(patch_path)], cwd=root, check=True)


def test_standard_unified_diff_passes_through() -> None:
    patch = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
    assert normalize_patch_text(patch) == patch


def test_envelope_update_add_and_delete(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (tmp_path / "obsolete.txt").write_text("remove me\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: existing.txt
@@
 one
-two
+TWO
 three
*** Add File: added.txt
+first
+second
*** Delete File: obsolete.txt
*** End Patch
"""

    normalized = normalize_patch_text(patch, str(tmp_path))
    assert normalized.startswith("diff --git a/existing.txt b/existing.txt\n")
    _git_apply(tmp_path, normalized)

    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"
    assert (tmp_path / "added.txt").read_text(encoding="utf-8") == "first\nsecond\n"
    assert not (tmp_path / "obsolete.txt").exists()


def test_envelope_supports_multiple_hunks_and_eof_append(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: sample.txt
@@
-alpha
+ALPHA
 beta
@@
 gamma
+delta
*** End of File
*** End Patch
"""

    _git_apply(tmp_path, normalize_patch_text(patch, str(tmp_path)))

    assert target.read_text(encoding="utf-8") == "ALPHA\nbeta\ngamma\ndelta\n"


def test_envelope_rejects_ambiguous_hunk_without_touching_files(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    original = "same\nvalue\nsame\nvalue\n"
    target.write_text(original, encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: sample.txt
@@
 same
-value
+changed
*** End Patch
"""

    with pytest.raises(ValueError, match="multiple locations"):
        normalize_patch_text(patch, str(tmp_path))

    assert target.read_text(encoding="utf-8") == original


def test_envelope_validates_all_actions_before_application(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old\n", encoding="utf-8")
    second.write_text("actual\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: first.txt
@@
-old
+new
*** Update File: second.txt
@@
-missing
+replacement
*** End Patch
"""

    with pytest.raises(ValueError, match="does not match second.txt"):
        normalize_patch_text(patch, str(tmp_path))

    assert first.read_text(encoding="utf-8") == "old\n"
    assert second.read_text(encoding="utf-8") == "actual\n"


def test_envelope_preserves_executable_mode_on_delete(tmp_path: Path) -> None:
    target = tmp_path / "script.sh"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    target.chmod(0o755)
    patch = """*** Begin Patch
*** Delete File: script.sh
*** End Patch
"""

    normalized = normalize_patch_text(patch, str(tmp_path))
    assert "deleted file mode 100755" in normalized
    _git_apply(tmp_path, normalized)

    assert not target.exists()


def test_envelope_updates_file_without_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_bytes(b"old")
    patch = """*** Begin Patch
*** Update File: sample.txt
@@
-old
+new
*** End Patch
"""

    normalized = normalize_patch_text(patch, str(tmp_path))
    assert "\\ No newline at end of file" in normalized
    _git_apply(tmp_path, normalized)

    assert target.read_bytes() == b"new"


def test_envelope_accepts_absolute_path_inside_cwd(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = f"""*** Begin Patch
*** Update File: {target}
@@
-old
+new
*** End Patch
"""

    _git_apply(tmp_path, normalize_patch_text(patch, str(tmp_path)))

    assert target.read_text(encoding="utf-8") == "new\n"


def test_envelope_rejects_paths_outside_cwd(tmp_path: Path) -> None:
    patch = """*** Begin Patch
*** Add File: ../escape.txt
+bad
*** End Patch
"""

    with pytest.raises(ValueError, match="stay within cwd"):
        normalize_patch_text(patch, str(tmp_path))
