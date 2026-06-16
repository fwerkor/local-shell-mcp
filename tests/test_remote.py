

import subprocess
import urllib.error
from io import BytesIO

import pytest

from local_shell_mcp import remote
from local_shell_mcp.remote import join_script
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_join_script_loads_vendored_worker_dependencies(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.test")
    get_settings.cache_clear()

    response = await join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")

    assert 'export PYTHONPATH="$TMPDIR:$TMPDIR/vendor:${PYTHONPATH:-}"' in script


@pytest.mark.asyncio
async def test_join_script_reports_download_progress_and_uses_worker_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.test")
    get_settings.cache_clear()

    response = await join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")

    assert "Downloading worker bundle" in script
    assert "--progress-bar" in script
    assert "python3 -m local_shell_mcp.remote_worker" in script
    assert "python3 -m local_shell_mcp.main worker" not in script


def test_worker_post_json_uses_curl_and_parses_success(monkeypatch):
    calls = []

    def fake_run(command, *, input, capture_output, check):  # noqa: A002
        calls.append((command, input, check))
        assert capture_output is True
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b'{"ok": true, "data": {"registered": true}}\nLOCAL_SHELL_MCP_HTTP_STATUS:200',
            stderr=b"",
        )

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    monkeypatch.setattr(remote.subprocess, "run", fake_run)

    result = remote._worker_post_json(  # noqa: SLF001
        "https://example.test/remote/register",
        {"invite": "abc"},
        {"Authorization": "Bearer token"},
        30,
    )

    assert result == {"ok": True, "data": {"registered": True}}
    command, body, check = calls[0]
    assert command[:4] == ["/usr/bin/curl", "--max-time", "30", "-sS"]
    assert ["-H", "Authorization: Bearer token"] in [command[index : index + 2] for index in range(len(command) - 1)]
    assert command[-1] == "https://example.test/remote/register"
    assert body == b'{"invite": "abc"}'
    assert check is False


def test_worker_post_json_curl_reports_non_2xx_body(monkeypatch):
    def fake_run(command, *, input, capture_output, check):  # noqa: A002, ARG001
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"<html>Cloudflare 1010</html>\nLOCAL_SHELL_MCP_HTTP_STATUS:403",
            stderr=b"",
        )

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    monkeypatch.setattr(remote.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="failed with 403: <html>Cloudflare 1010</html>"):
        remote._worker_post_json("https://example.test/remote/register", {"invite": "abc"})  # noqa: SLF001


def test_worker_post_json_falls_back_to_urllib_when_curl_unavailable(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self):
            return b'{"ok": true, "data": {"heartbeat": true}}'

    captured = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    monkeypatch.setattr(remote.urllib.request, "urlopen", fake_urlopen)

    result = remote._worker_post_json(  # noqa: SLF001
        "https://example.test/remote/poll",
        {},
        {"Authorization": "Bearer token"},
        12,
    )

    assert result == {"ok": True, "data": {"heartbeat": True}}
    assert captured["timeout"] == 12
    assert captured["request"].headers["Authorization"] == "Bearer token"
    assert captured["request"].data == b"{}"


def test_worker_post_json_urllib_reports_non_2xx_body(monkeypatch):
    def fake_urlopen(request, timeout=None):  # noqa: ANN001, ARG001
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs={},
            fp=BytesIO(b"<html>Cloudflare 1010</html>"),
        )

    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    monkeypatch.setattr(remote.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="failed with 403: <html>Cloudflare 1010</html>"):
        remote._worker_post_json("https://example.test/remote/result", {"job_id": "job_1"})  # noqa: SLF001
