import pytest

from local_shell_mcp.config.settings import get_settings
from local_shell_mcp.fs_ops import write_text
from local_shell_mcp.tools import _secret_scan


@pytest.mark.asyncio
async def test_secret_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    write_text("x.py", "TOKEN = 'ghp_1234567890123456789012345678901234567890'")
    result = await _secret_scan(".")
    assert result["findings"]
