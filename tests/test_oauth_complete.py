from __future__ import annotations

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import jwt
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import local_shell_mcp.oauth as oauth
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch, **env):
    values = {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(tmp_path),
        "LOCAL_SHELL_MCP_STATE_DIR": str(tmp_path / ".state"),
        "LOCAL_SHELL_MCP_AUTH_MODE": "oauth",
        "LOCAL_SHELL_MCP_OAUTH_JWT_SECRET": "oauth-test-secret-that-is-more-than-32-bytes",
        "LOCAL_SHELL_MCP_PUBLIC_BASE_URL": "http://testserver",
        "LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN": "correct-admin-pin",
    }
    values.update({key: str(value) for key, value in env.items()})
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    oauth._CLIENTS.clear()
    oauth._CODES.clear()


def _app() -> Starlette:
    return Starlette(
        routes=[
            Route("/.well-known/oauth-protected-resource", oauth.oauth_protected_resource),
            Route("/.well-known/oauth-authorization-server", oauth.oauth_server_metadata),
            Route("/oauth/register", oauth.oauth_register, methods=["POST"]),
            Route("/oauth/authorize", oauth.oauth_authorize_get, methods=["GET"]),
            Route("/oauth/authorize", oauth.oauth_authorize_post, methods=["POST"]),
            Route("/oauth/token", oauth.oauth_token, methods=["POST"]),
        ]
    )


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _register(client: TestClient, redirect: str = "https://client.test/callback") -> str:
    response = client.post(
        "/oauth/register",
        json={"client_name": "test client", "redirect_uris": [redirect]},
    )
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


