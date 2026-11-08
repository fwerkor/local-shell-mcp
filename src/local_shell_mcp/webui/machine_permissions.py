"""Owner-scoped per-machine Agent permissions with inherited SQLite defaults.

Only exact machine identifiers are granted. A machine not present in any policy
is denied, even when added after a user configures global defaults.
"""

from __future__ import annotations

import re
import time
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .routes import _body, _owner, _repo

_LEVELS = frozenset({"none", "read", "write"})
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_GLOBAL = "agent.machine_policy.global"
_PROJECT = "agent.machine_policy.project."
_CONVERSATION = "agent.machine_policy.conversation."


def validate_access_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 128:
        raise ValueError("Machine permissions must be an object with at most 128 entries")
    result: dict[str, str] = {}
    for name, access in value.items():
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError("Invalid machine identifier")
        if access not in _LEVELS:
            raise ValueError("Machine access must be none, read or write")
        result[name] = access
    return result


def _stored(repo: Any, owner: str, key: str) -> dict[str, str]:
    value = repo.setting(owner, key, {})
    # Never treat an old all-machine boolean permission as a privilege grant.
    try:
        return validate_access_map(value)
    except (ValueError, TypeError):
        return {}


def resolve_access(owner: str, conversation_id: str | None = None, *, project_id: str | None = None,
                   repo: Any = None) -> dict[str, str]:
    repository = repo or _repo()
    policy = _stored(repository, owner, _GLOBAL)
    if conversation_id is not None:
        convo = repository.conversation(owner, conversation_id)
        if convo is None:
            raise KeyError("Conversation not found")
        project_id = convo.get("projectId")
    if project_id:
        if repository.project(owner, project_id) is None:
            raise KeyError("Project not found")
        policy.update(_stored(repository, owner, _PROJECT + project_id))
    if conversation_id is not None:
        policy.update(_stored(repository, owner, _CONVERSATION + conversation_id))
    return policy


def access_level(owner: str, conversation_id: str, machine: str, *, repo: Any = None) -> str:
    return resolve_access(owner, conversation_id, repo=repo).get(machine, "none")


def _principal_scopes(request: Request) -> set[str]:
    from ..auth import principal_scopes
    from ..settings import get_settings

    if get_settings().auth_mode == "none":
        return {"shell:read", "shell:write", "remote:use"}
    principal = getattr(request.state, "principal", None)
    return principal_scopes(principal) if principal is not None and hasattr(principal, "claims") else set()


def require_machine_scope(scopes: set[str], machine: str, level: str, *, expires: int | None = None) -> None:
    if expires is not None and expires <= int(time.time()):
        raise PermissionError("Agent session authorization has expired")
    required_scopes = ("shell:read", "shell:write") if level == "write" else ("shell:read",)
    for required in required_scopes:
        if required not in scopes:
            raise PermissionError(f"{required} permission is required")
    if machine != "local" and "remote:use" not in scopes:
        raise PermissionError("remote:use permission is required")


def authorize_machine_action(
    owner: str, conversation_id: str, machine: str, operation: str, *,
    scopes: set[str], expires: int | None = None, repo: Any = None,
) -> None:
    """The single policy gate for every model-initiated machine operation.

    `read` covers inspection. `write` includes edits and other mutations.
    `execute` is deliberately classified as write-capable: a shell command
    cannot reliably be distinguished as read-only just by its text.
    """
    from ..settings import get_settings

    if operation not in {"read", "write", "execute"}:
        raise ValueError("Unknown machine operation class")
    if not isinstance(machine, str) or not _NAME_RE.fullmatch(machine):
        raise PermissionError("Invalid target machine")
    settings = get_settings()
    if machine == "local" and settings.disable_local:
        raise PermissionError("Local machine is disabled")
    if machine != "local" and not settings.remote_enabled:
        raise PermissionError("Remote machine access is disabled")
    granted = access_level(owner, conversation_id, machine, repo=repo)
    if granted == "none":
        raise PermissionError(f"Access to machine {machine} is not granted")
    if operation in {"write", "execute"} and granted != "write":
        raise PermissionError(f"Machine {machine} is read-only")
    # The per-machine grant never expands the OAuth principal's own rights.
    require_machine_scope(scopes, machine, "write" if operation != "read" else "read", expires=expires)
    if operation == "execute" and "shell:execute" not in scopes:
        raise PermissionError("shell:execute permission is required")


def _checked(request: Request, permissions: dict[str, str]) -> None:
    from ..settings import get_settings

    scopes = _principal_scopes(request)
    settings = get_settings()
    for machine, level in permissions.items():
        if level == "none":
            continue
        if machine == "local" and settings.disable_local:
            raise HTTPException(403, detail="Local machine is disabled")
        if machine != "local" and not settings.remote_enabled:
            raise HTTPException(403, detail="Remote machines are disabled")
        try:
            require_machine_scope(scopes, machine, level)
        except PermissionError as exc:
            raise HTTPException(403, detail=str(exc)) from exc


async def available_machines(request: Request):
    _owner(request)
    from ..human_ui import _machine_rows

    if "shell:read" not in _principal_scopes(request):
        raise HTTPException(403, detail="shell:read permission is required")
    from ..settings import get_settings

    try:
        rows = _machine_rows().get("machines", [])
    except Exception:
        rows = []
    # The Controller host is always the `local` machine, including when
    # execution on it is disabled. Do not hide its permission row.
    local_status = "disabled" if get_settings().disable_local else "online"
    rows = [{"name": "local", "status": local_status},
            *[row for row in rows if row.get("name") != "local"]]
    visible = []
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            continue
        if name != "local" and "remote:use" not in _principal_scopes(request):
            continue
        visible.append({"name": name, "status": row.get("status", "unknown")})
    return JSONResponse({"machines": visible})


async def default_permissions(request: Request):
    owner = _owner(request)
    repository = _repo()
    key = _GLOBAL
    if "project_id" in request.path_params:
        project_id = request.path_params["project_id"]
        if repository.project(owner, project_id) is None:
            raise HTTPException(404, detail="Project not found")
        key = _PROJECT + project_id
    if request.method == "PUT":
        body = await _body(request)
        try:
            value = validate_access_map(body.get("machines"))
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        _checked(request, value)
        repository.save_setting(owner, key, value)
    else:
        value = _stored(repository, owner, key)
    inherited = {} if key == _GLOBAL else _stored(repository, owner, _GLOBAL)
    return JSONResponse({"machines": value, "effective": {**inherited, **value}})


def machine_permission_routes() -> list[Route]:
    return [
        Route("/api/lsm/permissions/machines", available_machines, methods=["GET"]),
        Route("/api/lsm/permissions/defaults", default_permissions, methods=["GET", "PUT"]),
        Route("/api/lsm/permissions/projects/{project_id}", default_permissions, methods=["GET", "PUT"]),
    ]
