"""LibreChat startup, model and user configuration served by LSM Python.

The same SQLite identity owns user preferences, Agent definitions and chat
state. No public endpoint exposes model API keys or controller credentials.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .routes import _body, _owner, _repo


def _endpoint_models() -> dict[str, list[str]]:
    from .provider_profiles import all_profiles
    from .providers import provider_config

    available: dict[str, list[str]] = {}
    for value in all_profiles():
        label = value.get("name") or ("openAI" if value["provider"] == "openai" else value["provider"])
        try:
            provider_config(label)
        except ValueError:
            continue
        available[label] = value["models"]
    return available


def _endpoint_info() -> dict:
    from .provider_profiles import all_profiles

    configs = _endpoint_models()
    result: dict = {
        "agents": {
            "order": 0, "type": "agents", "name": "Agents",
            "modelDisplayLabel": "Agent", "allowedProviders": list(configs),
            "maxSubagents": 10,
            "capabilities": ["tools", "subagents", "chain", "ask_user_question", "end_after_tools"],
            "availableTools": [],
        },
    }
    for index, value in enumerate(all_profiles(), start=1):
        name = value.get("name") or ("openAI" if value["provider"] == "openai" else value["provider"])
        if name not in configs:
            continue
        # The native LibreChat endpointSchema uses OpenAI-compatible transport
        # for a custom name unless provider='anthropic'. LSM additionally has
        # an explicit Google native channel, never a generic custom client.
        endpoint_type = ("openAI" if value["provider"] == "openai" else value["provider"])
        result[name] = {
            "order": index, "type": endpoint_type, "name": name,
            "modelDisplayLabel": "Model", "userProvide": False,
        }
    return result


def _domain(request: Request) -> str:
    from ..settings import get_settings

    configured = getattr(get_settings(), "public_base_url", None)
    if configured:
        parsed = urlsplit(configured)
        return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


async def startup_config(request: Request):
    # This endpoint is queried before signing in. Keep the anonymous response
    # limited to render-only fields; do not expose credential/model inventory.
    settings = {
        "appTitle": "local-shell-mcp",
        "customFooter": "local-shell-mcp",
        "serverDomain": _domain(request),
        "discordLoginEnabled": False,
        "facebookLoginEnabled": False,
        "githubLoginEnabled": False,
        "googleLoginEnabled": False,
        "openidLoginEnabled": False,
        "appleLoginEnabled": False,
        "samlLoginEnabled": False,
        "openidLabel": "",
        "openidImageUrl": "",
        "openidAutoRedirect": False,
        "samlLabel": "",
        "samlImageUrl": "",
        "emailLoginEnabled": False,
        "registrationEnabled": False,
        "socialLoginEnabled": False,
        "passwordResetEnabled": False,
        "emailEnabled": False,
        "showBirthdayIcon": False,
        "helpAndFaqURL": "https://github.com/fwerkor/local-shell-mcp",
        "sharedLinksEnabled": False,
        "publicSharedLinksEnabled": False,
        "allowAccountDeletion": False,
    }
    # A controller user is authenticated by LSM PIN/OAuth. Exposing feature
    # toggles only to an authorized identity matches the original two-stage
    # startup config rather than leaking backend plugin settings before login.
    try:
        _owner(request)
    except HTTPException:
        return JSONResponse(settings)
    settings.update({
        "interface": {
            "modelSelect": True,
            "parameters": True,
            "presets": True,
            "multiConvo": True,
            "bookmarks": True,
            "agents": {"use": True, "create": True, "share": False, "public": False},
            "prompts": {"use": False, "create": False, "share": False, "public": False},
            "mcpServers": {"use": True, "create": True, "share": False, "public": False},
            "webSearch": False,
            "fileSearch": False,
            "contextUsage": False,
            "memories": False,
            "marketplace": {"use": False},
            "peoplePicker": {"users": False, "groups": False, "roles": False},
            "remoteAgents": {"use": False},
        },
        "mcpServers": {},
        "titleGenerationTiming": "final",
    })
    return JSONResponse(settings)


async def endpoint_configs(request: Request):
    _owner(request)
    return JSONResponse(_endpoint_info())


async def models(request: Request):
    _owner(request)
    available = _endpoint_models()
    return JSONResponse({**available, "agents": []})


async def token_configs(request: Request):
    _owner(request)
    return JSONResponse({})


async def preferences(request: Request):
    owner = _owner(request)
    repository = _repo()
    if request.method == "GET":
        return JSONResponse(repository.setting(owner, "user.preferences", {}))
    body = await _body(request)
    if len(str(body).encode("utf-8")) > 128 * 1024:
        raise HTTPException(413, detail="Preferences are too large")
    repository.save_setting(owner, "user.preferences", body)
    return JSONResponse(body)


async def presets(request: Request):
    owner = _owner(request)
    repo = _repo()
    known = repo.setting(owner, "user.presets", [])
    if not isinstance(known, list):
        known = []
    if request.method == "GET":
        return JSONResponse(known)
    new_value = await _body(request)
    name = str(new_value.get("title") or new_value.get("name") or "").strip()
    if not name or len(name) > 160:
        raise HTTPException(400, detail="Preset title is required")
    import uuid

    preset_id = str(new_value.get("presetId") or uuid.uuid4())
    new_value["presetId"] = preset_id
    known = [row for row in known if row.get("presetId") != preset_id]
    known.append(new_value)
    if len(known) > 200:
        raise HTTPException(413, detail="Preset limit exceeded")
    repo.save_setting(owner, "user.presets", known)
    return JSONResponse(new_value)


async def delete_preset(request: Request):
    owner = _owner(request)
    body = await _body(request)
    preset_id = str(body.get("presetId") or "")
    known = _repo().setting(owner, "user.presets", [])
    keep = [row for row in known if row.get("presetId") != preset_id]
    _repo().save_setting(owner, "user.presets", keep)
    return JSONResponse({"success": len(keep) != len(known)})


def config_routes() -> list[Route]:
    from .provider_profiles import provider_profiles

    return [
        Route("/api/lsm/providers", provider_profiles, methods=["GET", "PUT", "DELETE"]),
        Route("/api/config", startup_config, methods=["GET"]),
        Route("/api/endpoints", endpoint_configs, methods=["GET"]),
        Route("/api/endpoints/token-config", token_configs, methods=["GET"]),
        Route("/api/models", models, methods=["GET"]),
        Route("/api/user/preferences", preferences, methods=["GET", "PUT", "PATCH"]),
        Route("/api/presets", presets, methods=["GET", "POST"]),
        Route("/api/presets/delete", delete_preset, methods=["POST"]),
    ]
