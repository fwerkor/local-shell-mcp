"""Original /api/agents/actions routes, keyed to existing LSM principal."""
from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from .actions import ActionRepository
from .routes import _body, _owner


def _repository():
    from ..settings import get_settings
    from ..sqlite_store import shared_database
    return ActionRepository(shared_database(get_settings().state_dir.resolve()))


async def actions_list(request: Request):
    return JSONResponse(_repository().list(_owner(request)))


async def actions_save(request: Request):
    owner = _owner(request)
    try:
        agent, action = _repository().save(owner, request.path_params["agent_id"], await _body(request))
    except PermissionError as error:
        raise HTTPException(403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    return JSONResponse([agent, action])


async def actions_delete(request: Request):
    owner = _owner(request)
    try:
        deleted = _repository().delete(owner, request.path_params["agent_id"], request.path_params["action_id"])
    except KeyError as error:
        raise HTTPException(404, detail=str(error)) from error
    if not deleted:
        raise HTTPException(404, detail="Action not found")
    return JSONResponse({"message": "Action deleted successfully"})


async def action_oauth_bind(request: Request):
    """Source-compatible POST /api/actions/:action_id/oauth/bind."""
    from .action_oauth import _base_url, bind_cookie, cookie_name
    from .auth import _same_origin

    _same_origin(request)
    owner = _owner(request)
    action_id = request.path_params["action_id"]
    try:
        token = bind_cookie(_repository(), owner, action_id)
    except KeyError as exc:
        raise HTTPException(404, detail="OAuth Action not found") from exc
    base = _base_url()
    response = JSONResponse({"success": True}, headers={"Cache-Control": "no-store"})
    response.set_cookie(cookie_name(action_id), token, max_age=600, httponly=True,
                        secure=base.startswith("https://"), samesite="lax",
                        path=f"/api/actions/{action_id}/oauth")
    return response


async def action_oauth_callback(request: Request):
    """One-shot state + browser CSRF binding; provider callback needs no JWT."""
    from urllib.parse import quote

    from .action_oauth import claim_callback, cookie_name, exchange_code

    action_id = request.path_params["action_id"]
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error_code = "callback_failed"
    try:
        if not isinstance(code, str) or not 1 <= len(code) <= 2048:
            raise ValueError("Missing or invalid authorization code")
        if not isinstance(state, str):
            raise ValueError("Missing state")
        repo = _repository()
        owner, metadata, credentials, redirect, version = claim_callback(
            repo, action_id, state, request.cookies.get(cookie_name(action_id)))
        principal = getattr(request.state, "principal", None)
        if principal is not None and getattr(principal, "subject", None) not in (None, owner):
            raise PermissionError("OAuth browser identity mismatch")
        await exchange_code(repo, owner, action_id, metadata, credentials, redirect, code,
                            expected_version=version)
        label = str(metadata.get("domain") or "Action")
        response = RedirectResponse("/oauth/success?serverName=" + quote(label, safe=""), status_code=302)
        response.delete_cookie(cookie_name(action_id), path=f"/api/actions/{action_id}/oauth")
        response.headers["Cache-Control"] = "no-store"
        return response
    except (ValueError, PermissionError, KeyError):
        error_code = "invalid_state"
    except Exception:
        # A provider error must never leak codes, tokens or client secrets.
        pass
    return RedirectResponse("/oauth/error?error=" + error_code, status_code=302,
                            headers={"Cache-Control": "no-store"})


def action_routes() -> list[Route]:
    return [
        Route("/api/agents/actions", actions_list, methods=["GET"]),
        Route("/api/actions/{action_id}/oauth/bind", action_oauth_bind, methods=["POST"]),
        Route("/api/actions/{action_id}/oauth/callback", action_oauth_callback, methods=["GET"]),
        Route("/api/agents/actions/{agent_id}", actions_save, methods=["POST"]),
        Route("/api/agents/actions/{agent_id}/{action_id}", actions_delete, methods=["DELETE"]),
    ]
