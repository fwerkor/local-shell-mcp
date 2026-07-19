from __future__ import annotations

import gzip
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from local_shell_mcp import tui_runtime

PAYLOAD_NAME = "local-shell-mcp-tui.exe.gz" if os.name == "nt" else "local-shell-mcp-tui.gz"


def test_materialize_embedded_tui(tmp_path: Path) -> None:
    payload = tmp_path / PAYLOAD_NAME
    with gzip.open(payload, "wb") as archive:
        archive.write(b"runtime")

    state_dir = tmp_path / "state"
    target = tui_runtime.materialize_embedded_tui(state_dir, payload=payload)

    assert target is not None
    assert target.read_bytes() == b"runtime"
    if os.name != "nt":
        assert os.access(target, os.X_OK)
        assert target.stat().st_mode & (stat.S_IXGRP | stat.S_IXOTH) == 0
    assert tui_runtime.materialize_embedded_tui(state_dir, payload=payload) == target


def test_materialize_embedded_tui_returns_none_without_payload(tmp_path: Path) -> None:
    assert tui_runtime.materialize_embedded_tui(
        tmp_path / "state", payload=tmp_path / "missing.gz"
    ) is None


def test_materialize_embedded_tui_is_concurrency_safe(tmp_path: Path) -> None:
    payload = tmp_path / PAYLOAD_NAME
    with gzip.open(payload, "wb") as archive:
        archive.write(b"runtime" * 1024)

    state_dir = tmp_path / "state"
    with ThreadPoolExecutor(max_workers=8) as executor:
        targets = list(
            executor.map(
                lambda _: tui_runtime.materialize_embedded_tui(state_dir, payload=payload),
                range(16),
            )
        )

    assert targets[0] is not None
    assert all(target == targets[0] for target in targets)
    assert targets[0].read_bytes() == b"runtime" * 1024
    assert not list(targets[0].parent.glob("*.tmp"))


def test_materialize_embedded_tui_accepts_completed_windows_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / PAYLOAD_NAME
    with gzip.open(payload, "wb") as archive:
        archive.write(b"runtime")

    real_replace = tui_runtime.os.replace

    def replace_then_report_windows_race(source: Path, target: Path) -> None:
        real_replace(source, target)
        raise PermissionError("simulated Windows replace race")

    monkeypatch.setattr(tui_runtime.os, "replace", replace_then_report_windows_race)
    target = tui_runtime.materialize_embedded_tui(tmp_path / "state", payload=payload)

    assert target is not None
    assert target.read_bytes() == b"runtime"
    assert not list(target.parent.glob("*.tmp"))


def test_materialize_embedded_tui_propagates_replace_failure_without_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / PAYLOAD_NAME
    with gzip.open(payload, "wb") as archive:
        archive.write(b"runtime")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise PermissionError("simulated access failure")

    monkeypatch.setattr(tui_runtime.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="simulated access failure"):
        tui_runtime.materialize_embedded_tui(tmp_path / "state", payload=payload)

    target_dir = tmp_path / "state" / "ui-runtime" / tui_runtime.__version__
    assert not list(target_dir.glob("*.tmp"))
