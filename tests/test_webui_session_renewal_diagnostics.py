"""WebUI session renewal, grant revocation and safe generation errors."""

import json
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException

from local_shell_mcp.webui import auth, generation_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
from local_shell_mcp.webui.error_diagnostics import generation_failure


def test_activity_slides_browser_session_without_reviving_logout(tmp_path, monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(auth.time, 'time', lambda: now)
    store = auth.WebAuthStore(tmp_path)
    cookie, _ = store.redeem(store.issue_ticket('alice', 'shell:read', now + 86400, renewable=True))

    monkeypatch.setattr(auth.time, 'time', lambda: now + 3600)
    renewed = store.renew(cookie)
    assert renewed is not None
    assert renewed.grant_until == now + 3600 + auth.SESSION_TTL
    monkeypatch.setattr(auth.time, 'time', lambda: now + auth.SESSION_TTL + 1)
    assert store.session(cookie) is not None
    store.revoke(cookie)
    assert store.session(cookie) is None
    assert store.renew(cookie) is None


def test_legacy_sqlite_login_tables_migrate_without_extending_old_grants(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / 'lsm.sqlite3'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE web_sessions (hash TEXT PRIMARY KEY, owner TEXT NOT NULL, '
                   'scopes TEXT NOT NULL, grant_until INTEGER NOT NULL, expires_at INTEGER NOT NULL, '
                   'created_at INTEGER NOT NULL DEFAULT (unixepoch()))')
        db.execute('CREATE TABLE web_login_tickets (hash TEXT PRIMARY KEY, owner TEXT NOT NULL, '
                   'scopes TEXT NOT NULL, grant_until INTEGER NOT NULL, expires_at INTEGER NOT NULL)')
    now = 1_800_000_000
    monkeypatch.setattr(auth.time, 'time', lambda: now)
    from local_shell_mcp.sqlite_store import shared_database
    database = shared_database(tmp_path)
    with database.connect() as db:
        assert 'renewable' in [r['name'] for r in db.execute('PRAGMA table_info(web_sessions)')]
        assert 'renewable' in [r['name'] for r in db.execute('PRAGMA table_info(web_login_tickets)')]
    store = auth.WebAuthStore(tmp_path)
    cookie, _ = store.redeem(store.issue_ticket('alice', 'shell:read', now + 90))
    assert store.renew(cookie).grant_until == now + 90


def test_expired_browser_session_cannot_renew(tmp_path, monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(auth.time, 'time', lambda: now)
    store = auth.WebAuthStore(tmp_path)
    cookie, _ = store.redeem(store.issue_ticket('alice', 'shell:read', now + 120))
    monkeypatch.setattr(auth.time, 'time', lambda: now + 120)
    assert store.renew(cookie) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("client_name,approved,redirects,renewable", [
    ("WebUI", True, ["https://lsm.example.test/auth/login"], True),
    ("External API", True, ["https://lsm.example.test/auth/login"], False),
    ("WebUI", False, ["https://lsm.example.test/auth/login"], False),
    ("WebUI", True, ["https://other.example.test/auth/login"], False),
    ("WebUI", True, ["https://lsm.example.test/auth/login", "https://other.example.test/callback"], False),
])
async def test_first_party_oauth_ticket_is_renewable_after_short_bearer(
    tmp_path, monkeypatch, client_name, approved, redirects, renewable,
):
    import httpx
    from starlette.applications import Starlette

    from local_shell_mcp import oauth
    from local_shell_mcp import settings as settings_module

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "oauth", "MODE": "http", "PUBLIC_BASE_URL": "https://lsm.example.test",
        "OAUTH_ACCESS_TOKEN_TTL_S": "80",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    settings_module.get_settings.cache_clear()
    monkeypatch.setattr(oauth, "_get_client", lambda client_id: oauth.OAuthClient(
        client_id=client_id, client_name=client_name, approved=approved,
        redirect_uris=redirects,
    ))
    from local_shell_mcp import auth as controller_auth
    monkeypatch.setattr(controller_auth, '_verify_oauth', lambda request, settings: SimpleNamespace(
        subject='alice', claims={'client_id': 'oauth-browser', 'scope': 'shell:read',
                                 'exp': int(auth.time.time()) + 80},
    ))
    app = Starlette(routes=auth.auth_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url='https://lsm.example.test', follow_redirects=False) as client:
        issued = await client.post('/api/ui/webui-ticket', headers={'Authorization': 'Bearer TEST_PROOF'})
        assert issued.status_code == 200
        login = await client.post('/api/auth/lsm', data={'ticket': issued.json()['ticket']})
        assert login.status_code == 303
        token = await client.post('/api/auth/refresh')
        assert token.status_code == 200
        import jwt
        claims = jwt.decode(token.json()['token'], options={'verify_signature': False})
        assert auth.time.time() < claims['exp'] <= auth.time.time() + 80
        cookie = client.cookies[auth.COOKIE]
        session = auth._store().session(cookie)
        if renewable:
            assert session.grant_until > auth.time.time() + 29 * 86400
        else:
            assert session.grant_until <= auth.time.time() + 80
    settings_module.get_settings.cache_clear()


def test_bounded_session_does_not_slide_or_extend_oauth_grant(tmp_path, monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(auth.time, 'time', lambda: now)
    store = auth.WebAuthStore(tmp_path)
    cookie, _ = store.redeem(store.issue_ticket('alice', 'shell:read', now + 300))
    monkeypatch.setattr(auth.time, 'time', lambda: now + 100)
    assert store.renew(cookie).grant_until == now + 300
    monkeypatch.setattr(auth.time, 'time', lambda: now + 301)
    assert store.renew(cookie) is None


def test_webui_grants_are_cookie_bound_and_external_bearers_stay_bounded(tmp_path, monkeypatch):
    from local_shell_mcp import settings as settings_module

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'oauth')
    settings_module.get_settings.cache_clear()
    now = int(auth.time.time())
    store = auth.WebAuthStore(settings_module.get_settings().state_dir)
    cookie, _ = store.redeem(store.issue_ticket('alice', 'shell:read', now + 3600, renewable=True))
    user = SimpleNamespace(subject='alice', claims={
        'client_id': 'lsm-webui', 'scope': 'shell:read', 'exp': now + 15,
    })
    request = SimpleNamespace(state=SimpleNamespace(principal=user), cookies={auth.COOKIE: cookie})
    assert generation_routes._request_grant(request) == ({'shell:read'}, now + 3600)

    # No cookie, another person's cookie, or excess bearer scopes must not
    # inherit the browser session. Independent OAuth clients keep token expiry.
    request.cookies = {}
    with pytest.raises(HTTPException) as missing:
        generation_routes._request_grant(request)
    assert missing.value.status_code == 401
    request.cookies = {auth.COOKIE: cookie}
    user.subject = 'bob'
    with pytest.raises(HTTPException):
        generation_routes._request_grant(request)
    user.subject = 'alice'
    user.claims['scope'] = 'shell:read shell:write'
    with pytest.raises(HTTPException):
        generation_routes._request_grant(request)
    user.claims['scope'] = 'shell:read'
    user.claims['client_id'] = 'other-client'
    assert generation_routes._request_grant(request)[1] == now + 15

    user.claims['client_id'] = 'lsm-webui'
    runner = object.__new__(AgentRunner)
    runner.owner = 'alice'
    runner.scopes = {'shell:read'}
    runner.webui_cookie = cookie
    runner.grant_expires = now + 15  # The original short-lived bearer.
    runner.actor_lease = None
    runner.task_control_host = None
    runner.wakeup_lease = None
    runner.event_delivery_lease = None
    # A still-active browser run outlives its original bearer expiry.
    monkeypatch.setattr(auth.time, 'time', lambda: now + 16)
    runner._check_grant()
    assert runner.grant_expires == now + 3600
    store.revoke(cookie)
    with pytest.raises(RuntimeSafetyError, match='signed out'):
        runner._check_grant()
    settings_module.get_settings.cache_clear()


def test_diagnostics_include_stack_and_reason_without_secret_leaks():
    try:
        raise RuntimeSafetyError('Authorization rejected: Bearer MY_PRIVATE_ACCESS_TOKEN')
    except RuntimeSafetyError as exc:
        record = json.loads(generation_failure(exc, 'run_test'))
    assert record['type'] == 'lsm_generation_error'
    assert record['runId'] == 'run_test'
    assert record['exception'] == 'RuntimeSafetyError'
    assert 'Stack' in record['details']
    assert 'test_diagnostics_include_stack' in record['details']
    assert 'MY_PRIVATE_ACCESS_TOKEN' not in json.dumps(record)
    assert 'lsm_generation_error' not in record['message']

    assert 'Sign in again' in json.loads(generation_failure(
        RuntimeSafetyError('Authentication grant expired'), 'run_test'))['message']