def test_metadata_and_forwarded_base_urls(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(_app(), base_url="http://internal")

    protected = client.get("/.well-known/oauth-protected-resource")
    server = client.get("/.well-known/oauth-authorization-server")

    assert protected.headers["cache-control"] == "no-store"
    assert protected.json()["resource"] == "http://testserver"
    assert server.json()["issuer"] == "http://testserver"
    assert server.json()["authorization_endpoint"].endswith("/oauth/authorize")
    assert "S256" in server.json()["code_challenge_methods_supported"]

    monkeypatch.delenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL")
    get_settings.cache_clear()
    forwarded = TestClient(_app(), base_url="http://internal").get(
        "/.well-known/oauth-protected-resource",
        headers={"x-forwarded-proto": "wss", "x-forwarded-host": "public.test"},
    )
    assert forwarded.json()["resource"] == "https://public.test"


def test_registration_rejects_every_invalid_shape(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(_app())

    assert client.post("/oauth/register", content=b"not-json").status_code == 400
    for redirects in (None, [], ["https://x.test"] * (oauth.MAX_REDIRECT_URIS + 1), "bad"):
        body = {} if redirects is None else {"redirect_uris": redirects}
        response = client.post("/oauth/register", json=body)
        assert response.status_code == 400
    assert client.post("/oauth/register", json={"redirect_uris": [123]}).status_code == 400

    invalid_uris = [
        "",
        "relative/path",
        "https://client.test/cb#fragment",
        "http:///missing-host",
        "x" * (oauth.MAX_OAUTH_URI_LENGTH + 1),
    ]
    for uri in invalid_uris:
        response = client.post("/oauth/register", json={"redirect_uris": [uri]})
        assert response.status_code == 400, uri

    response = client.post(
        "/oauth/register",
        json={
            "client_name": "x" * (oauth.MAX_CLIENT_NAME_LENGTH + 1),
            "redirect_uris": ["https://client.test/cb"],
        },
    )
    assert response.status_code == 400

    monkeypatch.setattr(oauth, "MAX_OAUTH_CLIENTS", 0)
    assert client.post(
        "/oauth/register", json={"redirect_uris": ["https://client.test/cb"]}
    ).status_code == 503


def test_registered_clients_survive_memory_reset(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(_app())
    redirect = "https://client.test/persistent-callback"
    client_id = _register(client, redirect)
    store_path = get_settings().state_dir / oauth.OAUTH_CLIENT_STORE_FILE_NAME

    assert store_path.exists()
    oauth._CLIENTS.clear()

    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
        },
    )

    assert "Unknown client_id" not in response.text
    assert client_id in oauth._CLIENTS


def test_v2_client_id_is_migrated_after_pin_approval(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(_app())
    client_id = "local-shell-mcp-" + "v2LegacyClientId_1234567890abcd"
    redirect = "https://client.test/v2-callback"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
    }

    invalid_redirect = client.get(
        "/oauth/authorize",
        params={**params, "redirect_uri": "relative/callback"},
    )
    assert "redirect_uri must be absolute" in invalid_redirect.text

    form = client.get("/oauth/authorize", params=params)
    assert "Unknown client_id" not in form.text
    assert client_id not in oauth._CLIENTS

    rejected = client.post("/oauth/authorize", data={**params, "pin": "wrong"})
    assert "Invalid admin PIN" in rejected.text
    assert client_id not in oauth._CLIENTS

    approved = client.post(
        "/oauth/authorize",
        data={**params, "pin": "correct-admin-pin"},
        follow_redirects=False,
    )
    assert approved.status_code == 302
    assert client_id in oauth._CLIENTS

    oauth._CLIENTS.clear()
    reloaded = client.get("/oauth/authorize", params=params)
    assert "Unknown client_id" not in reloaded.text
    assert client_id in oauth._CLIENTS


def test_authorize_validation_and_pin_failures(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(_app())
    client_id = _register(client)
    base = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "https://client.test/callback",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
    }

    cases = [
        ({**base, "response_type": "token"}, "Only response_type=code"),
        ({key: value for key, value in base.items() if key != "client_id"}, "Missing client_id"),
        ({key: value for key, value in base.items() if key != "redirect_uri"}, "Missing redirect_uri"),
        ({**base, "client_id": "missing"}, "Unknown client_id"),
        ({**base, "redirect_uri": "https://other.test/cb"}, "not registered"),
        ({key: value for key, value in base.items() if key != "code_challenge"}, "Missing code_challenge"),
        ({**base, "code_challenge_method": "plain"}, "Only code_challenge_method=S256"),
    ]
    for params, message in cases:
        response = client.get("/oauth/authorize", params=params)
        assert response.status_code == 200
        assert message in response.text

    invalid_post = client.post("/oauth/authorize", data={"client_id": "missing"})
    assert "Only response_type=code" in invalid_post.text

    ignored_scope = client.get(
        "/oauth/authorize",
        params={**base, "scope": "shell:read git:write unknown:scope"},
    )
    assert "Unsupported OAuth scope" not in ignored_scope.text
    assert oauth._scope_value() in ignored_scope.text

    wrong_pin = client.post("/oauth/authorize", data={**base, "pin": "wrong"})
    assert wrong_pin.status_code == 200
    assert "Invalid admin PIN" in wrong_pin.text
    assert not oauth._CODES


def test_complete_authorization_code_flow_and_token_failures(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S=120,
        LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S=30,
    )
    client = TestClient(_app())
    redirect = "https://client.test/callback?existing=1"
    client_id = _register(client, redirect)
    verifier = "verifier-with-enough-entropy"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "scope": "shell:read shell:execute",
        "resource": "http://testserver",
        "state": "opaque-state",
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
        "pin": "correct-admin-pin",
    }

    approved = client.post("/oauth/authorize", data=params, follow_redirects=False)
    assert approved.status_code == 302
    parsed = urlsplit(approved.headers["location"])
    query = parse_qs(parsed.query)
    code = query["code"][0]
    assert query["state"] == ["opaque-state"]
    assert query["iss"] == ["http://testserver"]
    assert "existing=1" in parsed.query

    unsupported = client.post("/oauth/token", data={"grant_type": "password"})
    assert unsupported.json()["error"] == "unsupported_grant_type"
    unknown = client.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": "missing"},
    )
    assert unknown.json()["error"] == "invalid_grant"

    mismatch = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "wrong",
            "redirect_uri": redirect,
            "code_verifier": verifier,
        },
    )
    assert "mismatch" in mismatch.json()["error_description"]

    bad_pkce = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_verifier": "wrong",
        },
    )
    assert "PKCE" in bad_pkce.json()["error_description"]

    token_response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_verifier": verifier,
        },
    )
    assert token_response.status_code == 200
    body = token_response.json()
    assert body["expires_in"] == 120
    claims = jwt.decode(
        body["access_token"],
        "oauth-test-secret-that-is-more-than-32-bytes",
        algorithms=["HS256"],
        audience="http://testserver",
        issuer="http://testserver",
    )
    assert claims["client_id"] == client_id
    assert claims["scope"] == oauth._scope_value()
    assert body["scope"] == oauth._scope_value()
    assert claims["exp"] > claims["iat"]

    reused = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_verifier": verifier,
        },
    )
    assert reused.json()["error"] == "invalid_grant"


