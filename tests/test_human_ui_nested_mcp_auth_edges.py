"""Nested-MCP UI actions must remain validated and scope-bound to LSM."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException

from local_shell_mcp import audit, dynamic_mcp, human_ui


class Request:
    def __init__(self, method: str, payload):
        self.method = method
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture
def mcp_control(monkeypatch, tmp_path):
    scopes = []
    invoked = []
    audited = []
    monkeypatch.setattr(human_ui, '_require_ui_scopes', lambda _request, *args: scopes.append(args))
    monkeypatch.setattr(human_ui, 'get_settings', lambda: SimpleNamespace(
        state_dir=tmp_path, max_timeout_s=60,
    ))

    class Manager:
        def __init__(self, directory, max_timeout_s):
            assert directory == tmp_path and max_timeout_s == 60

        async def manage(self, *, action, **kwargs):
            invoked.append((action, kwargs))
            return {'action': action, 'arguments': kwargs}

    monkeypatch.setattr(dynamic_mcp, 'DynamicMCPManager', Manager)
    monkeypatch.setattr(audit, 'audit', lambda event, **kwargs: audited.append((event, kwargs)))
    return scopes, invoked, audited


@pytest.mark.asyncio
async def test_nested_mcp_management_get_only_requires_read_scope(mcp_control):
    scopes, invoked, audited = mcp_control
    response = await human_ui.api_nested_mcp(Request('GET', None))
    assert response.status_code == 200
    assert invoked == [('list', {})]
    assert scopes == [('shell:read',)] and audited == []


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    None, [], {}, {'action': None}, {'action': 42},
    {'action': 'run_shell'}, {'action': 'register', 'untrusted': 'command'},
    {'action': 'remove', 'credential': 'must not pass through'},
])
async def test_nested_mcp_management_rejects_unapproved_actions_and_keys(mcp_control, payload):
    scopes, invoked, audited = mcp_control
    response = await human_ui.api_nested_mcp(Request('POST', payload))
    assert response.status_code in (400, 422)
    assert scopes == [('shell:read', 'shell:execute')]
    assert invoked == [] and audited == []


@pytest.mark.asyncio
async def test_nested_mcp_management_audits_only_authorized_post_actions(mcp_control):
    scopes, invoked, audited = mcp_control
    response = await human_ui.api_nested_mcp(Request('POST', {
        'action': 'register', 'name': 'evidence-server',
        'transport': 'stdio', 'command': 'python', 'args': ['-m', 'evidence'],
    }))
    assert response.status_code == 200
    assert invoked == [('register', {'name': 'evidence-server', 'transport': 'stdio',
                                      'command': 'python', 'args': ['-m', 'evidence']})]
    assert audited == [('nested_mcp_manage', {'action': 'register', 'name': 'evidence-server'})]
    assert scopes == [('shell:read', 'shell:execute')]


@pytest.mark.asyncio
@pytest.mark.parametrize('auth_kind,expiration', [
    ('none', None), ('local-cli', 2_000_000_000), ('oauth', 1_800_000_000),
])
async def test_webui_ticket_scopes_and_expiry_reflect_authenticated_native_grant(
        monkeypatch, tmp_path, auth_kind, expiration):
    from local_shell_mcp import auth as native_auth
    from local_shell_mcp.webui import auth as web_auth

    issued = []
    requested = []
    monkeypatch.setattr(human_ui, '_require_ui_scopes', lambda _request, *scopes: requested.append(scopes))
    monkeypatch.setattr(human_ui, 'get_settings', lambda: SimpleNamespace(
        state_backend='sqlite', state_dir=tmp_path, public_base_url=None,
    ))
    principal = SimpleNamespace(claims={'auth': auth_kind, 'exp': expiration})
    monkeypatch.setattr(human_ui, '_request_principal', lambda _request: principal)
    monkeypatch.setattr(human_ui, '_logical_session_subject',
                        lambda _request, create: 'authenticated-subject')
    monkeypatch.setattr(native_auth, 'principal_scopes', lambda _: frozenset({'shell:read'}))

    class Store:
        def __init__(self, directory):
            assert directory == tmp_path

        def issue_ticket(self, subject, scopes, until):
            issued.append((subject, scopes, until))
            return 'opaque-ticket'

    monkeypatch.setattr(web_auth, 'WebAuthStore', Store)
    request = SimpleNamespace(base_url='https://gui.example.invalid/')
    response = await human_ui.api_webui_ticket(request)
    assert response.status_code == 200
    assert json.loads(response.body)['data']['ticket'] == 'opaque-ticket'
    assert issued[0][0] == 'authenticated-subject'
    assert 'shell:read' in issued[0][1]
    assert requested == [('shell:read',)]
    if auth_kind == 'oauth':
        assert issued[0][1] == 'shell:read'
    else:
        assert len(issued[0][1].split()) >= 2
    assert issued[0][2] <= int(time.time()) + 3600


@pytest.mark.asyncio
async def test_webui_ticket_rejects_non_sqlite_and_unauthorized_access(monkeypatch, tmp_path):
    monkeypatch.setattr(human_ui, 'get_settings', lambda: SimpleNamespace(
        state_backend='other', state_dir=tmp_path,
    ))
    monkeypatch.setattr(human_ui, '_require_ui_scopes', lambda *_: None)
    result = await human_ui.api_webui_ticket(SimpleNamespace())
    assert result.status_code == 404

    def denied(*_args):
        raise HTTPException(status_code=403, detail='Missing authorized shell:read')

    monkeypatch.setattr(human_ui, '_require_ui_scopes', denied)
    result = await human_ui.api_webui_ticket(SimpleNamespace())
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_nested_mcp_denies_post_before_parsing_attacker_supplied_payload(monkeypatch):
    parsed = []

    async def attacker_payload():
        parsed.append(True)
        raise AssertionError('Payload must not be parsed before native authorization')

    monkeypatch.setattr(human_ui, '_require_ui_scopes', lambda *_: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail='Missing shell:execute')))
    request = SimpleNamespace(method='POST', json=attacker_payload)
    result = await human_ui.api_nested_mcp(request)
    assert result.status_code == 403 and parsed == []
