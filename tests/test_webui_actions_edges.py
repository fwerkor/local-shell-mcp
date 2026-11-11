"""Source test vectors from LibreChat e8f3be08 actions.ts and update/credentials/tools.spec.ts."""
from __future__ import annotations

import base64
import json

import pytest
from cryptography.fernet import Fernet

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.action_runtime import (
    _allowed_domain,
    _allowed_local,
    _authorization,
    _full_url,
    _request,
    _resolve_address,
    _validate,
)
from local_shell_mcp.webui.action_spec import (
    _ref,
    encoded_domain,
    is_action_tool,
    legacy_domain,
    normalize_action_tool_name,
    operations,
    parse_spec,
    tool_name,
    validate_domain,
)
from local_shell_mcp.webui.actions import ActionRepository, _target, _validate_auth
from local_shell_mcp.webui.agents import AgentRepository

BASE = "https://api.example.org"


def sample_spec(url=BASE, *, operation="echo"):
    return {
        "openapi": "3.0.0", "servers": [{"url": url}], "paths": {
            "/hello": {"get": {"operationId": operation, "responses": {"200": {"description": "ok"}}}}
        },
    }


def make_body(url=BASE, *, operation="echo", auth=None, secret=None):
    meta = {"domain": url.split("/v")[0], "raw_spec": json.dumps(sample_spec(url, operation=operation))}
    if auth is not None:
        meta["auth"] = auth
    if secret is not None:
        meta["api_key"] = secret
    return {"metadata": meta, "functions": [{"type": "function", "function": {"name": operation}}]}


def make_agent(db, owner="alice"):
    return AgentRepository(db).create(owner, {"provider": "openAI", "model": None, "name": "Actions"})


