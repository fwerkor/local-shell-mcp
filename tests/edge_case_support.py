from __future__ import annotations

from pathlib import Path

import pytest

from local_shell_mcp.settings import get_settings


def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    return tmp_path


def symlink_or_skip(link: Path, target: Path | str, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform")


class _FakeHandle:
    def __init__(self, fd: int = 7) -> None:
        self._fd = fd
        self.seeks: list[tuple[int, ...]] = []

    def fileno(self) -> int:
        return self._fd

    def seek(self, *args: int) -> None:
        self.seeks.append(args)



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



