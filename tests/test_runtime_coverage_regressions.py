from __future__ import annotations

import asyncio

import pytest

import local_shell_mcp.human_ui as human_ui
import local_shell_mcp.tools as tools


@pytest.mark.parametrize(
    "reader",
    [
        human_ui._read_linux_cpu_times,
        human_ui._read_linux_memory,
        human_ui._read_linux_network,
    ],
)
def test_local_system_snapshot_readers_tolerate_unavailable_proc_files(
    monkeypatch: pytest.MonkeyPatch, reader
) -> None:
    class MissingProcFile:
        def read_text(self, **kwargs):
            raise FileNotFoundError("procfs unavailable")

    monkeypatch.setattr(human_ui, "Path", lambda path: MissingProcFile())
    assert reader() is None


@pytest.mark.parametrize(
    ("reader", "content"),
    [
        (human_ui._read_linux_cpu_times, "cpu 42 malformed 4\n"),
        (human_ui._read_linux_memory, "MemTotal: malformed kB\n"),
        (human_ui._read_linux_network, "header\nheader\ninvalid record\n"),
    ],
)
def test_local_system_snapshot_readers_tolerate_malformed_proc_contents(
    monkeypatch: pytest.MonkeyPatch, reader, content: str
) -> None:
    class MalformedProcFile:
        def read_text(self, **kwargs):
            return content

    monkeypatch.setattr(human_ui, "Path", lambda path: MalformedProcFile())
    assert reader() is None


@pytest.mark.asyncio
async def test_cancelled_tool_waits_for_inflight_side_effect_to_finish() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    completed = False

    async def side_effect() -> str:
        nonlocal completed
        started.set()
        await release.wait()
        completed = True
        return "committed"

    request = asyncio.create_task(tools._await_non_cancellable(side_effect()))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        request.cancel()
        await asyncio.sleep(0)
        assert not request.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(request, timeout=1)
    assert completed


@pytest.mark.parametrize(
    ("reader", "content", "expected"),
    [
        (human_ui._read_linux_cpu_times, "cpu 1 2 3 4\n", (10, 4)),
        (human_ui._read_linux_cpu_times, "cpu 1 2 3\n", None),
        (human_ui._read_linux_memory, "MemTotal: 100 kB\nMemFree: 40 kB\n", (102400, 61440)),
        (
            human_ui._read_linux_network,
            "header\nheader\nlo: 1 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0\neth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n",
            (100, 200),
        ),
    ],
)
def test_local_system_snapshot_parses_partial_proc_records(
    monkeypatch: pytest.MonkeyPatch, reader, content: str, expected
) -> None:
    class ProcFile:
        def read_text(self, **kwargs):
            return content

    monkeypatch.setattr(human_ui, "Path", lambda path: ProcFile())
    assert reader() == expected


@pytest.mark.asyncio
async def test_cancelled_tool_preserves_side_effect_failure_until_settled() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    failed = False

    async def side_effect() -> None:
        nonlocal failed
        started.set()
        await release.wait()
        failed = True
        raise ValueError("write failed")

    request = asyncio.create_task(tools._await_non_cancellable(side_effect()))
    await asyncio.wait_for(started.wait(), timeout=1)
    request.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(request, timeout=1)
    assert failed