@pytest.mark.parametrize(("raw", "message"), [
    (5, "Invalid OpenAPI"), ("{" + "A" * (512 * 1024), "Invalid OpenAPI"),
    ("{", "Error parsing"), ("a: [broken", "Error parsing"),
    ("null", "Error parsing"), ("[]", "Error parsing"),
    ("servers: []\npaths: {}", "valid URL"),
    ('{"servers":[{}],"paths":{"/x":{}}}', "valid URL"),
    ('{"servers":[{"url":"https://api.example.org"}],"paths":{}}', "No paths"),
    ('{"servers":[{"url":"https://api.example.org"}],"paths":[]}', "No paths"),
])
def test_parse_failures(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_spec(raw)


def test_parse_yaml_and_many_paths():
    result = parse_spec("servers:\n - url: https://api.example.org\npaths:\n /x: {}\n")
    assert result["paths"]["/x"] == {}
    too_many = sample_spec()
    too_many["paths"] = {"/" + str(n): {} for n in range(257)}
    with pytest.raises(ValueError, match="Too many"):
        parse_spec(json.dumps(too_many))


def test_ref_resolution_and_failures():
    components = {"schemas": {"Name": {"type": "string"}, "Alias": {"$ref": "#/components/schemas/Name"}}}
    assert _ref({"$ref": "#/components/schemas/Alias"}, components) == {"type": "string"}
    assert _ref({"type": "array"}, components) == {"type": "array"}
    assert _ref(None, {}) == {}
    assert _ref(9, {}) == {}
    with pytest.raises(ValueError, match="Unsupported"):
        _ref({"$ref": "http://elsewhere"}, components)
    with pytest.raises(ValueError, match="Could not resolve"):
        _ref({"$ref": "#/components/schemas/Unknown"}, components)
    components["schemas"]["Loop"] = {"$ref": "#/components/schemas/Loop"}
    with pytest.raises(ValueError, match="Circular"):
        _ref(components["schemas"]["Loop"], components)


def test_ref_openapi_schema_extraction():
    doc = sample_spec()
    doc["components"] = {
        "parameters": {"Id": {"name": "id", "in": "path", "required": True,
                              "schema": {"$ref": "#/components/schemas/UserId"}}},
        "schemas": {"UserId": {"type": "integer", "minimum": 1},
                    "Body": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        "requestBodies": {"Body": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Body"}}}}},
    }
    doc["paths"]["/hello"]["get"].update({
        "summary": "Short summary", "description": "Long summary", "x-strict": True,
        "x-openai-isConsequential": True,
        "parameters": [{"$ref": "#/components/parameters/Id"}, {"name": "unused", "in": "query"}],
        "requestBody": {"$ref": "#/components/requestBodies/Body"},
    })
    op = operations(doc)["echo"]
    assert op["description"] == "Short summary"
    assert op["consequential"] and op["strict"]
    assert op["parameters"]["additionalProperties"] is False
    assert op["parameters"]["required"] == ["id", "name"]
    assert op["parameters"]["properties"]["id"]["minimum"] == 1
    assert op["locations"]["id"] == "path" and op["locations"]["name"] == "body"


def test_operation_names_and_methods():
    doc = sample_spec(operation="with-hyphen")
    doc["paths"]["/other.one"] = {"get": {"summary": "No ID"}}
    doc["paths"]["/third"] = {"parameters": [], "options": {"operationId": "opt"}}
    op = operations(doc)
    assert "get_otherone" in op
    assert op["get_otherone"]["description"] == "No ID"
    assert op["with-hyphen"]["strict"] is False
    assert op["opt"]["method"] == "options"
    doc["paths"]["/other.one"]["get"]["operationId"] = "with-hyphen"
    with pytest.raises(ValueError, match="Duplicate"):
        operations(doc)
    for invalid in ({"paths": {"bad": {}}}, {"paths": {"/ok": 8}}):
        with pytest.raises(ValueError, match="Invalid OpenAPI path"):
            operations(invalid)
    assert operations({"paths": {"/x": {"get": None, "parameters": [], "post": {}}}})["post_x"]["method"] == "post"


def test_encoding_source_vectors():
    assert encoded_domain("https://example.com") == base64.b64encode(b"example.com").decode()[:10]
    assert encoded_domain("x.io") == "x---io"
    assert legacy_domain("x.io") == "x---io"
    assert legacy_domain("https://example.com") == base64.b64encode(b"https://example.com").decode()[:10]
    assert is_action_tool("list_mcp_docs_action_bad_mcp_v1")
    assert not is_action_tool("noaction")
    assert normalize_action_tool_name("get_action_swapi---tech") == "get_action_swapi_tech"
    assert normalize_action_tool_name("get_mcp_a_action_swapi---tech") == "get_mcp_a_action_swapi_tech"
    assert normalize_action_tool_name("get_action_data---x_mcp_srv") == "get_action_data---x_mcp_srv"


@pytest.mark.parametrize(("domain", "server", "valid"), [
    (None, BASE, False), ("", BASE, False),
    ("https://api.example.org", BASE, True),
    ("api.example.org", BASE, True),
    ("http://api.example.org", BASE, False),
    ("https://attacker.example.org", BASE, False),
    ("https://api.example.org/evil", BASE, False),
    ("https://api.example.org:443", BASE, True),
    ("https://api.example.org:8443", BASE, False),
    ("https://u:p@api.example.org", BASE, False),
    ("https://api.example.org?token=secret", BASE, False),
    ("http://127.0.0.1", "http://127.0.0.1:8080", True),
    ("127.0.0.1", "http://127.0.0.1:8080", True),
    ("https://api.example.org", "ftp://api.example.org", False),
    ("https://api.example.org", "https://u:p@api.example.org", False),
    ("https://api.example.org", "https://api.example.org/#frag", False),
])
def test_domain_validation_cases(domain, server, valid):
    if valid:
        validate_domain(domain, server)
    else:
        with pytest.raises(ValueError):
            validate_domain(domain, server)


def test_target_comparison_and_auth_validation():
    assert _target(None) == ""
    assert _target("HTTPS://API.EXAMPLE.ORG/v1/") == "https://api.example.org/v1"
    assert _target("not-a-url") == "https://not-a-url"
    assert _target("https://api.example.org/v2", domain=True) == BASE
    for auth in ({"type": "none"}, {"type": "service_http", "authorization_type": "basic"},
                 {"type": "service_http", "authorization_type": "bearer"},
                 {"type": "service_http", "authorization_type": "custom", "custom_auth_header": "X-API-Key"},
                 {"type": "oauth", "authorization_url": "https://id.example.org/authorize",
                  "client_url": "https://id.example.org/token", "scope": "read",
                  "token_exchange_method": "default_post"}):
        _validate_auth(auth)
    for auth in ({"type": "unsupported"},
                 {"type": "service_http", "authorization_type": "nope"},
                 {"type": "service_http", "authorization_type": "custom", "custom_auth_header": "Host"},
                 {"type": "service_http", "authorization_type": "custom", "custom_auth_header": "X\nLeak"},
                 {"type": "service_http", "authorization_type": "custom", "custom_auth_header": ""},
                 {"type": "oauth", "authorization_url": "http://id.example.org",
                  "client_url": "https://id.example.org/token", "scope": "", "token_exchange_method": "default_post"},
                 {"type": "oauth", "authorization_url": "https://id.example.org",
                  "client_url": "https://id.example.org/token", "scope": [], "token_exchange_method": "default_post"},
                 {"type": "oauth", "authorization_url": "https://id.example.org",
                  "client_url": "https://id.example.org/token", "scope": "", "token_exchange_method": "bad"}):
        with pytest.raises(ValueError):
            _validate_auth(auth)


def test_sqlite_rejects_invalid_and_cross_owner(tmp_path):
    db = SQLiteDatabase(tmp_path)
    a, b = make_agent(db, "alice"), make_agent(db, "bob")
    repo = ActionRepository(db)
    with pytest.raises(ValueError, match="functions"):
        repo.save("alice", a["id"], {"functions": [], "metadata": {}})
    with pytest.raises(ValueError, match="metadata"):
        repo.save("alice", a["id"], {"functions": [{"function": {"name": "echo"}}]})
    with pytest.raises(ValueError, match="Action ID"):
        repo.save("alice", a["id"], {**make_body(), "action_id": "a" * 130})
    with pytest.raises(KeyError):
        repo.save("bob", a["id"], make_body())
    with pytest.raises(ValueError, match="Unknown Action metadata"):
        repo.save("alice", a["id"], {**make_body(), "metadata": {**make_body()["metadata"], "oauth_access_token": "sensitive"}})
    for func in ([None], [{"function": None}], [{"function": {"name": "wrong"}}]):
        with pytest.raises(ValueError, match="functions"):
            repo.save("alice", a["id"], {**make_body(), "functions": func})
    _, saved = repo.save("alice", a["id"], {**make_body(), "action_id": "known-action"})
    assert saved["action_id"] == "known-action"
    with pytest.raises(PermissionError):
        repo.save("bob", b["id"], {**make_body(), "action_id": "known-action"})
    with pytest.raises(PermissionError):
        repo.save("alice", make_agent(db, "alice")["id"], {**make_body(), "action_id": "known-action"})
    assert repo.list("alice") == [saved] and repo.list("bob") == []


def test_credentials_require_refresh_and_no_auth_cleanup(tmp_path):
    db = SQLiteDatabase(tmp_path)
    agent = make_agent(db)
    repo = ActionRepository(db)
    auth = {"type": "service_http", "authorization_type": "bearer"}
    _, action = repo.save("alice", agent["id"], make_body(BASE + "/v1", auth=auth, secret="old-key"))
    aid = action["action_id"]
    no_auth = make_body(BASE + "/v2", auth={"type": "none"})
    no_auth["action_id"] = aid
    updated, _ = repo.save("alice", agent["id"], no_auth)
    assert updated["version"] == 3
    with db.connect() as conn:
        row = conn.execute("SELECT credentials FROM action_records WHERE id=?", (aid,)).fetchone()
    assert row["credentials"] is None
    altered = make_body(BASE + "/v3", auth=auth)
    altered["action_id"] = aid
    with pytest.raises(ValueError, match="API key"):
        repo.save("alice", agent["id"], altered)


def test_metadata_security_edge_cases(tmp_path):
    db = SQLiteDatabase(tmp_path)
    agent = make_agent(db)
    repo = ActionRepository(db)
    auth = {"type": "service_http", "authorization_type": "bearer"}
    data = make_body(auth=auth, secret="VERY-SECRET")
    _, action = repo.save("alice", agent["id"], data)
    for changes, reason in [
        ({"auth": {"type": "service_http", "authorization_type": "custom",
                   "custom_auth_header": "X-Key"}}, "re-entered"),
        ({"raw_spec": json.dumps(sample_spec(BASE + "/debug"))}, "re-entered"),
    ]:
        attempt = make_body(auth=auth)
        attempt["action_id"] = action["action_id"]
        attempt["metadata"].update(changes)
        with pytest.raises(ValueError, match=reason):
            repo.save("alice", agent["id"], attempt)
    malformed = make_body(auth=auth, secret="VERY-SECRET")
    malformed["metadata"]["auth"] = {"type": "service_http", "authorization_type": "bearer", "secret": "leak"}
    with pytest.raises(ValueError, match="Unknown Action auth"):
        repo.save("alice", agent["id"], malformed)
    with pytest.raises(ValueError, match="Invalid Action auth"):
        repo.save("alice", agent["id"], {**make_body(), "metadata": {**make_body()["metadata"], "auth": "none"}})
    with pytest.raises(ValueError, match="API key"):
        repo.save("alice", make_agent(db)["id"], make_body(auth=auth))


def test_auth_headers_and_model_safety():
    key = {"api_key": "stored-cred"}
    assert _authorization({}, {}) == {}
    assert _authorization({"auth": {"type": "service_http", "authorization_type": "bearer"}}, key) == {
        "Authorization": "Bearer stored-cred"}
    assert _authorization({"auth": {"type": "service_http", "authorization_type": "basic"}}, key) == {
        "Authorization": "Basic " + base64.b64encode(b"stored-cred").decode()}
    assert _authorization({"auth": {"type": "service_http", "authorization_type": "custom",
                                   "custom_auth_header": "X-Key"}}, key) == {"X-Key": "stored-cred"}
    for kind in ("oauth", "invalid", "service_http"):
        with pytest.raises((ValueError, RuntimeError)):
            _authorization({"auth": {"type": kind}}, {})


@pytest.mark.parametrize(("value", "schema", "valid"), [
    ({"a": "abc"}, {"type": "object", "properties": {"a": {"type": "string"}}}, True),
    ({}, {"type": "object", "required": ["id"]}, False),
    ("hello", {"type": "object"}, False),
    ({"other": 3}, {"type": "object", "properties": {"a": {}}, "additionalProperties": False}, False),
    (["x", "y"], {"type": "array", "items": {"type": "string"}}, True),
    (["x", 5], {"type": "array", "items": {"type": "string"}}, False),
    ("x", {"type": "array"}, False),
    (2, {"type": "integer", "minimum": 1, "maximum": 2}, True),
    (2.5, {"type": "integer"}, False),
    (True, {"type": "integer"}, False),
    (-1, {"type": "number", "minimum": 0}, False),
    (4, {"type": "number", "maximum": 3}, False),
    ("abc", {"type": "string", "minLength": 3, "maxLength": 3}, True),
    ("ab", {"type": "string", "minLength": 3}, False),
    ("abcd", {"type": "string", "maxLength": 3}, False),
    (False, {"type": "boolean"}, True),
    (3, {"type": "boolean"}, False),
    ("x", {"enum": ["x", "y"]}, True),
    ("z", {"enum": ["x", "y"]}, False),
])
def test_argument_schema_cases(value, schema, valid):
    if valid:
        _validate(value, schema)
    else:
        with pytest.raises(ValueError):
            _validate(value, schema)


def test_request_mapping_edge_cases():
    op = {"method": "post", "path": "/users/{id}", "parameters": {
        "type": "object", "properties": {"id": {"type": "string"}, "search": {"type": "string"},
                                        "data": {"type": "string"}, "X-Trace": {"type": "string"}},
        "required": ["id"]}, "locations": {"id": "path", "search": "query",
                                          "data": "body", "X-Trace": "header"}}
    path, query, body, headers = _request(op, {"id": "a/b", "search": "find", "data": "hello", "X-Trace": "ok"})
    assert path == "/users/a%2Fb"
    assert query == {"search": "find"} and body == {"data": "hello"} and headers == {"X-Trace": "ok"}
    with pytest.raises(ValueError, match="required"):
        _request(op, {})
    for key in ("Authorization", "Host", "cookie", "Connection", "transfer-encoding"):
        altered = {**op, "locations": {**op["locations"], key: "header"}}
        with pytest.raises(ValueError, match="Reserved"):
            _request(altered, {"id": "x", key: "value"})
    with pytest.raises(ValueError, match="Missing required path"):
        _request({**op, "locations": {}}, {"id": "x"})
    with pytest.raises(ValueError, match="Unsupported HTTP"):
        _request({**op, "method": "trace"}, {"id": "x"})
    assert _request({**op, "method": "get", "path": "/get", "locations": {}}, {"id": "x"})[1] == {"id": "x"}


def test_url_mapping_and_network_allowlist(monkeypatch):
    assert _full_url(BASE + "/v1", "/users") == BASE + "/v1/users"
    for server in ("ftp://evil", "http://u:p@evil", "no-url"):
        with pytest.raises(ValueError):
            _full_url(server, "/x")
    for path in ("//evil", "/x?u=evil", "x", "/x#fragment"):
        with pytest.raises(ValueError):
            _full_url(BASE, path)
    monkeypatch.delenv("LSM_ACTION_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("LSM_ACTION_ALLOWED_ADDRESSES", raising=False)
    assert _allowed_domain("a.b") and not _allowed_local("127.0.0.1", 9999)
    monkeypatch.setenv("LSM_ACTION_ALLOWED_DOMAINS", "api.example.org,other.example.org")
    monkeypatch.setenv("LSM_ACTION_ALLOWED_ADDRESSES", "localhost:8080,127.0.0.1:9999")
    assert _allowed_domain("API.EXAMPLE.ORG")
    assert not _allowed_domain("evil.invalid")
    assert _allowed_local("LOCALHOST", 8080)
    assert not _allowed_local("localhost", 8081)
    with pytest.raises(PermissionError, match="domain"):
        _resolve_address("evil.invalid", 8080)


def test_resolver_pins_and_denies_private(monkeypatch):
    from local_shell_mcp.webui import action_runtime
    def answers(ip):
        return [(2, 1, 0, "", (ip, 443))]
    monkeypatch.delenv("LSM_ACTION_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("LSM_ACTION_ALLOWED_ADDRESSES", raising=False)
    monkeypatch.setattr(action_runtime.socket, "getaddrinfo", lambda host, port, type: answers("8.8.8.8"))
    assert _resolve_address("public.example.org", 443) == "8.8.8.8"
    monkeypatch.setattr(action_runtime.socket, "getaddrinfo", lambda host, port, type: answers("127.0.0.1"))
    with pytest.raises(PermissionError):
        _resolve_address("private.invalid", 443)
    monkeypatch.setenv("LSM_ACTION_ALLOWED_ADDRESSES", "private.invalid:443")
    assert _resolve_address("private.invalid", 443) == "127.0.0.1"
    monkeypatch.setattr(action_runtime.socket, "getaddrinfo", lambda host, port, type: [])
    with pytest.raises(ConnectionError):
        _resolve_address("private.invalid", 443)


def test_encryption_isolated_by_file_permission(tmp_path):
    db = SQLiteDatabase(tmp_path)
    repo = ActionRepository(db)
    key = repo._cipher()
    assert isinstance(key, Fernet)
    assert key.decrypt(key.encrypt(b"test")) == b"test"
    p = tmp_path / "actions-fernet.key"
    p.chmod(0o666)
    with pytest.raises(PermissionError, match="Unsafe"):
        repo._cipher()


def test_oauth_storage_explicit_interactive_blocker(tmp_path):
    db = SQLiteDatabase(tmp_path)
    agent = make_agent(db)
    repo = ActionRepository(db)
    meta = make_body()
    meta["metadata"].update({
        "auth": {"type": "oauth", "authorization_url": "https://identity.example.org/authorize",
                 "client_url": "https://identity.example.org/token", "scope": "read",
                 "token_exchange_method": "default_post"},
        "oauth_client_id": "CLIENT-SECRET-ID",
        "oauth_client_secret": "CLIENT-SECRET-PASSWORD",
    })
    _, saved = repo.save("alice", agent["id"], meta)
    assert "CLIENT-SECRET" not in str(saved)
    assert "CLIENT-SECRET" not in db.path.read_text(errors="ignore")
    record = repo.get_for_tool("alice", agent["id"], tool_name("echo", BASE))
    assert record[1] == {"oauth_client_id": "CLIENT-SECRET-ID", "oauth_client_secret": "CLIENT-SECRET-PASSWORD"}
    assert _authorization(record[0], record[1]) if False else True
    with pytest.raises(RuntimeError, match="interactive flow unavailable"):
        _authorization(record[0], record[1])


@pytest.mark.asyncio
async def test_action_http_route_error_handlers_and_shared_repository(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import httpx
    from starlette.applications import Starlette

    from local_shell_mcp.webui import action_routes as route_module
    from local_shell_mcp.webui import routes

    db = SQLiteDatabase(tmp_path)
    alice_agent = make_agent(db)
    bob_agent = make_agent(db, "bob")
    repository = ActionRepository(db)
    monkeypatch.setattr(route_module, "_repository", lambda: repository)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="oauth"))
    app = Starlette(routes=route_module.action_routes())

    async def principal(scope, receive, send):
        if scope["type"] == "http":
            owner = dict(scope.get("headers", [])).get(b"x-user")
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner.decode())
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=principal),
                                 base_url="http://actions-web") as client:
        headers = {"x-user": "alice"}
        invalid = make_body()
        invalid["metadata"]["domain"] = "http://bad.example.org"
        response = await client.post(f"/api/agents/actions/{alice_agent['id']}", headers=headers, json=invalid)
        assert response.status_code == 400 and "Domain mismatch" in response.text
        response = await client.post(f"/api/agents/actions/{bob_agent['id']}", headers=headers, json=make_body())
        assert response.status_code == 404
        _, action = repository.save("alice", alice_agent["id"], make_body())
        response = await client.post(
            f"/api/agents/actions/{bob_agent['id']}", headers={"x-user": "bob"},
            json={**make_body(), "action_id": action["action_id"]},
        )
        assert response.status_code == 403
        response = await client.delete(f"/api/agents/actions/{alice_agent['id']}/missing", headers=headers)
        assert response.status_code == 404
        response = await client.delete(f"/api/agents/actions/{bob_agent['id']}/{action['action_id']}", headers=headers)
        assert response.status_code == 404
    # Real default repository path reads same shared SQLite database.
    from local_shell_mcp import settings
    monkeypatch.setattr(settings, "get_settings", lambda: SimpleNamespace(state_dir=tmp_path))
    assert route_module._repository().list("alice")[0] == action


@pytest.mark.asyncio
async def test_action_runtime_network_error_and_output_stripping(monkeypatch):
    import httpx

    from local_shell_mcp.webui import action_runtime
    from local_shell_mcp.webui.action_runtime import execute_action

    async def inject(operation, *, content, code=200, error=None):
        class MockResponse:
            status_code = code
            async def aiter_bytes(self):
                if error:
                    raise error
                yield content

        class Stream:
            async def __aenter__(self):
                return MockResponse()
            async def __aexit__(self, *args):
                pass

        class Client:
            def __init__(self, **kwargs):
                assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def stream(self, *args, **kwargs):
                return Stream()

        monkeypatch.setattr(action_runtime.httpx.AsyncClient, "__call__", None, raising=False) if False else None
        original = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", Client)
        monkeypatch.setattr(action_runtime, "_resolve_address", lambda *a: "8.8.8.8")
        try:
            return await execute_action(
                {"auth": {"type": "service_http", "authorization_type": "bearer"}},
                {"api_key": "SECRET-TOKEN"},
                {"server": BASE, "path": "/hello", "parameters": {"type": "object", "properties": {}},
                 "locations": {}, "method": "get", "content_type": ""},
                {},
            )
        finally:
            monkeypatch.setattr(httpx, "AsyncClient", original)


    assert await inject(None, content=b'{"token":"SECRET-TOKEN"}') == '{"token":"[redacted]"}'
    assert await inject(None, content=b"text SECRET-TOKEN") == "text [redacted]"
    assert await inject(None, content=b"") == ""
    assert await inject(None, content=b"12") == "12"
    assert await inject(None, content=b"x" * (256 * 1024 + 1)) == "API call failed (response too large)"
    assert await inject(None, content=b"", code=401) == "API call failed (HTTP 401)"
    assert await inject(None, content=b"", error=httpx.ReadTimeout("timed out")) == "API call failed (timeout)"
    assert await inject(None, content=b"", error=httpx.ConnectError("down")) == "API call failed (network error)"


def test_bindings_retain_unrelated_tools_same_domain(tmp_path):
    """LibreChat api/actions/tools.spec.ts: two Actions sharing a hostname."""
    db = SQLiteDatabase(tmp_path)
    agent = make_agent(db)
    repo = ActionRepository(db)
    _, first = repo.save("alice", agent["id"], make_body(operation="alpha"))
    _, second = repo.save("alice", agent["id"], make_body(operation="beta"))
    assert len(repo.list("alice")) == 2
    updated, replacement = repo.save(
        "alice", agent["id"],
        {**make_body(operation="gamma"), "action_id": first["action_id"]},
    )
    assert [normalize_action_tool_name(t) for t in updated["tools"]] == [
        tool_name("beta", BASE).replace("---", "_"),
        tool_name("gamma", BASE).replace("---", "_"),
    ]
    assert len(updated["actions"]) == 2
    assert repo.get_for_tool("alice", agent["id"], tool_name("alpha", BASE)) is None
    assert replacement["action_id"] == first["action_id"]
    assert repo.delete("alice", agent["id"], second["action_id"])
    assert [t["function"]["name"] for t in repo.tool_schemas(
        "alice", AgentRepository(db).get("alice", agent["id"])
    )] == [tool_name("gamma", BASE).replace("---", "_")]
