"""Validate private, deterministic runtime MCP configuration generation."""

import importlib.util
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
    assert 'url: "http://local-shell-mcp:8765/mcp"' in text
    assert f'Authorization: "Bearer {secret}"' in text
    assert 'searxngInstanceUrl: "http://searxng:8080"' in text
    assert "${" not in text
    assert dest.stat().st_mode & 0o777 == 0o600
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
