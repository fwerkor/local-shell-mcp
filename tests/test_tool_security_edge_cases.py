from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from edge_case_support import symlink_or_skip
from edge_case_support import workspace as _transfer_workspace
from pydantic import BaseModel

import local_shell_mcp.tools as mcp_tools
import local_shell_mcp.transfer_ops as transfer_ops
from local_shell_mcp.auth import Principal
from local_shell_mcp.settings import get_settings


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
    _transfer_workspace(tmp_path, monkeypatch)
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
    symlink_or_skip(link, escaped)
    with pytest.raises(ValueError, match="escapes"):
        mcp_tools._gui_temp_path(str(link), must_exist=True)

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

def test_tools_staging_parent_symlink_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    symlink_or_skip(root / ".local-shell-mcp", outside, target_is_directory=True)
    settings = SimpleNamespace(workspace_root=root, remote_job_timeout_s=60)
    monkeypatch.setattr(mcp_tools, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="relay staging parent escapes"):
        mcp_tools._controller_relay_staging_path()
    with pytest.raises(ValueError, match="GUI staging parent escapes"):
        mcp_tools._controller_gui_staging_path()
