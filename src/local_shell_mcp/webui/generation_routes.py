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
import uuid
from collections.abc import AsyncIterator

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .agents import AgentRepository
from .ask_user_tools import ask_user_requested
from .generations import Generation, GenerationConflict, GenerationStore
from .providers import (
    ModelToolCall,
    ProviderConfig,
    provider_config,
    selected_provider,
    stream_model,
    stream_model_with_tools,
)
from .routes import _body, _owner

log = logging.getLogger(__name__)
_PROTOCOL = "2"
_TASKS: dict[str, asyncio.Task] = {}
_TASK_GUARD = asyncio.Lock()


def _database():
    from ..settings import get_settings
    from ..sqlite_store import shared_database

    return shared_database(get_settings().state_dir.resolve())


def _generation_store() -> GenerationStore:
    return GenerationStore(_database())


def _generation_body(job: Generation, *, status: str = "stream", resumed: bool = False) -> dict:
    return {
        "status": status,
        "streamId": job.conversation_id,
        "conversationId": job.conversation_id,
        "generationCreatedAt": job.generation_created_at,
        "generationProtocolVersion": 2,
        "resumed": resumed,
    }


def _generator_headers() -> dict[str, str]:
    return {
        "X-LibreChat-Generation-Protocol": _PROTOCOL,
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
    approved_mcp: tuple[ModelToolCall, str] | None = None,
    granted_scopes: frozenset[str] = frozenset(), grant_expires: int | None = None,
) -> None:
    repo = _generation_store()
    text_parts: list[str] = [partial_text] if partial_text else []
    params = parameters or {}
    step_id = "step_" + generation.run_id
    now_ms = int(time.time() * 1000)
    try:
        history = resume_history if resume_history is not None else repo.history(owner, generation.conversation_id, message_id=generation.user_message_id)
        if instructions and resume_history is None:
            history.insert(0, {"role": "system", "content": instructions})
        if resume_history is None:
            repo.append(owner, generation.run_id, {
                "event": "on_run_step",
                "data": {
                    "type": "message_creation", "id": step_id,
                    "runId": generation.response_message_id,
                    "index": 0, "created_at": now_ms, "status": "in_progress",
                    "stepDetails": {
                        "type": "message_creation",
                        "message_creation": {
                            "message_id": generation.response_message_id,
                            "content_type": "text", "phase": "final_answer",
                        },
                    },
                },
            })
        raw_max_tokens = params.get("max_tokens") or params.get("max_output_tokens") or 2048
        max_tokens = max(1, min(int(raw_max_tokens), 16384))
        temperature = params.get("temperature")
        if temperature is not None:
            temperature = max(0.0, min(float(temperature), 2.0))
        async def append_text(chunk: str) -> None:
            if not chunk:
                return
            text_parts.append(chunk)
            repo.append(owner, generation.run_id, {
                "event": "on_message_delta",
                "data": {"id": step_id,
                         "delta": {"content": {"type": "text", "text": chunk, "phase": "final_answer"}}},
            })

        if approved_mcp is not None:
            from .nested_mcp import approved_call

            call, decision = approved_mcp
            if decision == "approve":
                try:
                    result = await approved_call(
                        owner, generation.conversation_id, set(granted_scopes), call,
                    )
                except Exception as exc:
                    log.warning("Approved external MCP call failed: %s", type(exc).__name__)
                    result = "External MCP tool failed (" + type(exc).__name__ + ")"
            else:
                result = "User rejected the external MCP tool call."
            history.append({"role": "tool", "tool_call_id": call.call_id, "content": result})
            repo.append(owner, generation.run_id, {
                "event": "on_run_step",
                "data": {"type": "tool_calls", "id": "step_" + call.call_id,
                         "index": 1, "status": "completed",
                         "stepDetails": {"type": "tool_calls", "tool_calls": [{
                             "id": call.call_id, "type": "function", **call.history_metadata(),
                             "function": {"name": call.name, "arguments": "<redacted>"},
                             "status": "completed",
                         }]}}
            })
        model_tools = []
        if profile.provider in {"openai", "anthropic", "google"}:
            from .ask_user_tools import ASK_USER_TOOLS
            from .delegation import delegation_tools
            from .lsm_tool_registry import available_tools
            from .nested_mcp import nested_tools

            model_tools = (
                available_tools(owner, generation.conversation_id,
                                scopes=set(granted_scopes), expires=grant_expires) +
                (ASK_USER_TOOLS if ask_user_enabled else []) +
                (nested_tools() if mcp_enabled else []) +
                delegation_tools(parent_agent)
            )
        if model_tools:
            from .delegation import run_subagent
            from .lsm_tool_registry import call_tool
            from .nested_mcp import discover

            for round_number in range(3):
                calls: list[ModelToolCall] = []
                async for item in stream_model_with_tools(
                    profile, history, tools=model_tools,
                    max_tokens=max_tokens, temperature=temperature,
                ):
                    if isinstance(item, ModelToolCall):
                        calls.append(item)
                    else:
                        await append_text(item)
                if not calls:
                    break
                if round_number == 2 or len(calls) > 4:
                    raise ValueError("Model tool-call budget exceeded")
                external_calls = [call for call in calls if call.name == "mcp_tool_call"]
                if external_calls:
                    if not mcp_enabled or len(calls) != 1:
                        raise ValueError("Only one external MCP call can be approved per pause")
                    from .nested_mcp import _check_mcp_access

                    _check_mcp_access(owner, generation.conversation_id, set(granted_scopes))
                    calling = external_calls[0]
                    if (not isinstance(calling.arguments.get("name"), str) or
                        ":" not in calling.arguments["name"] or
                        not isinstance(calling.arguments.get("arguments", {}), dict)):
                        raise ValueError("Invalid external MCP tool arguments")
                    pending = {
                        "actionId": "action_" + uuid.uuid4().hex,
                        "streamId": generation.conversation_id,
                        "conversationId": generation.conversation_id,
                        "runId": generation.run_id,
                        "responseMessageId": generation.response_message_id,
                        "createdAt": int(time.time() * 1000),
                        "payload": {
                            "type": "tool_approval",
                            "action_requests": [{
                                "name": calling.name, "arguments": calling.arguments,
                                "tool_call_id": calling.call_id,
                                "description": "Approve an external MCP tool call",
                            }],
                            "review_configs": [{"action_name": calling.name,
                                                "tool_call_id": calling.call_id,
                                                "allowed_decisions": ["approve", "reject"]}],
                        },
                    }
                    history.append({
                        "role": "assistant", "content": None,
                        "tool_calls": [{"id": calling.call_id, "type": "function", **calling.history_metadata(),
                                        "function": {"name": calling.name,
                                                     "arguments": json.dumps(calling.arguments)}}],
                    })
                    repo.append(owner, generation.run_id, {
                        "event": "on_run_step",
                        "data": {"type": "tool_calls", "id": "step_" + calling.call_id,
                                 "index": round_number + 1, "status": "in_progress",
                                 "stepDetails": {"type": "tool_calls", "tool_calls": [{
                                     "id": calling.call_id, "type": "function", **calling.history_metadata(),
                                     "function": {"name": calling.name,
                                                  "arguments": json.dumps(calling.arguments)},
                                 }]}}
                    })
                    if not repo.pause_for_approval(owner, generation.run_id, pending, history,
                                                   "".join(text_parts)):
                        raise RuntimeError("Unable to park external MCP approval")
                    return
                delegated = [call for call in calls if call.name in {"delegate_agent", "handoff_agent"}]
                if delegated:
                    if len(calls) != 1:
                        raise ValueError("Only one subagent delegation is supported per model step")
                    deleg = delegated[0]
                    result = await run_subagent(owner, generation, parent_agent, deleg, _database())
                    repo.append(owner, generation.run_id, {
                        "event": "on_run_step",
                        "data": {"type": "tool_calls", "id": "step_" + deleg.call_id,
                                 "index": round_number + 1, "status": "completed",
                                 "stepDetails": {"type": "tool_calls", "tool_calls": [{
                                     "id": deleg.call_id, "type": "function", **deleg.history_metadata(),
                                     "function": {"name": deleg.name, "arguments": "<redacted>"},
                                     "status": "completed",
                                 }]}}
                    })
                    if deleg.name == "handoff_agent":
                        child_text = json.loads(result)["output"]
                        await append_text(child_text)
                        break
                    history.append({
                        "role": "assistant", "content": None,
                        "tool_calls": [{"id": deleg.call_id, "type": "function", **deleg.history_metadata(),
                                        "function": {"name": deleg.name,
                                                     "arguments": json.dumps(deleg.arguments)}}],
                    })
                    history.append({"role": "tool", "tool_call_id": deleg.call_id, "content": result})
                    continue
                asking = [call for call in calls if call.name == "ask_user_question"]
                if asking:
                    if not ask_user_enabled or len(calls) != 1:
                        raise ValueError("Only one Ask User question can be pending at a time")
                    from .ask_user_tools import build_ask_user_payload

                    question_payload = build_ask_user_payload(asking[0].arguments, asking[0].call_id)
                    history.append({
                        "role": "assistant", "content": None,
                        "tool_calls": [{"id": asking[0].call_id, "type": "function",
                                        "function": {"name": "ask_user_question",
                                                     "arguments": json.dumps(asking[0].arguments)}}],
                    })
                    pending = {
                        "actionId": "action_" + uuid.uuid4().hex,
                        "streamId": generation.conversation_id,
                        "conversationId": generation.conversation_id,
                        "runId": generation.run_id,
                        "responseMessageId": generation.response_message_id,
                        "createdAt": int(time.time() * 1000),
                        "payload": question_payload,
                    }
                    if not repo.pause_for_question(owner, generation.run_id, pending, history,
                                                   "".join(text_parts)):
                        raise RuntimeError("Unable to park Ask User generation")
                    return
                history.append({
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": call.call_id, "type": "function", **call.history_metadata(),
                                    "function": {"name": call.name,
                                                 "arguments": json.dumps(call.arguments)}}
                                   for call in calls],
                })
                for call in calls:
                    if call.name in {"mcp_tool_search", "mcp_tool_inspect"}:
                        result = await asyncio.wait_for(
                            discover(owner, generation.conversation_id, set(granted_scopes), call), timeout=10,
                        )
                        history.append({"role": "tool", "tool_call_id": call.call_id, "content": result})
                        continue
                    # Execute the original registered MCP callable. Its own
                    # argument validation, watchdog and Worker routing are
                    # retained; per-machine permission is checked first.
                    result = await call_tool(
                        owner, generation.conversation_id, call,
                        granted_scopes=set(granted_scopes), grant_expires=grant_expires,
                    )
                    repo.append(owner, generation.run_id, {
                        "event": "on_run_step",
                        "data": {"type": "tool_calls", "id": "step_" + call.call_id,
                                 "index": round_number + 1, "status": "completed",
                                 "stepDetails": {"type": "tool_calls", "tool_calls": [{
                                     "id": call.call_id, "type": "function", **call.history_metadata(),
                                     "function": {"name": call.name,
                                                  "arguments": "<redacted>"},
                                     "status": "completed",
                                 }]}}
                    })
                    history.append({"role": "tool", "tool_call_id": call.call_id, "content": result})
        else:
            async for chunk in stream_model(profile, history, max_tokens=max_tokens, temperature=temperature):
                await append_text(chunk)
        repo.append(owner, generation.run_id, {
            "event": "on_run_step_closed",
            "data": {
                "id": step_id, "index": 0, "type": "message_creation",
                "status": "completed", "runId": generation.response_message_id,
                "created_at": now_ms, "closed_at": int(time.time() * 1000),
            },
        })
        repo.finish(owner, generation.run_id, status="complete", text="".join(text_parts))
    except asyncio.CancelledError:
        repo.finish(owner, generation.run_id, status="aborted", text="".join(text_parts))
        raise
    except Exception as exc:
        # Do not put provider tokens, request metadata or secrets in response.
        log.warning("Model generation failed for %s: %s", generation.run_id, type(exc).__name__)
        repo.finish(owner, generation.run_id, status="error", text="".join(text_parts),
                    error=f"Model generation failed ({type(exc).__name__})")
    finally:
        async with _TASK_GUARD:
            _TASKS.pop(generation.run_id, None)


