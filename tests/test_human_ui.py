from __future__ import annotations

import json

from fastapi.testclient import TestClient

from local_shell_mcp.audit import audit, query_audit, suppress_audit
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch, *, auth_mode: str = "none") -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()


def test_human_file_api_has_yazi_style_directory_payload(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    (tmp_path / "folder").mkdir()
    (tmp_path / "alpha.txt").write_text("alpha", encoding="utf-8")

    client = TestClient(build_http_app())
    response = client.get("/api/ui/files", params={"machine": "local", "path": "."})

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["machine"] == "local"
    assert payload["path"] == "."
    assert [entry["name"] for entry in payload["entries"]][:2] == [".state", "folder"]
    assert any(entry["name"] == "alpha.txt" and entry["type"] == "file" for entry in payload["entries"])


def test_human_file_mutations_are_not_audited(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(build_http_app())

    response = client.post(
        "/api/ui/files/write",
        json={"machine": "local", "path": "manual.txt", "content": "human"},
    )

    assert response.status_code == 200
    assert (tmp_path / "manual.txt").read_text(encoding="utf-8") == "human"
    audit_path = tmp_path / "audit.jsonl"
    assert not audit_path.exists() or audit_path.read_text(encoding="utf-8") == ""


def test_suppress_audit_context_excludes_manual_activity(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    audit("mcp_tool_call_start", tool="list_files", machine="worker-a")
    with suppress_audit():
        audit("shell_send", session="manual")
    audit("mcp_tool_call_end", tool="list_files", ok=True, machine="worker-a")

    records = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == [
        "mcp_tool_call_start",
        "mcp_tool_call_end",
    ]


def test_query_audit_filters_node_operation_and_order(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    path = tmp_path / "audit.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {"ts": 10, "event": "mcp_tool_call_start", "tool": "read_file", "machine": "worker-a"},
                {"ts": 20, "event": "mcp_tool_call_start", "tool": "run_shell_tool", "machine": "worker-b"},
                {"ts": 30, "event": "mcp_tool_call_end", "tool": "run_shell_tool", "machine": "worker-b", "ok": True},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = query_audit(node="worker-b", operation="run", sort="asc")

    assert result["total_matched"] == 2
    assert [entry["ts"] for entry in result["entries"]] == [20, 30]
    assert all(entry["node"] == "worker-b" for entry in result["entries"])


def test_webui_shell_is_public_but_api_remains_oauth_protected(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    get_settings.cache_clear()
    client = TestClient(build_http_app())

    page = client.get("/ui")
    api = client.get("/api/ui/bootstrap")

    assert page.status_code == 200
    assert "local-shell-mcp UI" in page.text
    assert api.status_code == 401
