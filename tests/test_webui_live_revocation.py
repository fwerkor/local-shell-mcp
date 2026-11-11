"""Live authorization cancellation uses native process cleanup and call isolation."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from types import SimpleNamespace

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import quote_shell_argument, quote_shell_executable
from local_shell_mcp.webui import lsm_tool_registry as registry
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "sqlite")
    monkeypatch.setattr(registry, "_AUTHORIZATION_RECHECK_SECONDS", 0.02)
    get_settings.cache_clear()
    registry._registry_for_state.cache_clear()
    repo = _repo()
    conversations = [repo.create_conversation("local", {"title": name})["conversationId"]
                     for name in ("revocable", "independent")]
    repo.save_setting("local", "agent.machine_policy.global", {"local": "write"})
    yield repo, conversations
    registry._registry_for_state.cache_clear()
    get_settings.cache_clear()


def command(code):
    return quote_shell_executable(sys.executable) + " -c " + quote_shell_argument(code)


async def wait_for_file(path):
    async with asyncio.timeout(10):
        while not path.exists():
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["revoke", "expire"])
async def test_native_command_is_stopped_when_its_own_grant_is_lost(policy, tmp_path, reason, monkeypatch):
    repo, (cid, independent) = policy
    started, leaked, unaffected = [tmp_path / value for value in ("started", "leaked", "unaffected")]
    code = ("from pathlib import Path; import time; "
            "Path(" + repr(str(started)) + ").write_text('started'); "
            "time.sleep(3); Path(" + repr(str(leaked)) + ").write_text('leaked')")
    scopes = {"shell:read", "shell:write", "shell:execute"}
    expires = int(time.time()) + 60
    task = asyncio.create_task(registry.call_tool("local", cid,
        ModelToolCall("long", "run_shell", {"command": command(code), "cwd": str(tmp_path), "timeout_s": 15}),
        granted_scopes=scopes, grant_expires=expires if reason == "expire" else None))
    other = None
    try:
        await wait_for_file(started)
        other_code = "from pathlib import Path; Path(" + repr(str(unaffected)) + ").write_text('kept')"
        other = asyncio.create_task(registry.call_tool("local", independent,
            ModelToolCall("separate", "run_shell", {"command": command(other_code), "cwd": str(tmp_path), "timeout_s": 15}),
            granted_scopes=scopes))
        if reason == "revoke":
            repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "none"})
        else:
            from local_shell_mcp.webui import machine_permissions

            monkeypatch.setattr(machine_permissions, "time", SimpleNamespace(time=lambda: expires + 1))
        with pytest.raises(PermissionError, match="not granted|expired"):
            await asyncio.wait_for(task, timeout=5)
        assert json.loads(await other)["ok"] is True
        assert unaffected.read_text() == "kept"
        await asyncio.sleep(3.1)
        assert not leaked.exists(), "Revoked subprocess survived its native cancellation cleanup"
        # The owner can still manage its own session without any machine grants.
        repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "none"})
        answer = await registry.call_tool("local", cid, ModelToolCall("session", "session_manage", {
            "action": "start", "objective": "Own logical session after machine revocation",
        }), granted_scopes=set())
        assert json.loads(answer)["ok"] is True
    finally:
        for running in (task, other):
            if running is not None and not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_guard_drains_protected_mutation_and_checks_ownership(policy):
    repo, (cid, _) = policy
    started, settled = asyncio.Event(), asyncio.Event()

    async def protected():
        from local_shell_mcp.tools import _await_non_cancellable
        async def mutation():
            started.set()
            await asyncio.sleep(0.08)
            settled.set()
            return "committed"
        return await _await_non_cancellable(mutation())

    def authorized():
        if started.is_set():
            raise KeyError("Conversation ownership removed")

    with pytest.raises(PermissionError, match="no longer available"):
        await registry._await_authorized(protected(), authorized)
    assert settled.is_set(), "Protected native mutation must settle before its lease is released"


@pytest.mark.asyncio
async def test_outer_abort_cancels_only_its_owned_dispatch(policy):
    cancelled = asyncio.Event()
    async def waiting():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    task = asyncio.create_task(registry._await_authorized(waiting(), lambda: None))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