async def _start_task(owner: str, generation: Generation, profile: ProviderConfig,
                      agent: dict | None, native_file_tools: bool = False, write_tools: bool = False,
                      ask_user_enabled: bool = False, mcp_enabled: bool = False,
                      resume_history: list[dict] | None = None, partial_text: str = "",
                      approved_mcp: tuple[ModelToolCall, str] | None = None,
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
                       approved_mcp=approved_mcp,
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
    from ..auth import principal_scopes
    from ..settings import get_settings
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
    principal = getattr(request.state, "principal", None)
    scopes = ({"shell:read", "shell:write", "shell:execute", "remote:use"}
              if get_settings().auth_mode == "none" else
              principal_scopes(principal) if principal is not None and hasattr(principal, "claims") else set())
    grant_expires = None if get_settings().auth_mode == "none" else (
        principal.claims.get("exp") if principal is not None and hasattr(principal, "claims") else None
    )
    if requested_tools:
        try:
            for machine, level in policy.items():
                if level in {"read", "write"}:
                    require_machine_scope(scopes, machine, level, expires=grant_expires)
        except PermissionError as exc:
            raise HTTPException(403, detail=str(exc)) from exc
    try:
        profile = provider_config(kind, model)
        result, fresh = _generation_store().begin(owner, payload, agent)
    except GenerationConflict as exc:
        return JSONResponse(_generation_body(exc.existing, status="replaced"),
                            status_code=409, headers=_generator_headers())
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
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
                                         resumed=not fresh), status_code=202,
                        headers=_generator_headers())


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
                             headers=_generator_headers())


