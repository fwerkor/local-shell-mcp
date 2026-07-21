from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.patch_ops import normalize_patch_text


def _git_apply(root: Path, patch: str) -> None:
    patch_path = root / "change.diff"
    patch_path.write_bytes(patch.encode("utf-8"))
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
    expected_mode = "100755" if target.stat().st_mode & 0o111 else "100644"
    assert f"deleted file mode {expected_mode}" in normalized
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


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ("*** Begin Patch\n*** End Patch\n", "no file actions"),
        ("*** Begin Patch\n*** End Patch\nextra\n", "unexpected content"),
        ("*** Begin Patch\n*** Rename File: x.txt\n*** End Patch\n", "expected file action"),
        ("*** Begin Patch\n*** Add File: x.txt\n+x\n", "missing"),
        (
            "*** Begin Patch\n*** Update File: x.txt\n*** Move to: y.txt\n*** End Patch\n",
            "not supported",
        ),
        ("*** Begin Patch\n*** Add File:   \n+x\n*** End Patch\n", "invalid patch path"),
        ("*** Begin Patch\n*** Add File: sub\\x.txt\n+x\n*** End Patch\n", "invalid patch path"),
        ("*** Begin Patch\n*** Add File: .\n+x\n*** End Patch\n", "invalid patch path"),
        ("*** Begin Patch\n*** Add File: ../x.txt\n+x\n*** End Patch\n", "stay within cwd"),
    ],
)
def test_envelope_rejects_malformed_input(tmp_path: Path, patch: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_patch_text(patch, str(tmp_path))


def test_envelope_rejects_invalid_file_actions(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("old\n", encoding="utf-8")

    cases = [
        (
            "*** Begin Patch\n*** Add File: existing.txt\n+new\n*** End Patch\n",
            "cannot add existing",
        ),
        ("*** Begin Patch\n*** Delete File: missing.txt\n*** End Patch\n", "cannot delete missing"),
        (
            "*** Begin Patch\n*** Delete File: existing.txt\n-extra\n*** End Patch\n",
            "must not contain patch lines",
        ),
        (
            "*** Begin Patch\n*** Update File: missing.txt\n@@\n-old\n+new\n*** End Patch\n",
            "cannot update missing",
        ),
        (
            "*** Begin Patch\n*** Add File: bad.txt\nnot-added\n*** End Patch\n",
            "must start with",
        ),
    ]
    for patch, message in cases:
        with pytest.raises(ValueError, match=message):
            normalize_patch_text(patch, str(tmp_path))


def test_envelope_rejects_invalid_hunks(tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("one\ntwo\n", encoding="utf-8")
    cases = [
        (
            "*** Begin Patch\n*** Update File: sample.txt\n*** End of File\n*** End Patch\n",
            "unexpected end-of-file",
        ),
        (
            "*** Begin Patch\n*** Update File: sample.txt\n-one\n+ONE\n*** End Patch\n",
            "must follow an '@@' hunk",
        ),
        (
            "*** Begin Patch\n*** Update File: sample.txt\n@@\n?one\n*** End Patch\n",
            "invalid hunk line",
        ),
        (
            "*** Begin Patch\n*** Update File: sample.txt\n*** End Patch\n",
            "contains no hunks",
        ),
        (
            "*** Begin Patch\n*** Update File: sample.txt\n@@\n one\n*** End Patch\n",
            "contains no changes",
        ),
        (
            "*** Begin Patch\n*** Update File: sample.txt\n@@\n+zero\n*** End Patch\n",
            "has no context",
        ),
        (
            "*** Begin Patch\n*** Update File: sample.txt\n@@\n one\n+extra\n*** End of File\n*** End Patch\n",
            "does not match the end",
        ),
    ]
    for patch, message in cases:
        with pytest.raises(ValueError, match=message):
            normalize_patch_text(patch, str(tmp_path))


def test_envelope_rejects_invalid_targets(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    patch = "*** Begin Patch\n*** Update File: directory\n@@\n-old\n+new\n*** End Patch\n"
    with pytest.raises(ValueError, match="not a regular file"):
        normalize_patch_text(patch, str(tmp_path))

    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"\xff")
    patch = "*** Begin Patch\n*** Update File: binary.bin\n@@\n-old\n+new\n*** End Patch\n"
    with pytest.raises(ValueError, match="not UTF-8 text"):
        normalize_patch_text(patch, str(tmp_path))

    outside = tmp_path.parent / "outside.txt"
    patch = f"*** Begin Patch\n*** Add File: {outside}\n+x\n*** End Patch\n"
    with pytest.raises(ValueError, match="stay within cwd"):
        normalize_patch_text(patch, str(tmp_path))

    patch = f"*** Begin Patch\n*** Add File: {tmp_path}\n+x\n*** End Patch\n"
    with pytest.raises(ValueError, match="invalid patch path"):
        normalize_patch_text(patch, str(tmp_path))


def test_envelope_supports_empty_files_and_detects_net_noop(tmp_path: Path) -> None:
    add_empty = "*** Begin Patch\n*** Add File: empty.txt\n*** End Patch\n"
    _git_apply(tmp_path, normalize_patch_text(add_empty, str(tmp_path)))
    assert (tmp_path / "empty.txt").read_bytes() == b""

    delete_empty = "*** Begin Patch\n*** Delete File: empty.txt\n*** End Patch\n"
    _git_apply(tmp_path, normalize_patch_text(delete_empty, str(tmp_path)))
    assert not (tmp_path / "empty.txt").exists()

    noop = """*** Begin Patch
*** Add File: transient.txt
+x
*** Delete File: transient.txt
*** End Patch
"""
    with pytest.raises(ValueError, match="does not contain any file changes"):
        normalize_patch_text(noop, str(tmp_path))


def test_envelope_preserves_crlf_and_cr_line_endings(tmp_path: Path) -> None:
    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes(b"one\r\ntwo\r\n")
    patch = "*** Begin Patch\n*** Update File: crlf.txt\n@@\n one\n-two\n+TWO\n*** End Patch\n"
    _git_apply(tmp_path, normalize_patch_text(patch, str(tmp_path)))
    assert crlf.read_bytes() == b"one\r\nTWO\r\n"

    cr = tmp_path / "cr.txt"
    cr.write_bytes(b"one\rtwo\r")
    patch = "*** Begin Patch\n*** Update File: cr.txt\n@@\n one\n-two\n+TWO\n*** End Patch\n"
    normalized = normalize_patch_text(patch, str(tmp_path))
    assert " one\r" in normalized
