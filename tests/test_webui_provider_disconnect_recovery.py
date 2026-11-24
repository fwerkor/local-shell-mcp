"""Transport-retry safety and user-facing diagnostics for interrupted model streams."""

import httpx
import pytest

from local_shell_mcp.webui import agent_runtime, generation_routes
from local_shell_mcp.webui.agent_runtime import (
    AgentContext,
    AgentLoopState,
    ToolBatchOutput,
    run_agent_loop,
)
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


async def forbidden(*_args, **_kwargs):
    raise AssertionError("This edge must not execute")


@pytest.fixture
def model_profile():
    return ProviderConfig("openai", "model-x", "https://upstream.example/api", "private-secret")


@pytest.mark.asyncio
async def test_disconnect_before_first_event_retries_same_model_turn(monkeypatch, model_profile):
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(agent_runtime.asyncio, "sleep", sleep)
    state = AgentLoopState(AgentContext(model_profile, []), [{"role": "user", "content": "hi"}])
    attempts = 0
    rendered = []

    async def stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        yield "success"

    async def display(chunk):
        rendered.append(chunk)

    result = await run_agent_loop(state, stream_tools=forbidden, stream_text=stream,
                                  dispatch=forbidden, on_text=display)
    assert attempts == 3 and delays == [0.4, 1.2000000000000002]
    assert state.model_turn == 1 and state.step == 1
    assert rendered == ["success"]
    assert result[-1] == {"role": "assistant", "content": "success"}


@pytest.mark.asyncio
async def test_disconnect_after_visible_output_never_retries_or_commits_partial_call(monkeypatch, model_profile):
    state = AgentLoopState(AgentContext(model_profile, []), [])
    attempts = 0
    rendered = []

    async def stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        yield "already visible"
        raise httpx.RemoteProtocolError("incomplete chunked read")

    async def display(chunk):
        rendered.append(chunk)

    with pytest.raises(httpx.RemoteProtocolError):
        await run_agent_loop(state, stream_tools=forbidden, stream_text=stream,
                             dispatch=forbidden, on_text=display)
    assert attempts == 1
    assert rendered == ["already visible"]
    assert state.messages == []


@pytest.mark.asyncio
async def test_post_tool_disconnect_is_retried_without_reexecuting_tool(monkeypatch, model_profile):
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", forbidden_sleep)
    state = AgentLoopState(AgentContext(model_profile, [{"name": "file_read"}]),
                           [{"role": "user", "content": "read"}])
    attempts = 0
    executed = []

    async def stream(_profile, messages, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield ModelToolCall("once", "file_read", {"path": "/tmp/a"})
        elif attempts == 2:
            assert messages[-1]["role"] == "tool"
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        else:
            assert messages[-1]["role"] == "tool"
            yield "finish"

    async def dispatch(calls, _state):
        executed.extend(calls)
        return ToolBatchOutput([{"role": "tool", "tool_call_id": "once", "content": "result"}])

    async def display(_chunk):
        pass

    await run_agent_loop(state, stream_tools=stream, stream_text=forbidden,
                         dispatch=dispatch, on_text=display)
    assert attempts == 3
    assert [call.call_id for call in executed] == ["once"]
    assert state.model_turn == 2
    assert state.messages[-1]["content"] == "finish"


async def forbidden_sleep(_seconds):
    pass


@pytest.mark.asyncio
async def test_disconnection_after_emitted_tool_call_is_not_retried(model_profile):
    state = AgentLoopState(AgentContext(model_profile, [{"name": "file_read"}]), [])
    attempts = 0

    async def stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        yield ModelToolCall("call", "file_read", {"path": "/tmp/a"})
        raise httpx.RemoteProtocolError("broken")

    with pytest.raises(httpx.RemoteProtocolError):
        await run_agent_loop(state, stream_tools=stream, stream_text=forbidden,
                             dispatch=forbidden, on_text=forbidden)
    assert attempts == 1
    assert state.messages == []


@pytest.mark.asyncio
async def test_http_status_error_does_not_trigger_transport_retry(model_profile):
    state = AgentLoopState(AgentContext(model_profile, []), [])
    attempts = 0

    async def stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        response = httpx.Response(401, request=httpx.Request("POST", "https://upstream.example/"))
        raise httpx.HTTPStatusError("upstream rejected", request=response.request, response=response)
        yield "unreachable"

    with pytest.raises(httpx.HTTPStatusError):
        await run_agent_loop(state, stream_tools=forbidden, stream_text=stream,
                             dispatch=forbidden, on_text=forbidden)
    assert attempts == 1


def test_failure_details_are_actionable_and_do_not_echo_credentials(model_profile):
    from types import SimpleNamespace

    job = SimpleNamespace(run_id="run-123")
    detail = generation_routes._generation_error_report(
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        job, model_profile)
    assert "RemoteProtocolError" in detail
    assert "Server disconnected without sending a response" in detail
    assert "model-x" in detail and "run-123" in detail
    assert "private-secret" not in detail
    unsafe = httpx.RemoteProtocolError("Authorization: Bearer private-secret")
    hidden = generation_routes._generation_error_report(unsafe, job, model_profile)
    assert "private-secret" not in hidden and "Authorization" not in hidden
    response = httpx.Response(429, request=httpx.Request("POST", "https://upstream.example/secret?key=private-secret"))
    status = generation_routes._generation_error_report(
        httpx.HTTPStatusError("Authorization: Bearer private-secret", request=response.request, response=response),
        job, model_profile)
    assert "HTTP 429" in status
    assert "private-secret" not in status
