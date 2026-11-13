"""Resumable, authenticated React Agent generation endpoints (Python runtime).

The stream is detached from any one browser connection. All events are persisted
in the shared SQLite controller DB and are replayable after a network break.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .agents import AgentRepository
from .ask_user_tools import ask_user_requested
from .generation_protocol import request_protocol
from .generations import Generation, GenerationConflict, GenerationStore
from .providers import (
    ProviderConfig,
    provider_config,
    selected_provider,
    stream_model,
    stream_model_with_tools,
)
from .routes import _body, _owner

log = logging.getLogger(__name__)
_TASKS: dict[str, asyncio.Task] = {}
_TASK_GUARD = asyncio.Lock()
# Preserve durable running checkpoints only for cooperative Controller shutdown.
# Explicit abort/disconnect cancellation keeps its existing terminal semantics.
_SHUTDOWN_TASKS: set[asyncio.Task] = set()


def _database():
    from ..settings import get_settings
    from ..sqlite_store import shared_database

    return shared_database(get_settings().state_dir.resolve())


def _generation_store() -> GenerationStore:
    return GenerationStore(_database())


def _request_grant(request: Request) -> tuple[set[str], int | None]:
    from ..auth import principal_scopes
    from ..settings import get_settings

    if get_settings().auth_mode == "none":
        from ..oauth import ALL_OAUTH_SCOPES

        return set(ALL_OAUTH_SCOPES), None
    principal = getattr(request.state, "principal", None)
    if principal is None or not hasattr(principal, "claims"):
        return set(), None
    return principal_scopes(principal), principal.claims.get("exp")


def _generation_body(job: Generation, *, status: str = "stream", resumed: bool = False,
                     protocol_version: int | None = None) -> dict:
    return {
        "status": status,
        "streamId": job.conversation_id,
        "conversationId": job.conversation_id,
        "generationCreatedAt": job.generation_created_at,
        "generationProtocolVersion": job.protocol_version if protocol_version is None else protocol_version,
        "resumed": resumed,
    }


def _generator_headers(protocol_version: int = 2) -> dict[str, str]:
    return {
        "X-LibreChat-Generation-Protocol": str(protocol_version),
        "Cache-Control": "no-cache, no-store",
        "X-Accel-Buffering": "no",
    }


async def _run_model(
    owner: str, generation: Generation, profile: ProviderConfig,
    *, instructions: str = "", parameters: dict | None = None,
    native_file_tools: bool = False, write_tools: bool = False,
    ask_user_enabled: bool = False, mcp_enabled: bool = False,
    parent_agent: dict | None = None,
    resume_history: list[dict] | None = None, partial_text: str = "",
    approved_batch=None, resume_namespace: str = "",
    granted_scopes: frozenset[str] = frozenset(), grant_expires: int | None = None,
) -> None:
    repo = _generation_store()
    text_parts: list[str] = [partial_text] if partial_text else []
    params = parameters or {}
    step_id = "step_" + generation.run_id
    now_ms = int(time.time() * 1000)
    try:
        from .agent_runner import AgentRunner
        from .agent_runtime import AgentSuspended

        history = resume_history if resume_history is not None else repo.history(
            owner, generation.conversation_id, message_id=generation.user_message_id,
        )
        if instructions and resume_history is None:
            history.insert(0, {"role": "system", "content": instructions})
        if resume_history is None:
            repo.append(owner, generation.run_id, {
                "event": "on_run_step", "data": {
                    "type": "message_creation", "id": step_id,
                    "runId": generation.response_message_id, "index": 0,
                    "created_at": now_ms, "status": "in_progress",
                    "stepDetails": {"type": "message_creation", "message_creation": {
                        "message_id": generation.response_message_id,
                        "content_type": "text", "phase": "final_answer",
                    }},
                },
            })

        async def append_text(chunk):
            if not chunk:
                return
            text_parts.append(chunk)
            repo.append(owner, generation.run_id, {
                "event": "on_message_delta", "data": {
                    "id": step_id, "delta": {"content": {
                        "type": "text", "text": chunk, "phase": "final_answer",
                    }},
                },
            })

        runner = AgentRunner(owner, generation, _database(), repo,
                             scopes=granted_scopes, grant_expires=grant_expires,
                             stream_tools=stream_model_with_tools, stream_text=stream_model,
                             on_text=append_text, agent=parent_agent, profile=profile,
                             parameters=params, ask_user_enabled=ask_user_enabled,
                             mcp_enabled=mcp_enabled, resume_history=resume_history,
                             resume_namespace=resume_namespace, partial_text=partial_text,
                             approved_batch=approved_batch)
        try:
            await runner.run(history)
        except AgentSuspended:
            return
        repo.append(owner, generation.run_id, {
            "event": "on_run_step_closed", "data": {
                "id": step_id, "index": 0, "type": "message_creation",
                "status": "completed", "runId": generation.response_message_id,
                "created_at": now_ms, "closed_at": int(time.time() * 1000),
            },
        })
        repo.finish(owner, generation.run_id, status="complete", text=runner.partial_text)
    except asyncio.CancelledError:
        if asyncio.current_task() not in _SHUTDOWN_TASKS:
            repo.finish(owner, generation.run_id, status="aborted", text="".join(text_parts))
        raise
    except Exception as exc:
        # Do not put provider tokens, request metadata or secrets in response.
        log.warning("Model generation failed for %s: %s", generation.run_id, type(exc).__name__)
        repo.finish(owner, generation.run_id, status="error", text="".join(text_parts),
                    error=f"Model generation failed ({type(exc).__name__})")
    finally:
        _SHUTDOWN_TASKS.discard(asyncio.current_task())
        async with _TASK_GUARD:
            _TASKS.pop(generation.run_id, None)


async def _start_task(owner: str, generation: Generation, profile: ProviderConfig,
                      agent: dict | None, native_file_tools: bool = False, write_tools: bool = False,
                      ask_user_enabled: bool = False, mcp_enabled: bool = False,
                      resume_history: list[dict] | None = None, partial_text: str = "",
                      approved_batch=None, resume_namespace: str = "",
                      granted_scopes: frozenset[str] = frozenset(), grant_expires: int | None = None) -> None:
    async with _TASK_GUARD:
        existing = _TASKS.get(generation.run_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(
            _run_model(owner, generation, profile,
                       instructions=str((agent or {}).get("instructions") or ""),
                       parameters=(agent or {}).get("model_parameters") or {},
                       native_file_tools=native_file_tools, write_tools=write_tools,
                       ask_user_enabled=ask_user_enabled, mcp_enabled=mcp_enabled,
                       parent_agent=agent,
                       resume_history=resume_history, partial_text=partial_text,
                       approved_batch=approved_batch, resume_namespace=resume_namespace,
                       granted_scopes=granted_scopes, grant_expires=grant_expires),
            name="webui-generation-" + generation.run_id,
        )
        _TASKS[generation.run_id] = task


async def start_generation(request: Request):
    owner = _owner(request)
    payload = await _body(request)
    payload = dict(payload)
    if "projectId" not in payload and "chatProjectId" in payload:
        payload["projectId"] = payload["chatProjectId"]
    if not payload.get("provider"):
        payload["provider"] = selected_provider({**payload, "endpoint": payload.get("endpoint") or request.path_params.get("endpoint")})
    protocol = request_protocol(request, payload)
    agent_id = payload.get("agent_id")
    agent = None
    if agent_id is not None:
        if not isinstance(agent_id, str):
            raise HTTPException(400, detail="Invalid agent identifier")
        agent = AgentRepository(_database()).get(owner, agent_id)
        if agent is None:
            raise HTTPException(404, detail="Agent not found")
    kind = selected_provider(payload, agent)
    model = (agent or {}).get("model") or payload.get("model")
    # Permission inheritance is resolved against SQLite at the start and
    # rechecked before every tool. The initial OAuth grant cannot be elevated
    # by modifying defaults while a generation is in progress.
    from .machine_permissions import require_machine_scope, resolve_access

    existing_cid = payload.get("conversationId")
    try:
        if isinstance(existing_cid, str) and existing_cid not in {"", "new", "new_conversation"}:
            policy = resolve_access(owner, existing_cid)
        else:
            project_id = payload.get("projectId")
            if project_id is not None and not isinstance(project_id, str):
                raise HTTPException(400, detail="Invalid project id")
            policy = resolve_access(owner, project_id=project_id)
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    requested_tools = any(level in {"read", "write"} for level in policy.values())
    scopes, grant_expires = _request_grant(request)
    if requested_tools:
        try:
            for machine, level in policy.items():
                if level in {"read", "write"}:
                    require_machine_scope(scopes, machine, level, expires=grant_expires)
        except PermissionError as exc:
            raise HTTPException(403, detail=str(exc)) from exc
    try:
        profile = provider_config(kind, model)
        result, fresh = _generation_store().begin(owner, payload, agent, protocol_version=protocol)
    except GenerationConflict as exc:
        return JSONResponse(_generation_body(exc.existing, status="replaced",
                                               protocol_version=min(protocol, exc.existing.protocol_version)),
                            status_code=409, headers=_generator_headers(min(protocol, exc.existing.protocol_version)))
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    protocol = min(protocol, result.protocol_version)
    if fresh:
        ask_user_enabled = ask_user_requested(agent, payload)
        from .routes import _repo

        flags = _repo().setting(owner, "conversation.permissions." + result.conversation_id, {})
        mcp_enabled = isinstance(flags, dict) and flags.get("mcp") is True
        await _start_task(owner, result, profile, agent, native_file_tools=requested_tools,
                          write_tools=any(level == "write" for level in policy.values()),
                          ask_user_enabled=ask_user_enabled, mcp_enabled=mcp_enabled,
                          granted_scopes=frozenset(scopes), grant_expires=grant_expires)
    return JSONResponse(_generation_body(result, status="stream" if fresh else "resumed",
                                         resumed=not fresh, protocol_version=protocol), status_code=202,
                        headers=_generator_headers(protocol))


async def _events(owner: str, generation: Generation, after: int = 0) -> AsyncIterator[bytes]:
    store = _generation_store()
    last = max(0, after)
    last_heartbeat = time.monotonic()
    while True:
        results = store.events(owner, generation.run_id, last)
        for seq, value in results:
            last = seq
            yield f"id: {seq}\ndata: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()
        latest = store.get(owner, generation.run_id)
        if latest is None or latest.status in {"complete", "aborted", "error", "interrupted"}:
            if not results:
                return
            continue
        if time.monotonic() - last_heartbeat > 12:
            yield b": heartbeat\n\n"
            last_heartbeat = time.monotonic()
        await asyncio.sleep(0.15)


async def stream_generation(request: Request):
    owner = _owner(request)
    conversation_id = request.path_params["stream_id"]
    generation = _generation_store().latest(owner, conversation_id)
    if generation is None:
        raise HTTPException(404, detail="Generation stream not found")
    expected = request.query_params.get("generationCreatedAt")
    if expected:
        try:
            if int(expected) != generation.generation_created_at:
                raise HTTPException(409, detail="Generation superseded by newer run")
        except ValueError as exc:
            raise HTTPException(400, detail="Invalid generation identity") from exc
    cursor = request.headers.get("last-event-id") or request.query_params.get("after")
    try:
        after = max(0, int(cursor)) if cursor else 0
    except ValueError as exc:
        raise HTTPException(400, detail="Invalid SSE replay cursor") from exc
    return StreamingResponse(_events(owner, generation, after), media_type="text/event-stream",
                             headers=_generator_headers(request_protocol(request, stored_version=generation.protocol_version)))


async def generation_status(request: Request):
    owner = _owner(request)
    generation = _generation_store().latest(owner, request.path_params["conversation_id"])
    protocol = request_protocol(request, stored_version=generation.protocol_version if generation else None)
    if generation is None:
        return JSONResponse({"active": False, "generationProtocolVersion": protocol},
                            headers=_generator_headers(protocol))
    active = generation.status in {"running", "requires_action"}
    pending = _generation_store().pending_action(owner, generation.run_id)
    return JSONResponse({
        "active": active,
        "status": generation.status,
        **({"pendingAction": pending} if pending is not None else {}),
        "streamId": generation.conversation_id,
        "createdAt": generation.generation_created_at,
        "elapsedMs": max(0, int(time.time() * 1000) - generation.generation_created_at),
        "generationProtocolVersion": protocol,
    }, headers=_generator_headers(protocol))


async def active_generations(request: Request):
    owner = _owner(request)
    with _database().connect() as db:
        rows = db.execute(
            "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
            "WHERE c.owner=? AND r.status IN ('running','requires_action') ORDER BY r.created_at DESC",
            (owner,),
        ).fetchall()
    protocol = request_protocol(request)
    jobs = [GenerationStore._run(row) for row in rows]
    running = [_generation_body(job, status="running",
                                protocol_version=min(protocol, job.protocol_version))
               for job in jobs]
    return JSONResponse({"jobs": running, "activeJobs": running,
                         "activeJobIds": [job["conversationId"] for job in running],
                         "generationProtocolVersion": protocol}, headers=_generator_headers(protocol))


async def abort_generation(request: Request):
    owner = _owner(request)
    payload = await _body(request)
    cid = payload.get("conversationId") or payload.get("streamId")
    if not isinstance(cid, str):
        raise HTTPException(400, detail="Conversation id is required")
    store = _generation_store()
    generation = store.latest(owner, cid)
    if generation is None:
        raise HTTPException(404, detail="Generation not found")
    protocol = request_protocol(request, payload, stored_version=generation.protocol_version)
    expected = payload.get("generationCreatedAt")
    if expected is not None and str(generation.generation_created_at) != str(expected):
        raise HTTPException(409, detail="Generation identity mismatch")
    if generation.status not in {"running", "requires_action"}:
        raise HTTPException(409, detail="Generation is not active")
    from .durable_tasks import cancel_run

    cancel_run(owner, generation.run_id)
    task = _TASKS.get(generation.run_id)
    if task and not task.done():
        task.cancel()
    else:
        store.finish(owner, generation.run_id, status="aborted")
    return JSONResponse({"success": True, "generationProtocolVersion": protocol},
                        headers=_generator_headers(protocol))


async def resume_generation(request: Request):
    owner = _owner(request)
    payload = await _body(request)
    cid = payload.get("conversationId")
    if not isinstance(cid, str):
        raise HTTPException(400, detail="Conversation id required")
    store = _generation_store()
    generation = store.latest(owner, cid)
    if generation is None:
        raise HTTPException(404, detail="Generation not found")
    protocol = request_protocol(request, payload, stored_version=generation.protocol_version)
    action_id = payload.get("actionId")
    if action_id is None:
        if generation.status != "running":
            raise HTTPException(409, detail="Generation cannot be resumed")
        expected = payload.get("generationCreatedAt")
        if expected is not None and str(generation.generation_created_at) != str(expected):
            raise HTTPException(409, detail="Generation identity mismatch")
        current = _TASKS.get(generation.run_id)
        if current is None or current.done():
            # A Controller restart loses only the ephemeral task handle. The
            # real AgentRunner and StateGraph checkpoint stores live in SQLite;
            # reattach using the SAME generation scheduler and owner grant.
            from .checkpoints import SQLiteCheckpointSaver
            from .machine_permissions import require_machine_scope, resolve_access
            from .routes import _repo

            saver = SQLiteCheckpointSaver(_database(), owner)
            checkpoint = saver.get_tuple(saver.config(cid, generation.run_id, event_actor=True))
            graph_checkpoint = saver.get_tuple(saver.config(
                cid, generation.run_id + ":graph:", event_actor=True))
            if checkpoint is None and graph_checkpoint is None:
                raise HTTPException(409, detail="Generation has no recoverable checkpoint")
            try:
                scopes, expiry = _request_grant(request)
                machine_policy = resolve_access(owner, cid)
                for machine, level in machine_policy.items():
                    if level in {"read", "write"}:
                        require_machine_scope(scopes, machine, level, expires=expiry)
            except PermissionError as exc:
                raise HTTPException(403, detail=str(exc)) from exc
            with _database().connect() as db:
                row = db.execute("SELECT state,agent_id FROM runs WHERE id=?", (generation.run_id,)).fetchone()
            state = json.loads(row["state"])
            try:
                profile = provider_config(state.get("provider") or "openai", state.get("model") or None)
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            agent = AgentRepository(_database()).get(owner, row["agent_id"]) if row["agent_id"] else None
            if row["agent_id"] and agent is None:
                raise HTTPException(404, detail="Agent no longer available")
            await _start_task(
                owner, generation, profile, agent,
                native_file_tools=any(level in {"read", "write"} for level in machine_policy.values()),
                write_tools=any(level == "write" for level in machine_policy.values()),
                ask_user_enabled=bool(state.get("askUserEnabled")),
                mcp_enabled=bool((_repo().setting(owner, "conversation.permissions." + cid, {}) or {}).get("mcp")),
                resume_history=store.history(owner, cid, message_id=generation.user_message_id),
                partial_text=store.accumulated_text(owner, generation.run_id),
                granted_scopes=frozenset(scopes), grant_expires=expiry,
            )
        return JSONResponse(_generation_body(generation, status="resumed", resumed=True, protocol_version=protocol),
                            headers=_generator_headers(protocol))

    if not isinstance(action_id, str) or not action_id:
        raise HTTPException(400, detail="Invalid human action id")
    if generation.status != "requires_action":
        raise HTTPException(409, detail="No pending human action")
    expected = payload.get("generationCreatedAt")
    if expected is not None and str(generation.generation_created_at) != str(expected):
        raise HTTPException(409, detail="Generation identity mismatch")
    try:
        # Confirm the user is still entitled to use the Agent before taking
        # the one-shot SQLite continuation claim.
        from .machine_permissions import require_machine_scope, resolve_access

        scopes, expiry = _request_grant(request)
        machine_policy = resolve_access(owner, cid)
        for machine, level in machine_policy.items():
            if level in {"read", "write"}:
                require_machine_scope(scopes, machine, level, expires=expiry)
        pending = store.pending_action(owner, generation.run_id)
        if pending is None or pending.get("actionId") != action_id:
            raise HTTPException(409, detail="Stale or mismatched human action")
        # Read and validate the provider before mutating SQLite. Failed config
        # cannot consume a one-shot answer and strand the pending generation.
        with _database().connect() as db:
            row = db.execute("SELECT state,agent_id FROM runs WHERE id=?", (generation.run_id,)).fetchone()
        state = json.loads(row["state"])
        profile = provider_config(state.get("provider") or "openai", state.get("model") or None)
        agent = AgentRepository(_database()).get(owner, row["agent_id"]) if row["agent_id"] else None
        paused_task = _TASKS.get(generation.run_id)
        if paused_task and not paused_task.done():
            await asyncio.wait_for(asyncio.shield(paused_task), timeout=5)
        approval = pending.get("payload", {}).get("type") == "tool_approval"
        approved_batch = None
        resume_namespace = pending.get("namespace", "")
        if approval:
            from .nested_mcp import _check_mcp_access

            decisions = payload.get("decisions")
            if not isinstance(decisions, list):
                raise HTTPException(400, detail="Tool approval decisions are required")
            if any(isinstance(decision, dict) and decision.get("decision") in {"approve", "edit"}
                   for decision in decisions):
                _check_mcp_access(owner, cid, scopes, execution=True) if any(
                    item.get("name") == "mcp_tool_call" for item in pending["payload"].get("action_requests", [])
                ) else None
            resumed, history, previous_text, approved_batch = store.claim_approval(
                owner, generation.run_id, action_id, decisions,
            )
        else:
            resumed, history, previous_text = store.answer_question(
                owner, generation.run_id, action_id, payload,
            )
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    from .routes import _repo

    await _start_task(owner, resumed, profile, agent,
                      native_file_tools=any(level in {"read", "write"} for level in machine_policy.values()),
                      write_tools=any(level == "write" for level in machine_policy.values()),
                      ask_user_enabled=bool(state.get("askUserEnabled")),
                      mcp_enabled=bool((_repo().setting(owner, "conversation.permissions." + cid, {}) or {}).get("mcp")),
                      resume_history=history, partial_text=previous_text,
                      approved_batch=approved_batch, resume_namespace=resume_namespace,
                      granted_scopes=frozenset(scopes), grant_expires=expiry)
    return JSONResponse(_generation_body(resumed, status="resumed", resumed=True, protocol_version=protocol),
                        headers=_generator_headers(protocol))


async def shutdown_generations() -> None:
    async with _TASK_GUARD:
        tasks = list(_TASKS.values())
        for task in tasks:
            _SHUTDOWN_TASKS.add(task)
            task.cancel()
    if tasks:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
    from .subagent_task_host import shutdown_subagent_tasks

    await shutdown_subagent_tasks()


def generation_routes() -> list[Route]:
    return [
        Route("/api/agents/chat/stream/{stream_id}", stream_generation, methods=["GET"]),
        Route("/api/agents/chat/status/{conversation_id}", generation_status, methods=["GET"]),
        Route("/api/agents/chat/active", active_generations, methods=["GET"]),
        Route("/api/agents/chat/abort", abort_generation, methods=["POST"]),
        Route("/api/agents/chat/resume", resume_generation, methods=["POST"]),
        Route("/api/agents/chat", start_generation, methods=["POST"]),
        Route("/api/agents/chat/{endpoint}", start_generation, methods=["POST"]),
    ]
