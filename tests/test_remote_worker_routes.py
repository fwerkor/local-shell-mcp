from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote_worker_routes as routes
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_worker_bundle_and_manifest_are_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    routes.worker_bundle_bytes.cache_clear()
    first = routes.worker_bundle_bytes()
    routes.worker_bundle_bytes.cache_clear()
    second = routes.worker_bundle_bytes()
    assert first == second

    response = await routes.worker_manifest(None)  # type: ignore[arg-type]
    data = json.loads(response.body)
    assert data["sha256"] == hashlib.sha256(first).hexdigest()
    assert data["url"] == "https://example.test/remote/worker-bundle.tgz"

    public_manifest = await routes.worker_bundle(SimpleNamespace(query_params={"manifest": "1"}))
    assert json.loads(public_manifest.body) == data
    bundle = await routes.worker_bundle(None)  # type: ignore[arg-type]
    assert bundle.body == first


@pytest.mark.asyncio
async def test_join_script_caches_bundle_and_removes_invite_from_worker_process(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    response = await routes.join_script(None)  # type: ignore[arg-type]
    script = response.body.decode("utf-8")
    assert "/remote/worker-bundle.tgz?manifest=1" in script
    assert "bundle.sha256" in script
    assert "checksum mismatch" in script
    assert "install-service" in script
    assert "install-launcher" in script
    assert 'export PATH="$HOME/.local/bin:$PATH"' in script
    assert "--invite-stdin" in script
    assert "exec python3 -m local_shell_mcp.remote_worker run" in script
    assert "remote_worker run --invite" not in script


def test_remote_routes_replace_worker_bootstrap_endpoints():
    paths = [route.path for route in routes.remote_routes()]
    assert paths[:3] == [
        "/join",
        "/remote/worker-manifest.json",
        "/remote/worker-bundle.tgz",
    ]
    assert "/remote/register" in paths
    assert "/remote/resume" in paths
