"""Original LibreChat Agent Trigger authenticated remote ingress and key lifecycle.

Sources: triggers/ingress.ts, bindings.ts, envelope.ts. External bearer keys
are distinct from Controller OAuth; no browser cookie or model can spoof them.
"""
from __future__ import annotations

import re

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..auth import require_scopes
from ..settings import get_settings
from ..sqlite_store import shared_database
from .event_triggers import (
    _NO_PARENT,
    _iso,
    bound_child,
    enqueue_event,
    get_event,
    mint_source_key,
    register_bound_child,
    revoke_source_key,
    source_keys,
)
from .routes import _body, _owner

_HEADER = re.compile(r"^[A-Za-z0-9._~:/+=-]{1,256}$")


def _database():
    return shared_database(get_settings().state_dir.resolve())


def _event_auth(request: Request) -> tuple[str, str]:
    principal = getattr(request.state, "principal", None)
    claims = getattr(principal, "claims", {})
    if claims.get("auth") != "agent-event" or not claims.get("source_key_id"):
        raise HTTPException(401, detail="Authenticated remote Agent event API key required")
    return principal.subject, claims["source_key_id"]


def _key(request: Request) -> str:
    # Starlette collapses duplicate headers in .headers; source ingress
    # requires exactly one raw Idempotency-Key, including for retries.
    values = [v.decode("latin-1") for k, v in request.scope.get("headers", [])
              if k.lower() == b"idempotency-key"]
    if len(values) != 1 or not _HEADER.fullmatch(values[0].strip()):
        raise HTTPException(400, detail="Exactly one valid Idempotency-Key header is required")
    return values[0].strip()


def _event_error(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(403, detail=str(error))
    if isinstance(error, (ValueError, TypeError)):
        return HTTPException(409 if "Idempotency-Key was already used" in str(error) else 400,
                             detail=str(error))
    return HTTPException(500, detail="Agent event admission failed")


async def event_source_keys(request: Request):
    owner = _owner(request)
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.claims.get("auth") == "agent-event":
        raise HTTPException(403, detail="Controller administration is required")
    require_scopes(principal, {"admin:config"})
    if request.method == "GET":
        return JSONResponse({"sources": source_keys(_database(), owner)})
    payload = await _body(request)
    permissions = payload.get("permissions", ["fire", "continue", "steer"])
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        raise HTTPException(400, detail="Invalid source permissions")
    try:
        result = mint_source_key(_database(), owner, label=payload.get("label", "event-source"),
                                 permissions=tuple(permissions), expires_at=payload.get("expiresAt"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    return JSONResponse(result, status_code=201, headers={"Cache-Control": "no-store"})


async def revoke_event_source(request: Request):
    owner = _owner(request)
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.claims.get("auth") == "agent-event":
        raise HTTPException(403, detail="Controller administration is required")
    require_scopes(principal, {"admin:config"})
    if not revoke_source_key(_database(), owner, request.path_params["key_id"]):
        raise HTTPException(404, detail="Event source not found")
    return JSONResponse({"revoked": True})


async def enqueue_agent_event(request: Request):
    owner, source_id = _event_auth(request)
    if request.headers.get("content-length"):
        try:
            size = int(request.headers["content-length"])
        except ValueError as exc:
            raise HTTPException(400, detail="Invalid event body length") from exc
        if size > 1024 * 1024:
            raise HTTPException(413, detail="Agent trigger event is too large")
    payload = await request.body()
    if len(payload) > 1024 * 1024:
        raise HTTPException(413, detail="Agent trigger event is too large")
    try:
        import json

        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("An event must be a JSON object")
        if data.get("mode") == "continue":
            binding_id = data.get("bindingId")
            if not isinstance(binding_id, str):
                raise ValueError("Continue events require an authenticated agent-event binding")
            binding = bound_child(_database(), owner, source_id, binding_id)
            if binding is None:
                raise PermissionError("Authenticated event binding was not found")
            # Source bindings.ts:resolve overwrites caller-controlled target
            # before constructing its source envelope. The child branch leaf
            # is resolved by the admitted AgentRunner, not trusted to ingress.
            data = {**data, "orderingKey": binding_id, "target": {
                "agentId": binding["agent_id"],
                "conversationId": binding["conversation_id"],
                "parentMessageId": _NO_PARENT,
                "bindingId": binding_id,
            }}
        elif data.get("bindingId") is not None:
            raise ValueError("bindingId is valid only for continue events")
        receipt = enqueue_event(_database(), owner, source_id, _key(request), data)
    except (ValueError, TypeError, PermissionError) as exc:
        raise _event_error(exc) from exc
    return JSONResponse({**receipt, "availableAt": _iso(receipt["availableAt"])}, status_code=202,
                        headers={"Location": "/api/agents/v1/events/" + receipt["id"],
                                 "Cache-Control": "no-store"})


async def register_agent_event_binding(request: Request):
    owner, source_id = _event_auth(request)
    data = await _body(request)
    target = data.get("target")
    if not isinstance(target, dict):
        raise HTTPException(400, detail="A target Agent is required")
    try:
        value = register_bound_child(
            _database(), owner, source_id, _key(request),
            actor_id=data.get("actorId"),
            parent_conversation_id=data.get("parentConversationId"),
            parent_message_id=data.get("parentMessageId"),
            target_agent_id=target.get("agentId"),
        )
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise _event_error(exc) from exc
    return JSONResponse(value, status_code=201, headers={"Cache-Control": "no-store"})


async def get_agent_event(request: Request):
    owner, source_id = _event_auth(request)
    try:
        result = get_event(_database(), owner, source_id, request.path_params["delivery_id"])
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(404, detail="Event delivery not found")
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


def event_trigger_routes() -> list[Route]:
    return [
        Route("/api/agents/v1/event-source-keys", event_source_keys, methods=["GET", "POST"]),
        Route("/api/agents/v1/event-source-keys/{key_id}", revoke_event_source,
              methods=["DELETE"]),
        Route("/api/agents/v1/events/bindings", register_agent_event_binding,
              methods=["POST"]),
        Route("/api/agents/v1/events", enqueue_agent_event, methods=["POST"]),
        Route("/api/agents/v1/events/{delivery_id}", get_agent_event, methods=["GET"]),
    ]
