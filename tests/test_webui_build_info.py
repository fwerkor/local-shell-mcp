"""About panel should report LSM, not the vendored LibreChat build."""

from __future__ import annotations

from local_shell_mcp import __version__
from local_shell_mcp.webui import build_info


def test_about_build_info_with_source_checkout(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(build_info, "_source_root", lambda: tmp_path)
    monkeypatch.setattr(
        build_info, "_git_value",
        lambda _root, *args: "a" * 40 if "rev-parse" in args else "main",
    )
    build_info._checkout_info.cache_clear()
    for name in ("COMMIT", "BRANCH", "DATE"):
        monkeypatch.delenv("LOCAL_SHELL_MCP_BUILD_" + name, raising=False)
    try:
        assert build_info.about_build_info() == {
            "lsmVersion": __version__,
            "buildInfo": {"commit": "a" * 40, "commitShort": "a" * 8, "branch": "main"},
        }
    finally:
        build_info._checkout_info.cache_clear()


def test_about_build_info_without_checkout_or_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info, "_source_root", lambda: tmp_path)
    for name in ("COMMIT", "BRANCH", "DATE"):
        monkeypatch.delenv("LOCAL_SHELL_MCP_BUILD_" + name, raising=False)
    build_info._checkout_info.cache_clear()
    try:
        assert build_info.about_build_info() == {"lsmVersion": __version__}
    finally:
        build_info._checkout_info.cache_clear()


def test_about_build_info_from_deployment_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info, "_source_root", lambda: tmp_path)
    monkeypatch.setenv("LOCAL_SHELL_MCP_BUILD_COMMIT", "f" * 40)
    monkeypatch.setenv("LOCAL_SHELL_MCP_BUILD_BRANCH", "release")
    monkeypatch.setenv("LOCAL_SHELL_MCP_BUILD_DATE", "2026-11-23T08:00:00Z")
    build_info._checkout_info.cache_clear()
    try:
        assert build_info.about_build_info()["buildInfo"] == {
            "commit": "f" * 40,
            "commitShort": "f" * 8,
            "branch": "release",
            "buildDate": "2026-11-23T08:00:00Z",
        }
    finally:
        build_info._checkout_info.cache_clear()
