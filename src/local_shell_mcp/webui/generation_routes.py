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
from .generations import Generation, GenerationConflict, GenerationStore
from .providers import ProviderConfig, provider_config, stream_model
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
) -> None:
    repo = _generation_store()
    text_parts: list[str] = []
    params = parameters or {}
    step_id = "step_" + generation.run_id
    now_ms = int(time.time() * 1000)
    try:
        history = repo.history(owner, generation.conversation_id)
        if instructions:
            history.insert(0, {"role": "system", "content": instructions})
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
        async for chunk in stream_model(profile, history, max_tokens=max_tokens, temperature=temperature):
            if not chunk:
                continue
            text_parts.append(chunk)
            repo.append(owner, generation.run_id, {
                "event": "on_message_delta",
                "data": {
                    "id": step_id,
                    "delta": {
                        "content": {"type": "text", "text": chunk, "phase": "final_answer"},
                    },
                },
            })
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
                      agent: dict | None) -> None:
    async with _TASK_GUARD:
        existing = _TASKS.get(generation.run_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(
            _run_model(owner, generation, profile,
                       instructions=str((agent or {}).get("instructions") or ""),
                       parameters=(agent or {}).get("model_parameters") or {}),
            name="webui-generation-" + generation.run_id,
        )
        _TASKS[generation.run_id] = task


async def start_generation(request: Request):
    owner = _owner(request)
    payload = await _body(request)
    agent_id = payload.get("agent_id")
    agent = None
    if agent_id is not None:
        if not isinstance(agent_id, str):
            raise HTTPException(400, detail="Invalid agent identifier")
        agent = AgentRepository(_database()).get(owner, agent_id)
        if agent is None:
            raise HTTPException(404, detail="Agent not found")
    kind = str((agent or {}).get("provider") or payload.get("provider") or "openai")
    model = (agent or {}).get("model") or payload.get("model")
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
        await _start_task(owner, result, profile, agent)
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
    return JSONResponse({
        "active": active,
        "status": generation.status,
        "streamId": generation.conversation_id,
        "createdAt": generation.generation_created_at,
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
    generation = _generation_store().latest(owner, cid)
    if generation is None:
        raise HTTPException(404, detail="Generation not found")
    if generation.status != "running":
        raise HTTPException(409, detail="Generation cannot be resumed")
    return JSONResponse(_generation_body(generation, status="resumed", resumed=True),
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
