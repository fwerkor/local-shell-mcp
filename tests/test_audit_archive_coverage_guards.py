"""Archive path and index corruption regressions for the audit retention pipeline."""
from __future__ import annotations

import time

import pytest

from local_shell_mcp import audit as audit_module


@pytest.mark.parametrize('invalid', [None, 5, '../etc/passwd', r'audit-archive\\evil.jsonl.zst',
                                     'audit-archive/../evil.jsonl.zst', 'audit-archive/foo.txt'])
def test_archive_key_rejects_non_archive_names_and_traversal(invalid):
    assert audit_module._validated_archive_key(invalid) is None


@pytest.mark.parametrize('raw', [None, b'', b'not json', b'\xff', b'[]', b'{}',
                                   b'{"version":999,"archives":[]}',
                                   b'{"version":1,"archives":{}}'])
def test_archive_index_failure_is_safe_and_does_not_accept_untrusted_paths(raw):
    assert audit_module._parse_archive_index(raw) == []


@pytest.mark.parametrize('override', [
    {'start_ts': True}, {'start_ts': float('inf')}, {'start_ts': -1},
    {'end_ts': False}, {'end_ts': -1}, {'end_ts': float('nan')},
    {'records': -1}, {'raw_bytes': True}, {'compressed_bytes': '1'},
])
def test_archive_entry_validates_numeric_metadata_before_use(override):
    valid = {'key': 'audit-archive/a.jsonl.zst', 'start_ts': 1.0, 'end_ts': 2.0,
             'records': 1, 'raw_bytes': 12, 'compressed_bytes': 6}
    assert audit_module._validated_archive_entry({**valid, **override}) is None
    assert audit_module._validated_archive_entry(valid) == valid


def test_audit_archive_directory_does_not_follow_symlinks(tmp_path):
    log = tmp_path / 'audit.jsonl'
    escape = tmp_path / 'outside'
    escape.mkdir()
    try:
        (tmp_path / 'audit-archive').symlink_to(escape, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('Filesystem does not support creating symlinks for this user')
    with pytest.raises(ValueError, match='symlink'):
        audit_module._validated_archive_directory(log, create=True)
    with pytest.raises(ValueError, match='symlink'):
        audit_module._archive_file_path(log, 'audit-archive/a.jsonl.zst')


def test_audit_archive_recovered_metadata_rejects_reverse_intervals_and_invalid_filenames():
    assert audit_module._recovered_archive_entry('audit-archive/2-1-1-aabbccdd.jsonl.zst', 20) is None
    assert audit_module._recovered_archive_entry('audit-archive/1-2-1-aabbccdd.jsonl.zst', -1) is None
    assert audit_module._recovered_archive_entry('audit-archive/not-a-generated-key.jsonl.zst', 20) is None
    entry = audit_module._recovered_archive_entry('audit-archive/1-2-1-aabbccdd.jsonl.zst', 20)
    assert entry and entry['compressed_bytes'] == 20


def test_audit_missing_log_and_expired_pressure_backoff_return_to_normal(tmp_path):
    path = tmp_path / 'audit.jsonl'
    assert audit_module._audit_log_bytes(path) == 0
    assert not audit_module._audit_pressure_backoff_active(path)
    key = str(path)
    audit_module._AUDIT_PRESSURE_BACKOFF_UNTIL[key] = time.monotonic() - 1
    assert not audit_module._audit_pressure_backoff_active(path)
    assert key not in audit_module._AUDIT_PRESSURE_BACKOFF_UNTIL
