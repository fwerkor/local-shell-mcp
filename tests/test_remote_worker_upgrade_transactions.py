"""Test transactional upgrade edge cases that could strand a remote worker."""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from local_shell_mcp import remote_worker_installer as installer
from local_shell_mcp import remote_worker_state as state


def _setup(tmp_path, monkeypatch, *, previous: bool = True):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    state.write_worker_config(
        server="https://example.test", name="worker", workdir=str(tmp_path),
        runtime_digest="previous-digest", runtime_version="previous-version",
    )
    if previous:
        old = state.worker_runtime_dir() / "local_shell_mcp"
        old.mkdir(parents=True)
        (old / "value.py").write_text('version = "old"\n')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        payloads = {
            "__init__.py": b"",
            "remote_worker.py": b"def main(argv=None): pass\n",
            "remote_worker_cli.py": b"def run_worker_cli(argv=None): pass\n",
            "settings.py": (
                b"from types import SimpleNamespace\n"
                b"def get_settings(): return SimpleNamespace(state_backend='file')\n"
            ),
            "value.py": b'version = "new"\n',
        }
        for name, data in payloads.items():
            member = tarfile.TarInfo("local_shell_mcp/" + name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    payload = archive.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        installer, "fetch_manifest",
        lambda server: {"sha256": digest, "bundle_version": "next-version", "url": "https://example.test/bundle.tgz"},
    )
    monkeypatch.setattr(installer, "_fetch_bytes", lambda url, timeout=60: payload)
    return digest


def test_upgrade_trial_blocks_overlapping_update_even_when_forced(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    installer.install_or_update_runtime("https://example.test")
    assert (state.worker_state_dir() / "runtime.pending.json").exists()
    with pytest.raises(RuntimeError, match="already awaiting"):
        installer.install_or_update_runtime("https://example.test", force=True)
    assert (state.worker_state_dir() / "runtime.previous" / "local_shell_mcp" / "value.py").read_text() == 'version = "old"\n'


def test_confirm_restores_missing_candidate_metadata_after_interruption(tmp_path, monkeypatch):
    expected = _setup(tmp_path, monkeypatch)
    installer.install_or_update_runtime("https://example.test")
    # A prior process stopped after the swap but before writing config.json.
    state.update_runtime_metadata("previous-digest", "previous-version")
    installer.confirm_runtime_healthy()
    assert state.read_worker_config()["runtime_digest"] == expected
    assert state.read_worker_config()["runtime_version"] == "next-version"
    assert not (state.worker_state_dir() / "runtime.previous").exists()
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()
    installer.confirm_runtime_healthy()  # idempotent after success


def test_confirm_accepts_older_journal_without_candidate_digest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (state.worker_state_dir() / "runtime.pending.json").write_text(json.dumps({"previous_digest": "old"}))
    installer.confirm_runtime_healthy()
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()


def test_install_without_config_does_not_require_metadata_update(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, previous=False)
    state.worker_config_path().unlink()
    result = installer.install_or_update_runtime("https://example.test")
    assert result["updated"]
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()
    assert not state.worker_config_path().exists()
    assert (state.worker_runtime_dir() / "local_shell_mcp" / "value.py").exists()


def test_stale_backup_is_replaced_only_when_no_upgrade_is_pending(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    backup = state.worker_state_dir() / "runtime.previous"
    backup.mkdir()
    (backup / "stale.txt").write_text("obsolete")
    installer.install_or_update_runtime("https://example.test")
    assert not (backup / "stale.txt").exists()
    assert (backup / "local_shell_mcp" / "value.py").read_text() == 'version = "old"\n'


def test_install_fails_safe_when_candidate_cannot_be_staged(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.shutil, "copytree", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("staging failed")))
    with pytest.raises(OSError, match="staging failed"):
        installer.install_or_update_runtime("https://example.test")
    assert (state.worker_runtime_dir() / "local_shell_mcp" / "value.py").read_text() == 'version = "old"\n'
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()


def test_swap_failure_restores_previous_runtime(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    real_replace = Path.replace

    def fail_candidate(path, target):
        if path.name.startswith("runtime.next."):
            raise OSError("candidate swap denied")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_candidate)
    with pytest.raises(OSError, match="candidate swap denied"):
        installer.install_or_update_runtime("https://example.test")
    assert (state.worker_runtime_dir() / "local_shell_mcp" / "value.py").read_text() == 'version = "old"\n'
    assert state.read_worker_config()["runtime_digest"] == "previous-digest"
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()
    assert installer.rollback_pending_runtime() is False
