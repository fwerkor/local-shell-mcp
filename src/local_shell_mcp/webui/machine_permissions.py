"""Owner-scoped per-machine Agent permissions with inherited SQLite defaults.

Registered machines default to read/write. Explicit owner, project and chat
overrides take precedence; an unknown machine is never implicitly granted.
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


class MachineReadOnlyError(PermissionError):
    """The requested operation exceeds a read-only machine grant."""


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


def agent_access_policy(agent: dict) -> tuple[dict[str, str], str] | None:
    """Resolve an Agent's ACL, preserving legacy per-tool and implicit-write policies."""
    if "machine_permissions" not in agent and "machine_default_permission" not in agent:
        return None
    default = agent.get("machine_default_permission", "write")
    if not isinstance(default, str) or default not in _LEVELS:
        raise ValueError("Default machine access must be none, read or write")
    return validate_access_map(agent.get("machine_permissions", {})), default


def _stored(repo: Any, owner: str, key: str) -> dict[str, str]:
    value = repo.setting(owner, key, {})
    # Never treat an old all-machine boolean permission as a privilege grant.
    try:
        return validate_access_map(value)
    except (ValueError, TypeError):
        return {}


def _registered_defaults() -> dict[str, str]:
    """Expose all registered machines by default, including offline Workers.

    The Controller still enforces server-side machine switches and OAuth scopes
    at each native tool invocation. Nothing is granted to unknown machine IDs.
    """
    from ..remote import remote_manager

    defaults = {"local": "write"}
    try:
        workers = remote_manager().list_machines().get("machines", ())
    except Exception:
        # A temporarily unavailable Worker registry cannot break ordinary
        # chat. Remote names still need registration before implicit exposure.
        workers = ()
    for worker in workers:
        name = worker.get("name") if isinstance(worker, dict) else None
        if isinstance(name, str) and _NAME_RE.fullmatch(name):
            defaults[name] = "write"
    return defaults


def resolve_access(owner: str, conversation_id: str | None = None, *, project_id: str | None = None,
                   repo: Any = None) -> dict[str, str]:
    repository = repo or _repo()
    policy = _registered_defaults()
    policy.update(_stored(repository, owner, _GLOBAL))
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


def effective_machine_access(owner: str, conversation_id: str, *, agent: dict | None,
                             scopes: set[str], expires: int | None = None,
                             repo: Any = None) -> tuple[dict[str, str], str]:
    """Resolve the machine ACL subject to the Agent and principal ceilings."""
    from ..settings import get_settings

    policy = resolve_access(owner, conversation_id, repo=repo)
    agent_policy, default = agent_access_policy(agent or {}) or ({}, "write")
    rank = {"none": 0, "read": 1, "write": 2}
    settings = get_settings()
    effective: dict[str, str] = {}
    for name, level in sorted(policy.items()):
        level = min(level, agent_policy.get(name, default), key=rank.__getitem__)
        if (name == "local" and settings.disable_local
                or name != "local" and not settings.remote_enabled):
            level = "none"
        else:
            try:
                require_machine_scope(scopes, name, "read", expires=expires)
            except PermissionError:
                level = "none"
            if level == "write":
                try:
                    require_machine_scope(scopes, name, "write", expires=expires)
                except PermissionError:
                    level = "read"
        effective[name] = level
    return effective, default


def machine_access_context(owner: str, conversation_id: str, *, agent: dict | None,
                           scopes: set[str], expires: int | None = None,
                           repo: Any = None) -> str:
    """Render the live native-machine ACL, not a grant or a history message."""
    effective, default = effective_machine_access(
        owner, conversation_id, agent=agent, scopes=scopes, expires=expires, repo=repo,
    )
    groups: dict[str, list[str]] = {"none": [], "read": [], "write": []}
    for name, level in effective.items():
        groups[level].append(name)
    execution_restricted = "shell:execute" not in scopes and bool(groups["write"])
    if not (groups["none"] or groups["read"] or default != "write" or execution_restricted):
        return ""
    lines = ["Current native machine access restrictions (server-enforced):"]
    for level, label in (("none", "No access"), ("read", "Read-only"), ("write", "Read/write")):
        if groups[level]:
            lines.append(f"- {label}: {', '.join(groups[level])}")
    if default != "write":
        label = {"none": "no access", "read": "read-only"}[default]
        lines.append(f"- Agent default for newly registered machines: {label}")
    if execution_restricted:
        lines.append("- Shell and other execution-class operations are not authorized.")
    lines.append("Unlisted, unregistered machines are not implicitly authorized. "
                 "Use read-only inspection tools on read-only machines; do not run shell "
                 "commands, scripts, or other mutating operations on them. "
                 "Other tool-specific restrictions still apply.")
    return "\n".join(lines)


def access_level(owner: str, conversation_id: str, machine: str, *, repo: Any = None) -> str:
    return resolve_access(owner, conversation_id, repo=repo).get(machine, "none")


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
        raise MachineReadOnlyError(f"Machine {machine} is read-only")
    # The per-machine grant never expands the OAuth principal's own rights.
    require_machine_scope(scopes, machine, "write" if operation != "read" else "read", expires=expires)
    if operation == "execute" and "shell:execute" not in scopes:
        raise PermissionError("shell:execute permission is required")


async def available_machines(request: Request):
    _owner(request)
    from ..human_ui import _machine_rows
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
        # UI toggles are exposure preferences, not OAuth grants. Runtime
        # dispatch still validates the unchanged principal scopes.
        repository.save_setting(owner, key, value)
        from .durable_tasks import mark_revoked

        mark_revoked(owner)
    else:
        value = _stored(repository, owner, key)
    effective = (resolve_access(owner, repo=repository) if key == _GLOBAL
                 else resolve_access(owner, project_id=project_id, repo=repository))
    return JSONResponse({"machines": value, "effective": effective})


def machine_permission_routes() -> list[Route]:
    return [
        Route("/api/lsm/permissions/machines", available_machines, methods=["GET"]),
        Route("/api/lsm/permissions/defaults", default_permissions, methods=["GET", "PUT"]),
        Route("/api/lsm/permissions/projects/{project_id}", default_permissions, methods=["GET", "PUT"]),
    ]
