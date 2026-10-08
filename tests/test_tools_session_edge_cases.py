from __future__ import annotations

from types import SimpleNamespace

import pytest

import local_shell_mcp.tools as mcp_tools
from local_shell_mcp.auth import Principal


def test_current_session_subject_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: None)
    assert mcp_tools._current_session_subject() == "local-mcp-client"

    oauth = Principal("mail@example.com", "", {"auth": "oauth"})
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: oauth)
    assert mcp_tools._current_session_subject() == "mail@example.com"

    trusted = Principal(None, "local", {"auth": "local-cli"})
    monkeypatch.setattr(mcp_tools, "current_principal", lambda: trusted)
    assert mcp_tools._current_session_subject() is None

    monkeypatch.setattr(mcp_tools, "get_settings", lambda: SimpleNamespace(auth_mode="none"))
    assert mcp_tools._current_session_subject(create=True) == "anonymous"
    monkeypatch.setattr(mcp_tools, "get_settings", lambda: SimpleNamespace(auth_mode="oauth"))
    assert mcp_tools._current_session_subject(create=True) == "local-user"
    monkeypatch.setattr(mcp_tools, "get_settings", lambda: SimpleNamespace(auth_mode="other"))
    assert mcp_tools._current_session_subject(create=True) == "local-mcp-client"

@pytest.mark.asyncio
async def test_tools_session_cleanup_retry_failure_then_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        def __init__(self):
            self.calls = 0

        def retry_tool_call_cleanup(self, lease):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("backend unavailable")
            return True

    manager = Manager()
    key = (id(manager), "session")
    monkeypatch.setattr(mcp_tools, "audit", lambda *args, **kwargs: None)
    original_sleep = mcp_tools.asyncio.sleep

    async def no_delay(delay):
        await original_sleep(0)

    monkeypatch.setattr(mcp_tools.asyncio, "sleep", no_delay)
    mcp_tools._SESSION_LEASE_CLEANUP_QUEUES[key] = {
        "call": ({"session_id": "session"}, "run_shell", float("inf"))
    }
    await mcp_tools._retry_session_tool_cleanups(manager, queue_key=key)
    assert manager.calls == 2
    assert key not in mcp_tools._SESSION_LEASE_CLEANUP_QUEUES

@pytest.mark.asyncio
async def test_tools_finish_session_activity_exception_schedules_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        def finish_tool_call(self, *args, **kwargs):
            raise RuntimeError("store down")

    scheduled = []
    monkeypatch.setattr(mcp_tools, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mcp_tools,
        "_schedule_session_tool_cleanup_retry",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    await mcp_tools._finish_session_tool_activity(
        Manager(),
        {"session_id": "s"},
        "tool_finished",
        {},
        tool_name="run_shell",
        call_id="c",
        stage="finish",
    )
    assert scheduled
    mcp_tools._schedule_session_tool_cleanup_retry(
        Manager(), {}, tool_name="run_shell", call_id="missing-session"
    )

@pytest.mark.asyncio
async def test_tools_empty_cleanup_queue_and_missing_session_schedule() -> None:
    key = (123456789, "missing")
    await mcp_tools._retry_session_tool_cleanups(object(), queue_key=key)
    mcp_tools._schedule_session_tool_cleanup_retry(
        object(), {}, tool_name="run_shell", call_id="call"
    )