def test_expired_code_capacity_pruning_and_pkce_variants(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S=1)
    client = TestClient(_app())
    client_id = _register(client)

    expired = oauth.AuthCode(
        code="expired",
        client_id=client_id,
        redirect_uri="https://client.test/callback",
        scope="shell:read",
        resource="http://testserver",
        code_challenge=None,
        code_challenge_method=None,
        created_at=int(time.time()) - 100,
    )
    oauth._CODES[expired.code] = expired
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": expired.code,
            "client_id": client_id,
            "redirect_uri": expired.redirect_uri,
        },
    )
    assert response.json()["error"] == "invalid_grant"

    oauth._CODES.clear()
    oauth._CODES["used"] = oauth.AuthCode(
        code="used",
        client_id=client_id,
        redirect_uri="https://client.test/callback",
        scope="shell:read",
        resource="http://testserver",
        code_challenge=None,
        code_challenge_method=None,
        used=True,
    )
    oauth._CLIENTS["old"] = oauth.OAuthClient(
        client_id="old",
        redirect_uris=["https://old.test/cb"],
        created_at=0,
    )
    monkeypatch.setattr(oauth, "MAX_OAUTH_CODES", 2)
    for index in range(4):
        oauth._CODES[str(index)] = oauth.AuthCode(
            code=str(index),
            client_id=client_id,
            redirect_uri="https://client.test/callback",
            scope="shell:read",
            resource="http://testserver",
            code_challenge=None,
            code_challenge_method=None,
            created_at=100 + index,
        )
    oauth._prune_oauth_state(now=100_000)
    assert "used" not in oauth._CODES
    assert "old" in oauth._CLIENTS

    for index in range(4):
        oauth._CODES[str(index)] = oauth.AuthCode(
            code=str(index),
            client_id=client_id,
            redirect_uri="https://client.test/callback",
            scope="shell:read",
            resource="http://testserver",
            code_challenge=None,
            code_challenge_method=None,
            created_at=100_000,
        )
    oauth._prune_oauth_state(now=100_000)
    assert len(oauth._CODES) <= 2

    assert oauth._verify_pkce(expired, None) is True
    plain = oauth.AuthCode(
        code="plain",
        client_id="c",
        redirect_uri="https://x.test",
        scope="",
        resource="",
        code_challenge="secret",
        code_challenge_method="plain",
    )
    assert oauth._verify_pkce(plain, None) is False
    assert oauth._verify_pkce(plain, "secret") is True
    assert oauth._verify_pkce(plain, "other") is False


def test_authorization_capacity_error_and_no_pin_hint(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "")
    get_settings.cache_clear()
    client = TestClient(_app())
    client_id = _register(client)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "https://client.test/callback",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
    }
    form = client.get("/oauth/authorize", params=params)
    assert "No admin PIN is configured" in form.text

    monkeypatch.setattr(oauth, "MAX_OAUTH_CODES", 0)
    response = client.post("/oauth/authorize", data=params)
    assert "Too many pending authorization requests" in response.text
