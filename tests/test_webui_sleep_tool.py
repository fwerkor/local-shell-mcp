import asyncio
import json
import math

import pytest

from local_shell_mcp.webui.approval_settings import call_decision
from local_shell_mcp.webui.sleep_tool import invoke_sleep, sleep_seconds


@pytest.mark.parametrize("arguments", [{}, {"seconds": 0}, {"seconds": 0.1}, {"seconds": 300}])
def test_sleep_valid_arguments(arguments):
    assert sleep_seconds(arguments) == arguments.get("seconds", 10)


@pytest.mark.parametrize("arguments", [
    {"seconds": -1}, {"seconds": 301}, {"seconds": True}, {"seconds": "5"},
    {"seconds": None}, {"seconds": math.nan}, {"seconds": math.inf}, {"extra": 1},
])
def test_sleep_rejects_invalid_arguments(arguments):
    with pytest.raises(ValueError, match="seconds"):
        sleep_seconds(arguments)


@pytest.mark.asyncio
async def test_sleep_does_not_block_other_tasks_and_returns_elapsed():
    task = asyncio.create_task(invoke_sleep(0.02, lambda: None))
    await asyncio.sleep(0)
    assert not task.done()
    result = json.loads(await task)
    assert result["slept_seconds"] >= 0.019


@pytest.mark.asyncio
async def test_sleep_cancels_promptly():
    task = asyncio.create_task(invoke_sleep(300, lambda: None))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)


@pytest.mark.asyncio
async def test_sleep_rechecks_grant(monkeypatch):
    from local_shell_mcp.webui import sleep_tool

    clock = [0]
    monkeypatch.setattr(sleep_tool.time, "monotonic", lambda: clock[0])

    async def advance(seconds):
        clock[0] += seconds

    monkeypatch.setattr(sleep_tool.asyncio, "sleep", advance)

    def check():
        if clock[0] >= 5:
            raise PermissionError("revoked")

    with pytest.raises(PermissionError, match="revoked"):
        await invoke_sleep(300, check)


def test_sleep_respects_approval_policy():
    assert call_decision("automatic", None, "sleep", {}) is None
    assert call_decision("dangerous", None, "sleep", {}) is None
    assert call_decision("all", None, "sleep", {}) == {"decision": "ask"}
    assert call_decision("automatic", {"enabled": True, "deny": ["sleep"]},
                         "sleep", {})["decision"] == "deny"
