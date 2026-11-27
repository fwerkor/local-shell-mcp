"""Exercise transport redaction and durable generation recovery boundaries."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.exceptions import HTTPException

from local_shell_mcp.webui import auth
from local_shell_mcp.webui import generation_routes as routes
from local_shell_mcp.webui.error_diagnostics import generation_failure


@pytest.mark.parametrize('error,reason', [
    (TimeoutError('secret-token'), 'timed out'),
    (httpx.ConnectError('secret-token'), 'connection failed'),
    (httpx.ReadError('secret-token'), 'connection failed'),
])
def test_generation_failure_redacts_transport_details(error, reason):
    record = json.loads(generation_failure(error, 'run-test'))
    assert reason in record['message']
    assert 'secret-token' not in json.dumps(record)
    assert record['runId'] == 'run-test'


@pytest.mark.parametrize('error,short_reason,detail', [
    (httpx.RemoteProtocolError('peer closed connection without sending complete message body secret-token'),
     'disconnected', 'before its body was complete'),
    (httpx.ReadError('secret-token'), 'reading', 'connection failed'),
    (httpx.ReadTimeout('secret-token'), 'reading', 'exceeded its timeout'),
    (httpx.ConnectError('secret-token'), 'Unable to connect', 'connection failed'),
    (ValueError('secret-token'), 'Model generation failed', 'inspect the server logs'),
])
def test_provider_error_messages_redact_details(error, short_reason, detail):
    brief = routes._safe_model_error(error)
    report = routes._generation_error_report(error, SimpleNamespace(run_id='run-test'),
                                            SimpleNamespace(model='model-test'))
    assert short_reason in brief
    assert detail in report
    assert 'secret-token' not in brief + report
    assert 'run-test' in report


@pytest.mark.usefixtures('isolated_controller_settings')
def test_replay_open_step_handles_empty_pages_and_invalid_indices(tmp_path):
    from local_shell_mcp.sqlite_store import SQLiteDatabase
    from local_shell_mcp.webui.generations import GenerationStore

    store = GenerationStore(SQLiteDatabase(tmp_path / 'state'))
    job, _ = store.begin('alice', {'text': 'start'})
    assert routes._last_open_message_step(store, 'alice', job.run_id) is None
    # A full page of step boundaries exercises the old pagination path as
    # well as the optimized query returning only step boundary events.
    for i in range(198):
        store.append('alice', job.run_id, {'event': 'on_run_step_closed', 'data': {'id': str(i)}})
    store.append('alice', job.run_id, {'event': 'on_run_step', 'data': {
        'type': 'message_creation', 'id': 'bad', 'index': -1}})
    store.append('alice', job.run_id, {'event': 'on_run_step', 'data': {
        'type': 'message_creation', 'id': 'good', 'index': 2}})
    assert routes._last_open_message_step(store, 'alice', job.run_id) == ('good', 2, None)
    store.append('alice', job.run_id, {'event': 'on_run_step_closed', 'data': {'id': 'good'}})
    assert routes._last_open_message_step(store, 'alice', job.run_id) is None


def test_recovered_terminal_text_preserves_non_prefix_visible_answer():
    checkpoint = [{'role': 'assistant', 'content': 'prior'}, {'role': 'tool', 'content': 'result'}]
    store = SimpleNamespace(checkpoint_model_steps=lambda *_: checkpoint)
    recovered = routes._recovered_terminal_steps(store, 'alice', 'run', 'visible')
    assert recovered == checkpoint + [{'role': 'assistant', 'content': 'visible'}]
    assert len(checkpoint) == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures('isolated_controller_settings')
@pytest.mark.parametrize('error', [KeyError('stale'), ValueError('changed'), PermissionError('revoked')])
async def test_oauth_callback_rejects_stale_recovery(monkeypatch, error):
    from local_shell_mcp import settings
    generation = SimpleNamespace(run_id='run')
    monkeypatch.setattr(routes, '_generation_store', lambda: SimpleNamespace(get=lambda *_: generation))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'oauth')
    settings.get_settings.cache_clear()
    monkeypatch.setattr(auth, '_store', lambda: SimpleNamespace(session=lambda _: SimpleNamespace(
        owner='alice', scopes='shell:read', grant_until=123)))
    resume = AsyncMock(side_effect=error)
    monkeypatch.setattr(routes, '_resume_ready_oauth', resume)
    assert not await routes.resume_oauth_callback('alice', 'run', 'action', 'call', 1,
                                                 SimpleNamespace(cookies={auth.COOKIE: 'cookie'}))
    resume.assert_awaited_once_with('alice', generation, {'shell:read'}, 123,
                                   action_id='action', call_id='call', version=1)


@pytest.mark.usefixtures('isolated_controller_settings')
def test_browser_grant_rejects_session_revoked_between_reads(monkeypatch):
    from local_shell_mcp import settings
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'oauth')
    settings.get_settings.cache_clear()
    session = SimpleNamespace(owner='alice', scopes='shell:read', grant_until=123)
    replies = iter([session, None])
    monkeypatch.setattr(auth, '_store', lambda: SimpleNamespace(session=lambda _: next(replies)))
    principal = SimpleNamespace(subject='alice', claims={'client_id': 'lsm-webui', 'scope': 'shell:read'})
    request = SimpleNamespace(state=SimpleNamespace(principal=principal), cookies={auth.COOKIE: 'cookie'})
    with pytest.raises(HTTPException) as rejected:
        routes._request_grant(request)
    assert rejected.value.status_code == 401
    principal.claims['client_id'] = 'external'
    assert routes._webui_grant_cookie(request) is None


def test_compaction_diagnostic_preserves_causes_and_redacts_credentials():
    from local_shell_mcp.webui.compaction import CompactionFailed

    request = httpx.Request("POST", "https://example.invalid/v1?key=query-credential",
                            headers={"Authorization": "Bearer request-credential"})
    response = httpx.Response(429, request=request, json={"error": {
        "type": "rate_limit_error", "code": "insufficient_quota",
        "message": "Quota exhausted for request-credential; query-credential; configured-credential",
    }})

    def upstream():
        response.raise_for_status()

    try:
        try:
            upstream()
        except httpx.HTTPStatusError as cause:
            raise CompactionFailed("failed", diagnostics=("Context limit: 8192",)) from cause
    except CompactionFailed as error:
        record = json.loads(generation_failure(error, "run-test", credentials=("configured-credential",)))
    detail = record["details"]
    assert "CompactionFailed" in detail and "Caused by:" in detail
    assert "HTTPStatusError" in detail and "HTTP status: 429" in detail
    assert "Provider code: insufficient_quota" in detail
    assert "Quota exhausted" in detail and "in upstream" in detail
    assert "Context limit: 8192" in detail
    assert all(secret not in detail for secret in ("request-credential", "query-credential", "configured-credential"))


def test_diagnostic_preserves_implicit_chain_and_all_frames():
    def deep(n):
        if n:
            deep(n - 1)
        else:
            raise TimeoutError("secret-token")

    try:
        try:
            deep(40)
        except TimeoutError:
            raise ValueError("another secret")
    except ValueError as error:
        detail = json.loads(generation_failure(error, "run-test"))["details"]
    assert "During handling of:" in detail
    assert "TimeoutError" in detail
    assert detail.count(" in deep") == 41
    assert "secret-token" not in detail and "another secret" not in detail


@pytest.mark.asyncio
async def test_streaming_http_error_body_available_to_diagnostics():
    from local_shell_mcp.webui.providers import check_image_response

    class ErrorStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error":{"code":"insufficient_quota","message":"Quota exhausted"}}'

    request = httpx.Request("POST", "https://example.invalid/v1")
    response = httpx.Response(429, request=request, stream=ErrorStream())
    with pytest.raises(httpx.HTTPStatusError) as error:
        await check_image_response(response)
    detail = json.loads(generation_failure(error.value, "run-test"))["details"]
    assert "Provider code: insufficient_quota" in detail
    assert "Provider message: Quota exhausted" in detail
