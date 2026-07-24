import asyncio
import shutil

import pytest
from mcp.types import CallToolResult

import local_shell_mcp.search_ops as search_ops_module
from local_shell_mcp.errors import PathNotFoundError
from local_shell_mcp.search_ops import grep, tree
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import _handled_error


@pytest.mark.asyncio
async def test_tree_reports_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "project" / "src").mkdir(parents=True)
    (tmp_path / "project" / "README.md").write_text("hello", encoding="utf-8")

    result = await tree("project")

    assert result["exists"] is True
    assert result["is_directory"] is True
    assert "src/" in result["entries"]
    assert "README.md" in result["entries"]


@pytest.mark.asyncio
async def test_tree_clamps_entries_without_sorting_entire_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_TREE_ENTRIES", "3")
    get_settings.cache_clear()
    for idx in range(10):
        (tmp_path / f"file-{idx}.txt").write_text("x", encoding="utf-8")

    result = await tree(".", max_entries=100)

    assert result["count"] == 3
    assert len(result["entries"]) == 3
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_tree_returns_context_for_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "actual").mkdir()

    result = await tree("missing/project")

    assert result["exists"] is False
    assert result["is_directory"] is False
    assert result["nearest_existing_parent"] == str(tmp_path)
    assert "actual/" in result["nearest_parent_entries"]
    assert "Path does not exist" in result["message"]


def test_tool_error_returns_failed_not_found_result(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "actual").mkdir()

    result = _handled_error(PathNotFoundError(tmp_path / "missing" / "project"))

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert result.structuredContent["ok"] is False
    data = result.structuredContent["data"]
    assert data["status"] == "not_found"
    assert data["error_type"] == "FileNotFoundError"
    assert data["exists"] is False
    assert data["nearest_existing_parent"] == str(tmp_path)
    assert "actual/" in data["nearest_parent_entries"]


def test_tool_error_returns_failed_error_result():
    result = _handled_error(ValueError("bad input"))

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert result.structuredContent["ok"] is False
    assert result.structuredContent["data"] == {
        "status": "error",
        "error_type": "ValueError",
        "message": "bad input",
    }


def test_os_file_not_found_message_is_not_treated_as_workspace_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    result = _handled_error(FileNotFoundError(2, "The system cannot find the file specified"))

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    data = result.structuredContent["data"]
    assert data["status"] == "error"
    assert data["error_type"] == "FileNotFoundError"
    assert "path" not in data
    assert str(tmp_path) not in result.structuredContent["message"]


def test_syscall_file_not_found_inside_workspace_keeps_path_context(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    missing = tmp_path / "removed-during-read.txt"

    result = _handled_error(FileNotFoundError(2, "No such file or directory", str(missing)))

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    data = result.structuredContent["data"]
    assert data["status"] == "not_found"
    assert data["path"] == str(missing)


@pytest.mark.asyncio
async def test_grep_cleans_up_cancelled_stderr_reader(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    events = []

    class FakeStdout:
        async def readline(self):
            return b""

    class FakeStderr:
        async def read(self, limit):  # noqa: ARG002
            await asyncio.Event().wait()

    class FakeTransport:
        def close(self):
            events.append("transport-close")

    class FakeProcess:
        stdin = None
        stdout = FakeStdout()
        stderr = FakeStderr()
        returncode = 1
        _transport = FakeTransport()

        async def wait(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

    async def fake_create_subprocess_exec(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return FakeProcess()

    monkeypatch.setattr(search_ops_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await grep("needle", cwd=".", regex=False)

    assert result["ok"] is True
    assert events == ["transport-close"]


@pytest.mark.asyncio
async def test_grep_accepts_query_starting_with_dash(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    if not shutil.which(get_settings().rg_bin):
        pytest.skip("missing rg")
    term = chr(45) + "needle"
    (tmp_path / "dash.txt").write_text(term + "\\n", encoding="utf-8")

    result = await grep(term, cwd=".", regex=False)

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["matches"][0]["path"].endswith("dash.txt")


@pytest.mark.asyncio
async def test_grep_returns_first_matches_when_output_is_large(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_GREP_RESULTS", "3")
    get_settings.cache_clear()
    if not shutil.which(get_settings().rg_bin):
        pytest.skip("missing rg")
    lines = "".join(f"needle {idx}\n" for idx in range(20))
    (tmp_path / "many.txt").write_text(lines, encoding="utf-8")

    result = await grep("needle", cwd=".", regex=False, max_results=3)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert [item["line"] for item in result["matches"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_tree_does_not_follow_directory_symlinks(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret-name.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available in this environment")

    result = await tree(".", depth=3)

    assert "escape" in result["entries"]
    assert not any("secret-name.txt" in entry for entry in result["entries"])