async def generation_status(request: Request):
    owner = _owner(request)
    generation = _generation_store().latest(owner, request.path_params["conversation_id"])
    if generation is None:
        return JSONResponse({"active": False, "generationProtocolVersion": 2},
                            headers=_generator_headers())
    active = generation.status in {"running", "requires_action"}
    pending = _generation_store().pending_action(owner, generation.run_id)
    return JSONResponse({
        "active": active,
        "status": generation.status,
        **({"pendingAction": pending} if pending is not None else {}),
        "streamId": generation.conversation_id,
        "createdAt": generation.generation_created_at,
        "elapsedMs": max(0, int(time.time() * 1000) - generation.generation_created_at),
        "generationProtocolVersion": 2,
    }, headers=_generator_headers())


async def active_generations(request: Request):
    owner = _owner(request)
    with _database().connect() as db:
        rows = db.execute(
            "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
            "WHERE c.owner=? AND r.status IN ('running','requires_action') ORDER BY r.created_at DESC",
            (owner,),
        ).fetchall()
    running = [_generation_body(GenerationStore._run(row), status="running") for row in rows]
    return JSONResponse({"jobs": running, "activeJobs": running,
                         "activeJobIds": [job["conversationId"] for job in running],
                         "generationProtocolVersion": 2}, headers=_generator_headers())


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
    expected = payload.get("generationCreatedAt")
    if expected is not None and str(generation.generation_created_at) != str(expected):
        raise HTTPException(409, detail="Generation identity mismatch")
    task = _TASKS.get(generation.run_id)
    if task and not task.done():
        task.cancel()
    else:
        store.finish(owner, generation.run_id, status="aborted")
    return JSONResponse({"success": True, "generationProtocolVersion": 2},
                        headers=_generator_headers())


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
    action_id = payload.get("actionId")
    if action_id is None:
        if generation.status != "running":
            raise HTTPException(409, detail="Generation cannot be resumed")
        return JSONResponse(_generation_body(generation, status="resumed", resumed=True),
                            headers=_generator_headers())

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
        from ..auth import principal_scopes
        from ..settings import get_settings
        from .machine_permissions import require_machine_scope, resolve_access

        principal = getattr(request.state, "principal", None)
        scopes = ({"shell:read", "shell:write", "shell:execute", "remote:use"}
                  if get_settings().auth_mode == "none" else
                  principal_scopes(principal) if principal is not None and hasattr(principal, "claims") else set())
        expiry = None if get_settings().auth_mode == "none" else (
            principal.claims.get("exp") if principal is not None and hasattr(principal, "claims") else None
        )
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
        approved_mcp = None
        if approval:
            from .nested_mcp import _check_mcp_access

            decisions = payload.get("decisions")
            if not isinstance(decisions, list) or len(decisions) != 1 or not isinstance(decisions[0], dict):
                raise HTTPException(400, detail="Exactly one tool approval decision is required")
            if decisions[0].get("decision") == "approve":
                _check_mcp_access(owner, cid, scopes, execution=True)
            resumed, history, previous_text, requested, decision = store.claim_approval(
                owner, generation.run_id, action_id, decisions,
            )
            approved_mcp = (ModelToolCall(requested["tool_call_id"], requested["name"],
                                          requested["arguments"]), decision)
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
                      approved_mcp=approved_mcp,
                      granted_scopes=frozenset(scopes), grant_expires=expiry)
    return JSONResponse(_generation_body(resumed, status="resumed", resumed=True),
                        headers=_generator_headers())


async def shutdown_generations() -> None:
    async with _TASK_GUARD:
        tasks = list(_TASKS.values())
        for task in tasks:
            task.cancel()
    if tasks:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)


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
