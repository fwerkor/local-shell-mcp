import pytest
from conftest import python_shell_command
from fastapi.testclient import TestClient

from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    return TestClient(build_http_app())


def _mcp_data(response):
    return response[1]["data"]


@pytest.mark.asyncio
async def test_http_list_files_matches_mcp_payload(tmp_path, monkeypatch):
    (tmp_path / "alpha.txt").write_text("hello", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)

    http_payload = client.post("/tools/list_files", json={"path": "."}).json()
    mcp_payload = _mcp_data(await build_mcp().call_tool("list_files", {"path": "."}))

    def comparable_listing(rows):
        return sorted((item["path"], item["type"], item["size"]) for item in rows)

    assert comparable_listing(http_payload) == comparable_listing(mcp_payload)


@pytest.mark.asyncio
async def test_http_read_file_matches_mcp_payload(tmp_path, monkeypatch):
    (tmp_path / "alpha.txt").write_text("hello\nworld\n", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)
    args = {"path": "alpha.txt", "start_line": 2}

    http_payload = client.post("/tools/read_file", json=args).json()
    mcp_payload = _mcp_data(await build_mcp().call_tool("read_file", args))

    assert http_payload == mcp_payload


@pytest.mark.asyncio
async def test_http_run_shell_matches_mcp_command_payload(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    args = {"command": python_shell_command("print('parity', end='')"), "cwd": ".", "timeout_s": 5}

    http_payload = client.post("/tools/run_shell", json=args).json()
    mcp_payload = _mcp_data(await build_mcp().call_tool("run_shell_tool", args))

    assert http_payload["ok"] is True
    assert http_payload["stdout"] == mcp_payload["stdout"] == "parity"
    assert http_payload["exit_code"] == mcp_payload["exit_code"] == 0
