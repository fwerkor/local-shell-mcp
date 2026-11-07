"""Validate private, deterministic runtime MCP configuration generation."""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "integrations" / "librechat"
SPEC = importlib.util.spec_from_file_location("lsm_librechat_render_config", ROOT / "render_config.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_render_config_resolves_mcp_credentials_privately(tmp_path):
    dest = tmp_path / "librechat.runtime.yaml"
    secret = "v" * 48
    MODULE.render(ROOT / "librechat.yaml", dest, {"LSM_LIBRECHAT_BRIDGE_SECRET": secret})
    text = dest.read_text()
    assert 'requiresOAuth: false' in text
    assert 'url: "http://local-shell-mcp:8765/mcp"' in text
    assert f'Authorization: "Bearer {secret}"' in text
    assert 'searxngInstanceUrl: "${SEARXNG_INSTANCE_URL}"' in text
    assert "${" not in text.replace("${SEARXNG_INSTANCE_URL}", "")
    if os.name != "nt":
        assert dest.stat().st_mode & 0o777 == (0o600 if os.geteuid() == 1000 else 0o640)
        if os.geteuid() != 1000:
            assert dest.stat().st_gid == 1000
    assert secret not in (ROOT / "librechat.yaml").read_text()


def test_render_config_accepts_only_staging_or_private_origins(tmp_path):
    dest = tmp_path / "config.yaml"
    env = {"LSM_LIBRECHAT_BRIDGE_SECRET": "x" * 40,
           "LSM_CONTROLLER_INTERNAL_URL": "http://host.docker.internal:8766"}
    MODULE.render(ROOT / "librechat.yaml", dest, env)
    assert 'url: "http://host.docker.internal:8766/mcp"' in dest.read_text()
    assert '- "host.docker.internal:8766"' in dest.read_text()
    old = dest.read_bytes()
    for invalid in ("http://localhost:8765", "http://evil.example:8765",
                    "https://host.docker.internal:8766", "http://host.docker.internal:8766/evil",
                    "http://user:pass@local-shell-mcp:8765", "http://local-shell-mcp:bad"):
        with pytest.raises(ValueError):
            MODULE.render(ROOT / "librechat.yaml", dest, {**env, "LSM_CONTROLLER_INTERNAL_URL": invalid})
        assert dest.read_bytes() == old


def test_render_config_rejects_missing_secret_and_modified_template(tmp_path):
    dest = tmp_path / "config.yaml"
    for secret in ("", "x" * 31):
        with pytest.raises(ValueError, match="32 bytes"):
            MODULE.render(ROOT / "librechat.yaml", dest, {"LSM_LIBRECHAT_BRIDGE_SECRET": secret})
    source = tmp_path / "template.yaml"
    source.write_text('url: "${LSM_CONTROLLER_INTERNAL_URL}/mcp"\n')
    with pytest.raises(ValueError, match="Unexpected LibreChat"):
        MODULE.render(source, dest, {"LSM_LIBRECHAT_BRIDGE_SECRET": "x" * 40})
    assert not dest.exists()


def test_embedded_webui_uses_product_brand_not_oauth_client_name():
    root = Path(__file__).resolve().parents[1] / "integrations" / "librechat"
    compose = (root / "compose.yaml").read_text()
    config = (root / "app" / "api" / "server" / "routes" / "config.js").read_text()
    html = (root / "app" / "client" / "index.html").read_text()
    assert "APP_TITLE: local-shell-mcp" in compose
    assert "appTitle: process.env.APP_TITLE || 'local-shell-mcp'" in config
    assert "<title>local-shell-mcp</title>" in html
    client = root / "app" / "client" / "src"
    title = (client / "utils" / "documentTitle.ts").read_text()
    startup = (client / "routes" / "Layouts" / "Startup.tsx").read_text()
    assert "DEFAULT_APP_TITLE = 'local-shell-mcp'" in title
    assert "startupConfig?.appTitle || 'local-shell-mcp'" in startup
    web = (root.parent.parent / "ui" / "src" / "web.ts").read_text()
    assert 'client_name: "WebUI"' in web
