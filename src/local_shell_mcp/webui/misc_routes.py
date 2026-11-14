"""First-party React application preferences and optional capability endpoints.

All persistent user settings are in the same Controller SQLite database.
Unavailable services are explicitly disabled rather than pretending that a
speech, search, credit or file backend is running.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .routes import _body, _owner, _repo

_MAX_ITEMS = 500
_MAX_PREFERENCE_BYTES = 256 * 1024


async def banner(request: Request):
    _owner(request)
    return JSONResponse(None)


async def files(request: Request):
    owner = _owner(request)
    from .attachments import file_record

    with _repo().database.connect() as db:
        rows = db.execute("SELECT * FROM attachments WHERE owner=? ORDER BY created_at DESC LIMIT 500",
                          (owner,)).fetchall()
    return JSONResponse([file_record(row) for row in rows])


async def preferences(request: Request):
    owner = _owner(request)
    repo = _repo()
    is_pinned = request.path_params["kind"] == "pinned-order"
    key = "user.pinned-order" if is_pinned else "user.favorites"
    if request.method == "GET":
        result = repo.setting(owner, key, [])
        return JSONResponse(result if isinstance(result, list) else [])
    body = await _body(request)
    field = "pinnedOrder" if is_pinned else "favorites"
    items = body.get(field)
    if not isinstance(items, list) or len(items) > _MAX_ITEMS:
        raise HTTPException(400, detail="An array with up to 500 entries is required")
    if len(str(items).encode("utf-8")) > _MAX_PREFERENCE_BYTES:
        raise HTTPException(413, detail="Preferences are too large")
    if is_pinned and not all(isinstance(item, str) for item in items):
        raise HTTPException(400, detail="Pinned-order entries must be strings")
    if not is_pinned and not all(isinstance(item, dict) for item in items):
        raise HTTPException(400, detail="Favorites must be objects")
    repo.save_setting(owner, key, items)
    return JSONResponse(items)


async def speech_config(request: Request):
    _owner(request)
    return JSONResponse({
        "speechToText": {"enabled": False},
        "textToSpeech": {"enabled": False},
    })


async def search_available(request: Request):
    _owner(request)
    # Native SQLite FTS5 chat search is available separately. This indicates
    # that the external LibreChat web-search provider is not configured.
    return JSONResponse(False)


async def role(request: Request):
    _owner(request)
    name = request.path_params["role_name"]
    if name not in {"USER", "ADMIN"}:
        raise HTTPException(404, detail="Role does not exist")
    # LSM is a single-user Controller. Ownership and OAuth scopes remain the
    # authority; these UI metadata fields never grant endpoint capabilities.
    return JSONResponse({
        "name": name,
        "permissions": {
            # Match the retained React PermissionTypes and Permissions enum
            # wire values exactly. Lowercase interface config keys are NOT
            # interchangeable with these RBAC role-permission identifiers.
            "AGENTS": {"USE": True, "CREATE": True, "SHARE": False, "SHARE_PUBLIC": False},
            "MCP_SERVERS": {"USE": True, "CREATE": False, "SHARE": False, "SHARE_PUBLIC": False},
            "PROMPTS": {"USE": False, "CREATE": False, "SHARE": False, "SHARE_PUBLIC": False},
            "MEMORIES": {"USE": False, "CREATE": False, "UPDATE": False, "READ": False},
        },
    })


async def balance(request: Request):
    _owner(request)
    # This is a client-side visibility shim. LSM does not track vendor credits.
    return JSONResponse({"tokenCredits": 0, "autoRefillEnabled": False})


async def conversation_permissions(request: Request):
    from .machine_permissions import (
        _CONVERSATION,
        _checked,
        _stored,
        resolve_access,
        validate_access_map,
    )

    owner = _owner(request)
    conversation_id = request.path_params["conversation_id"]
    repo = _repo()
    convo = repo.conversation(owner, conversation_id)
    if convo is None:
        raise HTTPException(404, detail="Conversation not found")
    key = "conversation.permissions." + conversation_id
    machine_key = _CONVERSATION + conversation_id
    defaults = {"web": False, "lsm": False, "mcp": False, "memory": False}
    if request.method == "PUT":
        payload = await _body(request)
        flags = {name: payload.get(name, False) for name in defaults}
        if any(type(item) is not bool for item in flags.values()):
            raise HTTPException(400, detail="Permission flags must be booleans")
        # An old bare `lsm` flag never confers implicit access to every machine.
        if "machines" in payload:
            try:
                machines = validate_access_map(payload["machines"])
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            _checked(request, machines)
            repo.save_setting(owner, machine_key, machines)
        repo.save_setting(owner, key, flags)
        if "machines" in payload:
            from .durable_tasks import mark_revoked

            mark_revoked(owner)
    else:
        flags = repo.setting(owner, key, defaults)
        if not isinstance(flags, dict):
            flags = defaults
    stored = _stored(repo, owner, machine_key)
    effective = resolve_access(owner, conversation_id, repo=repo)
    return JSONResponse({**{name: bool(flags.get(name, False)) for name in defaults},
                         "machines": stored, "effective": effective,
                         "projectId": convo.get("projectId")})

async def user_key(request: Request):
    _owner(request)
    provider = request.query_params.get("name", "")
    if not provider:
        raise HTTPException(404, detail="Unknown model channel")
    # The API key belongs to the server environment and is never echoed to
    # React. A fixed expiry advertises availability without secret disclosure.
    from .providers import provider_config

    try:
        provider_config(provider)
    except ValueError:
        raise HTTPException(404, detail="Model provider is not configured") from None
    return JSONResponse({"expiresAt": "2099-12-31T23:59:59.000Z"})


async def tool_calls(request: Request):
    owner = _owner(request)
    cid = request.query_params.get("conversationId")
    if not cid or _repo().conversation(owner, cid) is None:
        raise HTTPException(404, detail="Conversation not found")
    # Tool execution is not available in the basic Python text generation
    # runtime. No synthesized tool calls are returned as successful work.
    return JSONResponse([])


async def api_health(request: Request):
    return JSONResponse({"status": "ok"})


async def tags(request: Request):
    _owner(request)
    # No tags exist until the user assigns them in the Python project model.
    return JSONResponse([])


async def files_config(request: Request):
    _owner(request)
    from ..settings import get_settings
    from .attachments import MAX_ATTACHMENT_BYTES

    disabled = get_settings().disable_local
    endpoint = {"disabled": disabled, "fileLimit": 32, "fileSizeLimit": MAX_ATTACHMENT_BYTES,
                "totalSizeLimit": MAX_ATTACHMENT_BYTES, "legacyFileUploadUX": True}
    return JSONResponse({"endpoints": {"default": endpoint, "agents": endpoint},
                         "serverFileSizeLimit": MAX_ATTACHMENT_BYTES, "legacyFileUploadUX": True})


async def web_search_auth(request: Request):
    _owner(request)
    return JSONResponse({"authenticated": False, "authTypes": []})


def misc_routes() -> list[Route]:
    from .machine_permissions import machine_permission_routes

    return [*machine_permission_routes(),
        Route("/health", api_health, methods=["GET"]),
        Route("/api/health", api_health, methods=["GET"]),
        Route("/api/banner", banner, methods=["GET"]),
        Route("/api/tags", tags, methods=["GET"]),
        Route("/api/keys", user_key, methods=["GET"]),
        Route("/api/agents/tools/calls", tool_calls, methods=["GET"]),
        Route("/api/lsm/preferences/{conversation_id}", conversation_permissions, methods=["GET", "PUT"]),
        Route("/api/files/config", files_config, methods=["GET"]),
        Route("/api/agents/tools/web_search/auth", web_search_auth, methods=["GET"]),
        Route("/api/files", files, methods=["GET"]),
        Route("/api/files/speech/config/get", speech_config, methods=["GET"]),
        Route("/api/search/enable", search_available, methods=["GET"]),
        Route("/api/roles/{role_name}", role, methods=["GET"]),
        Route("/api/balance", balance, methods=["GET"]),
        Route("/api/user/settings/{kind}", preferences, methods=["GET", "POST"]),
    ]
