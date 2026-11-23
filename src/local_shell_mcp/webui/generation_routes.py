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
from .misc_routes import effective_features
from .artifact_prompts import agent_instructions, artifact_mode
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


def _prune_stale_task_handles() -> None:
    """Do not hand tasks tied to a terminated loop to a replacement loop.

    A Controller restart creates a fresh event loop; durable state is in SQLite,
    not in these ephemeral handles. Test in-process reloads can retain module
    globals across closed loops, so those handles must never enter gather().
    """
    for run_id, task in list(_TASKS.items()):
        if task.done() or task.get_loop().is_closed():
            if _TASKS.get(run_id) is task:
                _TASKS.pop(run_id, None)
            _SHUTDOWN_TASKS.discard(task)


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


def _last_open_message_step(store: GenerationStore, owner: str, run_id: str):
    """Restore the active final-answer step from trusted persisted SSE events.

    Steer boundaries close the preceding step and open a new one at a later
    content index. A resumed actor must not revert to the old index 0.
    """
    opened: dict[str, dict] = {}
    order: list[str] = []
    closed: set[str] = set()
    def replay_events():
        cursor = 0
        while True:
            page = store.events(owner, run_id, cursor, limit=200)
            if not page:
                return
            for _, event in page:
                yield event
            cursor = page[-1][0]
            if len(page) < 200:
                return

    for event in replay_events():
        data = event.get('data') or {}
        if event.get('event') == 'on_run_step' and data.get('type') == 'message_creation':
            identifier = data.get('id')
            if (isinstance(identifier, str) and isinstance(data.get('index'), int)
                    and data.get('index') >= 0):
                opened[identifier] = data
                order.append(identifier)
        elif event.get('event') == 'on_run_step_closed' and isinstance(data.get('id'), str):
            closed.add(data['id'])
    for identifier in reversed(order):
        if identifier in opened and identifier not in closed:
            item = opened[identifier]
            return identifier, item['index'], item.get('created_at')
    return None
def _recovered_terminal_steps(store, owner: str, run_id: str, visible_text: str) -> list[dict] | None:
    """Keep safely streamed assistant text after a durable tool checkpoint.

    A provider abort has no completed model checkpoint for its unfinished answer,
    but that answer has already been displayed and must remain in model history.
    Do not resurrect unmatched tool calls from an interrupted model turn.
    """
    steps = store.checkpoint_model_steps(owner, run_id)
    if steps is None:
        return None
    from copy import deepcopy

    recovered = deepcopy(steps)
    prior_text = ''.join(step['content'] for step in recovered
                         if step.get('role') == 'assistant' and isinstance(step.get('content'), str))
    if visible_text and visible_text.startswith(prior_text):
        remaining = visible_text[len(prior_text):]
    elif visible_text and visible_text != prior_text:
        remaining = visible_text
    else:
        remaining = ''
    if remaining:
        if recovered and recovered[-1].get('role') == 'assistant' and isinstance(recovered[-1].get('content'), str):
            recovered[-1]['content'] += remaining
        else:
            recovered.append({'role': 'assistant', 'content': remaining})
    return recovered


async def _run_model(
    owner: str, generation: Generation, profile: ProviderConfig,
    *, instructions: str = "", parameters: dict | None = None,
    native_file_tools: bool = False, write_tools: bool = False,
    ask_user_enabled: bool = False, mcp_enabled: bool = False,
    parent_agent: dict | None = None,
    resume_history: list[dict] | None = None, partial_text: str = "",
    approved_batch=None, resume_namespace: str = "",
    granted_scopes: frozenset[str] = frozenset(), grant_expires: int | None = None,
    wakeup_lease: tuple[str, str] | None = None,
    event_delivery_lease: tuple[str, str] | None = None,
    actor_lease=None,
    recovery_steers: bool = False,
) -> None:
    repo = _generation_store()
    heartbeat = asyncio.create_task(actor_lease.keep_alive(), name="generation-lease-" + generation.run_id) \
        if actor_lease is not None else None
    text_parts: list[str] = [partial_text] if partial_text else []
    params = parameters or {}
    step_id = "step_" + generation.run_id
    step_index = 0
    needs_post_tool_step = False
    now_ms = int(time.time() * 1000)
    memory_task: asyncio.Task | None = None
    if resume_history is not None:
        # A human continuation must append into the last text step, which may
        # have been advanced past a STEER part before suspension.
        with _database().connect() as db:
            prior = db.execute(
                "SELECT data FROM generation_events WHERE run_id=? "
                "AND json_extract(data,'$.event')='on_run_step' ORDER BY seq DESC LIMIT 1",
                (generation.run_id,),
            ).fetchone()
        if prior:
            saved = json.loads(prior['data']).get('data') or {}
            if saved.get('type') == 'message_creation' and isinstance(saved.get('id'), str):
                step_id = saved['id']
                step_index = saved.get('index', 0)
                now_ms = saved.get('created_at', now_ms)

    def check_wakeup_lease():
        if actor_lease is not None:
            actor_lease.assert_current()
        if wakeup_lease is not None:
            from .subagent_wakeup import assert_wakeup_lease

            assert_wakeup_lease(repo.database, owner, generation.run_id, wakeup_lease)
        if event_delivery_lease is not None:
            from .event_triggers import assert_event_lease

            assert_event_lease(repo.database, owner, generation.run_id, event_delivery_lease)

    try:
        from .agent_runner import AgentRunner
        from .agent_runtime import AgentSuspended

        if recovery_steers and resume_history is not None and actor_lease is not None:
            # Hold the unique run lease before modifying the durable SSE log.
            # A model turn streaming after its last checkpoint is provisional;
            # its suffix is regenerated after Controller restart, not resumed.
            already_visible = repo.accumulated_text(owner, generation.run_id)
            if already_visible != partial_text:
                if not already_visible.startswith(partial_text):
                    raise RuntimeError('Recovered checkpoint text conflicts with streamed reply')
                repo.append(owner, generation.run_id, {'event': 'on_content_rewind',
                    'data': {'preserveText': partial_text, 'runId': generation.response_message_id}}, actor_lease=actor_lease)
        history = resume_history if resume_history is not None else repo.history(
            owner, generation.conversation_id, message_id=generation.user_message_id,
        )
        if instructions and resume_history is None:
            history.insert(0, {"role": "system", "content": instructions})
        if parent_agent is not None and resume_history is None:
            from .attachments import with_agent_context

            history = with_agent_context(_database(), owner, parent_agent, history)
        recovered_step = (_last_open_message_step(repo, owner, generation.run_id)
                          if resume_history is not None else None)
        if recovered_step is not None:
            step_id, step_index, created = recovered_step
            now_ms = created if isinstance(created, int) else now_ms
        else:
            if resume_history is not None:
                snapshot, _ = repo.resume_snapshot(owner, generation.run_id)
                step_index = len(snapshot['aggregatedContent'])
                step_id = f"step_{generation.run_id}_after_resume_{step_index}"
            check_wakeup_lease()
            repo.append(owner, generation.run_id, {
                "event": "on_run_step", "data": {
                    "type": "message_creation", "id": step_id,
                    "runId": generation.response_message_id, "index": step_index,
                    "created_at": now_ms, "status": "in_progress",
                    "stepDetails": {"type": "message_creation", "message_creation": {
                        "message_id": generation.response_message_id,
                        "content_type": "text", "phase": "final_answer",
                    }},
                },
            }, actor_lease=actor_lease)

        async def append_text(chunk):
            nonlocal needs_post_tool_step
            check_wakeup_lease()
            if not chunk:
                return
            if needs_post_tool_step:
                needs_post_tool_step = False
                await _open_followup_step('after_tool')
            text_parts.append(chunk)
            repo.append(owner, generation.run_id, {
                "event": "on_message_delta", "data": {
                    "id": step_id, "delta": {"content": {
                        "type": "text", "text": chunk, "phase": "final_answer",
                    }},
                },
            }, actor_lease=actor_lease)

        async def _open_followup_step(reason):
            nonlocal step_id, step_index, now_ms, needs_post_tool_step
            check_wakeup_lease()
            needs_post_tool_step = False
            # Upstream reserves an absolute content slot per message_creation.
            # Once a STEER part occupies the next slot, subsequent provider
            # text must use a *new* runStep index or useStepHandler appends it
            # into the old text block before the visible steer.
            closed_at = int(time.time() * 1000)
            repo.append(owner, generation.run_id, {
                "event": "on_run_step_closed", "data": {
                    "id": step_id, "index": step_index, "type": "message_creation",
                    "status": "completed", "runId": generation.response_message_id,
                    "created_at": now_ms, "closed_at": closed_at,
                },
            }, actor_lease=actor_lease)
            snapshot, _ = repo.resume_snapshot(owner, generation.run_id)
            step_index = len(snapshot["aggregatedContent"])
            step_id = f"step_{generation.run_id}_{reason}_{step_index}"
            now_ms = closed_at
            repo.append(owner, generation.run_id, {
                "event": "on_run_step", "data": {
                    "type": "message_creation", "id": step_id,
                    "runId": generation.response_message_id, "index": step_index,
                    "created_at": now_ms, "status": "in_progress",
                    "stepDetails": {"type": "message_creation", "message_creation": {
                        "message_id": generation.response_message_id,
                        "content_type": "text", "phase": "final_answer",
                    }},
                },
            }, actor_lease=actor_lease)

        async def on_injected():
            await _open_followup_step('after_steer')

        async def on_tool_completed(_call):
            nonlocal needs_post_tool_step
            # The Controller's tool-completion event is already durable. Only
            # the *next provider text* opens another text slot, avoiding empty
            # message steps on tool-only turns and keeping React indices exact.
            needs_post_tool_step = True

        runner = AgentRunner(owner, generation, _database(), repo,
                             scopes=granted_scopes, grant_expires=grant_expires,
                             stream_tools=stream_model_with_tools, stream_text=stream_model,
                             on_text=append_text, agent=parent_agent, profile=profile,
                             parameters=params, ask_user_enabled=ask_user_enabled,
                             mcp_enabled=mcp_enabled, resume_history=resume_history,
                             resume_namespace=resume_namespace, partial_text=partial_text,
                             approved_batch=approved_batch, on_injected=on_injected,
                             on_tool_completed=on_tool_completed,
                             wakeup_lease=wakeup_lease, event_delivery_lease=event_delivery_lease,
                             actor_lease=actor_lease, recovery_steers=recovery_steers)
        # Only the first entry determines this run's prefix. After human
        # actions, resume_history/checkpoints already contain prior run steps.
        original_boundary = len(history) if resume_history is None else len(
            repo.history(owner, generation.conversation_id, message_id=generation.user_message_id)
        ) + int(bool(instructions))
        history_start = repo.model_history_boundary(
            owner, generation.run_id, initial=original_boundary,
        )
        try:
            if resume_history is None and not repo.manual_compaction(owner, generation.run_id):
                from .memory_agent import run_automatic_memory

                memory_task = asyncio.create_task(run_automatic_memory(
                    owner, generation, _database(), history, root_agent=parent_agent,
                    stream_tools=stream_model_with_tools,
                    grant_expires=grant_expires),
                    name='webui-memory-' + generation.run_id)
            finished_messages = await runner.run(history)
        except AgentSuspended:
            return
        if memory_task is not None:
            try:
                await memory_task
            except Exception as exc:
                # The original AgentClient.runMemory isolates extraction
                # failures: a misconfigured opt-in memory model must never
                # discard the user's successful primary answer.
                log.warning("Automatic Memory extraction failed (%s)", type(exc).__name__)
        check_wakeup_lease()
        repo.append(owner, generation.run_id, {
            "event": "on_run_step_closed", "data": {
                "id": step_id, "index": step_index, "type": "message_creation",
                "status": "completed", "runId": generation.response_message_id,
                "created_at": now_ms, "closed_at": int(time.time() * 1000),
            },
        }, actor_lease=actor_lease)
        from .message_dto import model_steps

        # A handoff may replace system instructions, changing the context
        # prefix length. Locate the original request within the final graph
        # state so the response is not discarded by a stale numeric offset.
        post_compaction_start = repo.compacted_model_history_boundary(owner, generation.run_id)
        if post_compaction_start is not None:
            # The original prompt can be removed by a successful summary. The
            # new model-history boundary is committed with that checkpoint.
            history_start = post_compaction_start
        elif history_start > 0:
            source_user = next((message for message in reversed(history[:history_start])
                                if message.get('role') == 'user'), None)
            if source_user is not None:
                # The runner can prepend a memory system message after this
                # boundary is calculated. Anchor on the actual submitted user
                # message, even when the output list grew by exactly one.
                matched = [index for index, message in enumerate(finished_messages)
                           if message == source_user]
                if matched:
                    history_start = matched[-1] + 1
                elif len(finished_messages) <= history_start:
                    history_start = 0
            elif len(finished_messages) <= history_start:
                history_start = 0
        repo.finish(owner, generation.run_id, status="complete", text=runner.partial_text,
                    model_steps=model_steps(finished_messages, history_start), actor_lease=actor_lease)
    except asyncio.CancelledError:
        if wakeup_lease is not None or event_delivery_lease is not None or actor_lease is not None:
            check_wakeup_lease()
        current = repo.get(owner, generation.run_id)
        pending = repo.pending_action(owner, generation.run_id) if current and current.status == "requires_action" else None
        if (asyncio.current_task() not in _SHUTDOWN_TASKS and
                not (pending and pending.get("payload", {}).get("type") == "action_oauth")):
            repo.finish(owner, generation.run_id, status="aborted", text="".join(text_parts),
                        model_steps=_recovered_terminal_steps(repo, owner, generation.run_id,
                                                             "".join(text_parts)), actor_lease=actor_lease)
        raise
    except Exception as exc:
        # A former controller cannot publish failure after its lease changed.
        if wakeup_lease is not None or event_delivery_lease is not None or actor_lease is not None:
            try:
                check_wakeup_lease()
            except Exception:
                return
        # Do not put provider tokens, request metadata or secrets in response.
        log.warning("Model generation failed for %s: %s", generation.run_id, type(exc).__name__)
        repo.finish(owner, generation.run_id, status="error", text="".join(text_parts),
                    error=f"Model generation failed ({type(exc).__name__})",
                    model_steps=_recovered_terminal_steps(repo, owner, generation.run_id,
                                                             "".join(text_parts)), actor_lease=actor_lease)
    finally:
        if memory_task is not None and not memory_task.done():
            memory_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await memory_task
        if heartbeat is not None:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if actor_lease is not None:
            actor_lease.release()
        _SHUTDOWN_TASKS.discard(asyncio.current_task())
        async with _TASK_GUARD:
            if _TASKS.get(generation.run_id) is asyncio.current_task():
                _TASKS.pop(generation.run_id, None)


async def _start_task(owner: str, generation: Generation, profile: ProviderConfig,
                      agent: dict | None, native_file_tools: bool = False, write_tools: bool = False,
                      ask_user_enabled: bool = False, mcp_enabled: bool = False,
                      artifacts_mode: str | None = None,
                      resume_history: list[dict] | None = None, partial_text: str = "",
                      approved_batch=None, resume_namespace: str = "",
                      granted_scopes: frozenset[str] = frozenset(), grant_expires: int | None = None,
                      wakeup_lease: tuple[str, str] | None = None,
                      event_delivery_lease: tuple[str, str] | None = None,
                      recovery_steers: bool = False,
                      oauth_claim: tuple[str, str, int, bool] | None = None,
                      checkpoint_text: str | None = None) -> bool:
    from .generation_actor_lease import ActorLease

    previous = _TASKS.get(generation.run_id)
    if oauth_claim is not None and previous is not None and not previous.done():
        try:
            await asyncio.wait_for(asyncio.shield(previous), timeout=5)
        except TimeoutError:
            return False
    async with _TASK_GUARD:
        _prune_stale_task_handles()
        existing = _TASKS.get(generation.run_id)
        if existing and not existing.done():
            return False
        if oauth_claim is not None:
            action_id, call_id, version, lone_call = oauth_claim
            claimed = _generation_store().claim_oauth(owner, generation.run_id, action_id, call_id,
                                                      version, lone_call=lone_call)
            if claimed is None:
                return False
            generation, resume_history, partial_text = claimed
        actor_lease = ActorLease.claim(_database(), owner, generation.run_id)
        if actor_lease is None:
            return False
        if checkpoint_text is not None:
            try:
                _generation_store().rewind_running_to_checkpoint(
                    owner, generation.run_id, checkpoint_text, actor_lease=actor_lease)
            except Exception:
                actor_lease.release()
                raise
        task = asyncio.create_task(
            _run_model(owner, generation, profile,
                       instructions=agent_instructions(agent, profile.provider, artifacts_mode),
                       parameters=(agent or {}).get("model_parameters") or {},
                       native_file_tools=native_file_tools, write_tools=write_tools,
                       ask_user_enabled=ask_user_enabled, mcp_enabled=mcp_enabled,
                       parent_agent=agent,
                       resume_history=resume_history, partial_text=partial_text,
                       approved_batch=approved_batch, resume_namespace=resume_namespace,
                       granted_scopes=granted_scopes, grant_expires=grant_expires,
                       wakeup_lease=wakeup_lease, event_delivery_lease=event_delivery_lease,
                       actor_lease=actor_lease, recovery_steers=recovery_steers),
            name="webui-generation-" + generation.run_id,
        )
        _TASKS[generation.run_id] = task
        return True


async def _resume_ready_oauth(owner: str, generation: Generation,
                              scopes: set[str], expiry: int | None,
                              *, action_id: str | None = None,
                              call_id: str | None = None,
                              version: int | None = None) -> bool:
    """Resume only a saved, authorized Action after a fresh LSM grant.

    An OAuth IdP callback has no bearer token and is not itself a machine
    grant. The browser's current authenticated connection supplies the scopes
    for any follow-on LSM tools; no scopes or bearer tokens are persisted.
    """
    if generation.status != "requires_action":
        return False
    store = _generation_store()
    pending = store.pending_action(owner, generation.run_id)
    if not isinstance(pending, dict):
        return False
    payload = pending.get("payload") or {}
    if payload.get("type") != "action_oauth":
        return False
    aid, cid, rev = payload.get("action_id"), payload.get("tool_call_id"), payload.get("action_version")
    if (not isinstance(aid, str) or not isinstance(cid, str) or type(rev) is not int
            or action_id is not None and action_id != aid
            or call_id is not None and call_id != cid
            or version is not None and version != rev):
        return False
    from .action_oauth import access_token
    from .actions import ActionRepository
    from .checkpoints import SQLiteCheckpointSaver
    from .machine_permissions import require_machine_scope, resolve_access
    from .routes import _repo

    database = _database()
    with database.connect() as conn:
        row = conn.execute("SELECT state,agent_id FROM runs WHERE id=?", (generation.run_id,)).fetchone()
    if row is None or not row["agent_id"]:
        return False
    state = json.loads(row["state"])
    agents = AgentRepository(database)
    agent = agents.get(owner, row["agent_id"])
    if agent is None:
        return False
    # The root graph owns the conversation, but the originating member owns
    # the Action binding and its OAuth credentials. Authenticate the member
    # against the admitted graph topology and the durable task namespace.
    action_agent = agent
    namespace = pending.get("namespace", "")
    if not isinstance(namespace, str):
        return False
    import re

    identities = re.findall(r"(?:^|/)graph:([^/:]+):[^/]+", namespace)
    if identities:
        from .graph_topology import admit_agent_graph

        try:
            topology = admit_agent_graph(owner, agent, agents)
        except (ValueError, PermissionError):
            return False
        member_id = identities[-1]
        if topology is None or member_id not in (topology.reachable_agent_ids or topology.agent_ids):
            return False
        action_agent = agents.get(owner, member_id)
        if action_agent is None:
            return False
    record = ActionRepository(database).get_for_tool(owner, action_agent["id"], payload.get("tool_name"))
    if record is None or record[2]["action_id"] != aid or record[2]["action_version"] != rev:
        return False
    # Reattaching after a restart requires a checkpoint with the exact model
    # tool ID; never ask the model again merely to reconstruct the proposal.
    saver = SQLiteCheckpointSaver(database, owner)
    checkpoint = saver.get_tuple(saver.config(generation.conversation_id, generation.run_id,
                                              checkpoint_ns=pending.get("namespace", ""), event_actor=True))
    if checkpoint is None:
        return False
    calls = checkpoint["checkpoint"]["channel_values"].get("pending_calls") or []
    if not any(call.get("call_id") == cid and call.get("name") == payload.get("tool_name") for call in calls):
        # Recovery after a post-tool checkpoint is safe when the completed
        # Action's output was persisted and the saved graph has advanced.
        if calls != [] or payload.get("checkpoint_completed") is not True:
            return False
        with database.connect() as conn:
            persisted = conn.execute(
                "SELECT 1 FROM generation_events WHERE run_id=? AND "
                "json_extract(data,'$.event')='on_run_step_completed' AND "
                "json_extract(data,'$.data.result.tool_call.id')=? LIMIT 1",
                (generation.run_id, cid),
            ).fetchone()
        if not persisted:
            return False
    # Revalidate current LSM machine grants before even contacting an IdP
    # refresh endpoint or rotating an expired browser authorization state.
    policy = resolve_access(owner, generation.conversation_id)
    for machine, level in policy.items():
        if level in {"read", "write"}:
            require_machine_scope(scopes, machine, level, expires=expiry)
    repo = ActionRepository(database)
    if not await access_token(repo, owner, aid):
        from .action_oauth import begin_flow

        # A changed public origin or revoked IdP allowlist must not turn
        # an otherwise healthy status/SSE endpoint into a 500.
        with contextlib.suppress(ValueError, PermissionError):
            begin_flow(repo, owner, aid, generation.run_id, cid,
                       reissue={"tool_name": payload["tool_name"]})
        return False
    profile = provider_config(state.get("provider") or "openai", state.get("model") or None)
    flags = effective_features(owner, generation.conversation_id)
    started = await _start_task(owner, generation, profile, agent,
                      native_file_tools=any(level in {"read", "write"} for level in policy.values()),
                      write_tools=any(level == "write" for level in policy.values()),
                      ask_user_enabled=bool(state.get("askUserEnabled")),
                      mcp_enabled=isinstance(flags, dict) and flags.get("mcp") is True,
                      resume_namespace=pending.get("namespace", ""), granted_scopes=frozenset(scopes),
                      grant_expires=expiry, oauth_claim=(aid, cid, rev,
                          len(calls) == 1 or payload.get("checkpoint_completed") is True))
    return bool(started)


async def resume_oauth_callback(owner: str, run_id: str, action_id: str,
                                call_id: str, version: int, request: Request) -> bool:
    """The provider popup may reuse an active LSM web session, never OAuth CSRF as scope."""
    from ..settings import get_settings
    from .auth import COOKIE, _store

    generation = _generation_store().get(owner, run_id)
    if generation is None:
        return False
    if get_settings().auth_mode == "none":
        from ..oauth import ALL_OAUTH_SCOPES

        scopes, expiry = set(ALL_OAUTH_SCOPES), None
    else:
        session = _store().session(request.cookies.get(COOKIE, ""))
        if session is None or session.owner != owner:
            return False
        scopes, expiry = set(session.scopes.split()), session.grant_until
    try:
        return await _resume_ready_oauth(owner, generation, scopes, expiry,
                                         action_id=action_id, call_id=call_id, version=version)
    except (KeyError, ValueError, PermissionError):
        # The token is saved, but execution must await another authenticated
        # browser attachment with sufficient current machine permissions.
        return False


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
    # Apply configured source-specific policy before SQLite claims a run or
    # emits SSE. Bad content is never persisted or sent to the model.
    from .content_filters import (
        ContentFilterBlocked,
        validate_agent_instructions,
        validate_message_submission,
        validate_model_parameters,
    )
    from .memory_protection import configured_filters
    from .storage import WorkspaceRepository

    filters = configured_filters(WorkspaceRepository(_database()), owner)
    try:
        if isinstance(payload.get('text'), str):
            validate_message_submission(payload['text'], filters)
        # History prefers structured content parts to the top-level text.
        # Enforce the same submission policy before the run is admitted.
        projected_text_parts = []
        for part in payload.get('content') if isinstance(payload.get('content'), list) else []:
            if isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str):
                validate_message_submission(part['text'], filters)
                projected_text_parts.append(part['text'])
        if projected_text_parts:
            validate_message_submission(''.join(projected_text_parts), filters)
        validate_agent_instructions(str((agent or {}).get('instructions') or ''), filters)
        params = (agent or {}).get('model_parameters') or payload.get('model_parameters')
        if isinstance(params, dict):
            validate_model_parameters({'model_parameters': params}, filters)
    except ContentFilterBlocked as blocked:
        return JSONResponse(blocked.response(), status_code=400)
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

        mcp_enabled = effective_features(owner, result.conversation_id)["mcp"]
        await _start_task(owner, result, profile, agent, native_file_tools=requested_tools,
                          write_tools=any(level == "write" for level in policy.values()),
                          ask_user_enabled=ask_user_enabled, mcp_enabled=mcp_enabled,
                          artifacts_mode=artifact_mode(payload, agent),
                          granted_scopes=frozenset(scopes), grant_expires=grant_expires)
    return JSONResponse(_generation_body(result, status="stream" if fresh else "resumed",
                                         resumed=not fresh, protocol_version=protocol), status_code=202,
                        headers=_generator_headers(protocol))


async def _events(owner: str, generation: Generation, after: int = 0,
                  *, resume: bool = False) -> AsyncIterator[bytes]:
    store = _generation_store()
    last = max(0, after)
    if resume:
        snapshot, watermark = store.resume_snapshot(owner, generation.run_id)
        if watermark > last:
            last = watermark
        yield ("data: " + json.dumps({
            "sync": True, "resumeState": snapshot, "pendingEvents": [],
            "generationProtocolVersion": generation.protocol_version,
        }, ensure_ascii=False, separators=(",", ":")) + "\n\n").encode()
        # The React resumeState projection restores text/tool cards, while
        # attachmentHandler consumes independent SSE attachment events. A
        # disconnected browser has none of these attachments in memory.
        # Reproject owner-bound attachments at the captured watermark before
        # live replay; leave the sequence cursor unchanged to avoid rollback.
        cursor = 0
        while cursor < watermark:
            batch = store.events(owner, generation.run_id, cursor)
            if not batch:
                break
            for seq, item in batch:
                if seq > watermark:
                    break
                if item.get('event') == 'attachment' and isinstance(item.get('data'), dict):
                    yield ('data: ' + json.dumps(item, ensure_ascii=False,
                           separators=(',', ':')) + '\n\n').encode()
                cursor = seq
            if cursor >= watermark:
                break
        # The sync snapshot does not signal terminal completion to React.
        # Re-send a final event already included in the cursor watermark.
        if watermark > after:
            finished = store.events(owner, generation.run_id, watermark - 1, limit=1)
            if finished and finished[0][1].get("final"):
                seq, value = finished[0]
                yield (f"id: {seq}\ndata: " + json.dumps(value, ensure_ascii=False,
                      separators=(",", ":")) + "\n\n").encode()
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
    try:
        scopes, expiry = _request_grant(request)
        await _resume_ready_oauth(owner, generation, scopes, expiry)
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    cursor = request.headers.get("last-event-id") or request.query_params.get("after")
    try:
        after = max(0, int(cursor)) if cursor else 0
    except ValueError as exc:
        raise HTTPException(400, detail="Invalid SSE replay cursor") from exc
    resume = request.query_params.get("resume") == "true"
    if resume and generation.status == "running":
        await _reattach_running_actor(request, owner, generation)
    return StreamingResponse(_events(owner, generation, after, resume=resume),
                             media_type="text/event-stream",
                             headers=_generator_headers(request_protocol(request, stored_version=generation.protocol_version)))


async def generation_status(request: Request):
    owner = _owner(request)
    generation = _generation_store().latest(owner, request.path_params["conversation_id"])
    protocol = request_protocol(request, stored_version=generation.protocol_version if generation else None)
    if generation is None:
        return JSONResponse({"active": False, "generationProtocolVersion": protocol},
                            headers=_generator_headers(protocol))
    try:
        scopes, expiry = _request_grant(request)
        if await _resume_ready_oauth(owner, generation, scopes, expiry):
            generation = _generation_store().get(owner, generation.run_id) or generation
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    active = generation.status in {"running", "requires_action"}
    store = _generation_store()
    pending = store.client_pending_action(store.pending_action(owner, generation.run_id))
    resume_state, _ = store.resume_snapshot(owner, generation.run_id)
    from .steering import _public

    with _database().connect() as db:
        row = db.execute("SELECT state FROM runs WHERE id=?", (generation.run_id,)).fetchone()
    run_state = json.loads(row["state"]) if row else {}
    leftovers = (run_state.get("steering") or {}).get("leftovers") or []
    return JSONResponse({
        "active": active,
        "status": generation.status,
        **({"unrecoveredSteers": [_public(item) for item in leftovers]} if leftovers else {}),
        **({"pendingAction": pending} if pending is not None else {}),
        "resumeState": resume_state,
        "aggregatedContent": resume_state["aggregatedContent"],
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


async def steer_generation(request: Request):
    """Original React steering POST contract, no provider-bound side effects on replay."""
    from .steering import SteeringStore, SteerRejection

    owner = _owner(request)
    body = await _body(request)
    protocol = request_protocol(request, body)
    store = SteeringStore(_database())
    cid = body.get("conversationId")
    if isinstance(cid, str):
        current = _generation_store().latest(owner, cid)
        if (current is not None and current.agent_id and
            AgentRepository(_database()).get(owner, current.agent_id) is None):
            return JSONResponse({"code": "FORBIDDEN", "generationProtocolVersion": protocol},
                                status_code=403, headers=_generator_headers(protocol))
        if current is not None:
            # Model-bound instructions cannot bypass revoked machine scopes
            # merely because the originating generation still exists.
            from .machine_permissions import require_machine_scope, resolve_access

            scopes, expiry = _request_grant(request)
            try:
                policy = resolve_access(owner, cid)
                for machine, level in policy.items():
                    if level in {"read", "write"}:
                        require_machine_scope(scopes, machine, level, expires=expiry)
            except (PermissionError, KeyError):
                return JSONResponse({"code": "FORBIDDEN", "generationProtocolVersion": protocol},
                                    status_code=403, headers=_generator_headers(protocol))
    try:
        result = store.enqueue(owner, body, preempt_capable=True,
                               strict_delivery=request.url.path.endswith("/deliver"))
    except SteerRejection as exc:
        return JSONResponse({**exc.body, "generationProtocolVersion": protocol},
                            status_code=exc.status, headers=_generator_headers(protocol))
    return JSONResponse({**result, "generationProtocolVersion": protocol},
                        status_code=202, headers=_generator_headers(protocol))

async def mutate_steer(request: Request):
    from .steering import SteeringStore, SteerRejection

    owner = _owner(request)
    body = await _body(request)
    protocol = request_protocol(request, body)
    arm = request.url.path.endswith("/arm")
    try:
        result = SteeringStore(_database()).mutate(owner, body, arm=arm, preempt_capable=True)
    except SteerRejection as exc:
        return JSONResponse({**exc.body, "generationProtocolVersion": protocol},
                            status_code=exc.status, headers=_generator_headers(protocol))
    return JSONResponse({**result, "generationProtocolVersion": protocol},
                        headers=_generator_headers(protocol))


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
    from .steering import SteeringStore

    pending_steers = SteeringStore(_database()).pending(owner, generation.run_id)
    cancel_run(owner, generation.run_id)
    task = _TASKS.get(generation.run_id)
    # Explicit user abort wins over a concurrently parked OAuth/approval step.
    # The terminal transaction precedes cancellation so a crash cannot make
    # this run accidentally resumable after the user revoked consent.
    store.finish(owner, generation.run_id, status="aborted")
    if task and not task.done():
        task.cancel()
    return JSONResponse({"success": True, "generationProtocolVersion": protocol,
                         **({"pendingSteers": pending_steers} if pending_steers else {})},
                        headers=_generator_headers(protocol))


async def _reattach_running_actor(request: Request, owner: str, generation: Generation) -> None:
    """Fresh-request authorization for reconnecting a checkpointed root actor.

    No controller startup process can inherit a machine grant or run tools.
    Live foreign actors remain the unique owners of the run and only get SSE.
    """
    from .checkpoints import SQLiteCheckpointSaver
    from .generation_actor_lease import active_run_ids
    from .machine_permissions import require_machine_scope, resolve_access
    from .routes import _repo

    # Detached subagent child generations are owned by their task host.
    # Foreground reconnect may observe SSE, but never claim their actor lease.
    with _database().connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='subagent_tasks'").fetchone():
            child = db.execute(
                "SELECT 1 FROM subagent_tasks WHERE owner=? AND child_run_id=? LIMIT 1",
                (owner, generation.run_id)).fetchone()
            if child is not None:
                raise HTTPException(409, detail="Detached subagent runs require task-host recovery")
    current = _TASKS.get(generation.run_id)
    if current is not None and not current.done():
        return
    if generation.run_id in active_run_ids(_database()):
        return
    cid = generation.conversation_id
    saver = SQLiteCheckpointSaver(_database(), owner)
    checkpoint = saver.get_tuple(saver.config(cid, generation.run_id, event_actor=True))
    graph_checkpoint = saver.get_tuple(saver.config(
        cid, generation.run_id + ":graph:", event_actor=True))
    if checkpoint is None and graph_checkpoint is None:
        from .steering import SteeringStore

        if not SteeringStore(_database()).applied_parts(owner, generation.run_id):
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
    checkpoint_text = checkpoint["checkpoint"]["channel_values"].get("partial_text") if checkpoint else None
    if checkpoint_text is not None and not isinstance(checkpoint_text, str):
        raise HTTPException(409, detail="Invalid recoverable text checkpoint")
    await _start_task(
        owner, generation, profile, agent,
        native_file_tools=any(level in {"read", "write"} for level in machine_policy.values()),
        write_tools=any(level == "write" for level in machine_policy.values()),
        ask_user_enabled=bool(state.get("askUserEnabled")),
        mcp_enabled=bool(effective_features(owner, cid)["mcp"]),
        resume_history=_generation_store().history(owner, cid, message_id=generation.user_message_id),
        partial_text=(checkpoint_text if checkpoint_text is not None
                      else _generation_store().accumulated_text(owner, generation.run_id)),
        granted_scopes=frozenset(scopes), grant_expires=expiry,
        recovery_steers=True,
        checkpoint_text=checkpoint_text,
    )


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
        if generation.status == "requires_action":
            try:
                scopes, expiry = _request_grant(request)
                if await _resume_ready_oauth(owner, generation, scopes, expiry):
                    generation = _generation_store().get(owner, generation.run_id) or generation
            except PermissionError as exc:
                raise HTTPException(403, detail=str(exc)) from exc
        if generation.status != "running":
            raise HTTPException(409, detail="Generation cannot be resumed")
        expected = payload.get("generationCreatedAt")
        if expected is not None and str(generation.generation_created_at) != str(expected):
            raise HTTPException(409, detail="Generation identity mismatch")
        await _reattach_running_actor(request, owner, generation)
        return JSONResponse(_generation_body(generation, status="resumed", resumed=True, protocol_version=protocol),
                            headers=_generator_headers(protocol))

    if not isinstance(action_id, str) or not action_id:
        raise HTTPException(400, detail="Invalid human action id")
    if generation.status not in {"requires_action", "running"}:
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
        claim = store.resume_claim(owner, generation.run_id)
        pending = store.pending_action(owner, generation.run_id)
        if claim is not None and claim.get("actionId") == action_id:
            pending = claim.get("pendingAction")
        if pending is None or pending.get("actionId") != action_id:
            raise HTTPException(409, detail="Stale or mismatched human action")
        if claim is None and store.action_expired(pending):
            store.finish(owner, generation.run_id, status="interrupted",
                         error="Human action expired", expired_action_id=action_id)
            raise HTTPException(409, detail="No live pending action to resume")
        # Read and validate the provider before mutating SQLite. Failed config
        # cannot consume a one-shot answer and strand the pending generation.
        with _database().connect() as db:
            row = db.execute("SELECT state,agent_id FROM runs WHERE id=?", (generation.run_id,)).fetchone()
        state = json.loads(row["state"])
        profile = provider_config(state.get("provider") or "openai", state.get("model") or None)
        agent = AgentRepository(_database()).get(owner, row["agent_id"]) if row["agent_id"] else None
        if row["agent_id"] and agent is None:
            raise HTTPException(403, detail="The originating Agent is no longer accessible")
        if payload.get("agent_id") not in (None, row["agent_id"]):
            raise HTTPException(409, detail="Agent identity mismatch")
        if (payload.get("model") is not None and state.get("model") and
            payload["model"] != state["model"]):
            raise HTTPException(409, detail="Model identity mismatch")
        paused_task = _TASKS.get(generation.run_id)
        if claim is not None and paused_task is not None and not paused_task.done():
            # A retry after an accepted human decision is an acknowledgment,
            # not a wait on a potentially long-running model continuation.
            submission = ({"decisions": payload.get("decisions")}
                          if pending.get("payload", {}).get("type") == "tool_approval"
                          else {key: payload[key] for key in ("answer", "answers") if key in payload})
            if json.dumps(claim.get("submission"), sort_keys=True, ensure_ascii=False) != \
                    json.dumps(submission, sort_keys=True, ensure_ascii=False):
                raise HTTPException(409, detail="Conflicting human action retry")
            return JSONResponse(_generation_body(generation, status="resumed", resumed=True,
                                                 protocol_version=protocol),
                                headers=_generator_headers(protocol))
        if paused_task and not paused_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(paused_task), timeout=5)
            except TimeoutError as exc:
                raise HTTPException(409, detail="Previous generation is still settling") from exc
        approval = pending.get("payload", {}).get("type") == "tool_approval"
        approved_batch = None
        resume_namespace = pending.get("namespace", "")
        if approval:
            from .nested_mcp import _check_mcp_access

            decisions = payload.get("decisions")
            if not isinstance(decisions, list):
                raise HTTPException(400, detail="Tool approval decisions are required")
            if (
                any(isinstance(decision, dict) and decision.get("decision") in {"approve", "edit"}
                    for decision in decisions)
                and any(item.get("name") == "mcp_tool_call" for item in
                        pending["payload"].get("action_requests", []))
            ):
                _check_mcp_access(owner, cid, scopes, execution=True)
            submission = {"decisions": decisions}
            if claim is not None:
                resumed, history, previous_text, approved_batch, resume_namespace = (
                    store.restart_claimed_resume(owner, generation.run_id, action_id, submission))
            else:
                try:
                    resumed, history, previous_text, approved_batch = store.claim_approval(
                        owner, generation.run_id, action_id, decisions,
                    )
                except KeyError:
                    resumed, history, previous_text, approved_batch, resume_namespace = (
                        store.restart_claimed_resume(owner, generation.run_id, action_id, submission))
        else:
            submission = {key: payload[key] for key in ("answer", "answers") if key in payload}
            if claim is not None:
                resumed, history, previous_text, approved_batch, resume_namespace = (
                    store.restart_claimed_resume(owner, generation.run_id, action_id, submission))
            else:
                try:
                    resumed, history, previous_text = store.answer_question(
                        owner, generation.run_id, action_id, submission,
                    )
                except KeyError:
                    resumed, history, previous_text, approved_batch, resume_namespace = (
                        store.restart_claimed_resume(owner, generation.run_id, action_id, submission))
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        # A changed retry is a conflict with a previously committed one-shot
        # action, not a malformed new payload. Keep validation errors at 400.
        detail = str(exc)
        conflict = detail in {"Conflicting human action retry", "Stale human action"}
        raise HTTPException(409 if conflict else 400, detail=detail) from exc
    from .routes import _repo

    await _start_task(owner, resumed, profile, agent,
                      native_file_tools=any(level in {"read", "write"} for level in machine_policy.values()),
                      write_tools=any(level == "write" for level in machine_policy.values()),
                      ask_user_enabled=bool(state.get("askUserEnabled")),
                      artifacts_mode=state.get("artifactsMode"),
                      mcp_enabled=bool(effective_features(owner, cid)["mcp"]),
                      resume_history=history, partial_text=previous_text,
                      approved_batch=approved_batch, resume_namespace=resume_namespace,
                      granted_scopes=frozenset(scopes), grant_expires=expiry,
                      recovery_steers=True)
    return JSONResponse(_generation_body(resumed, status="resuming", resumed=True, protocol_version=protocol),
                        headers=_generator_headers(protocol))


async def shutdown_generations() -> None:
    async with _TASK_GUARD:
        _prune_stale_task_handles()
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
        Route("/api/agents/chat/steer", steer_generation, methods=["POST"]),
        Route("/api/agents/chat/steer/deliver", steer_generation, methods=["POST"]),
        Route("/api/agents/chat/steer/cancel", mutate_steer, methods=["POST"]),
        Route("/api/agents/chat/steer/arm", mutate_steer, methods=["POST"]),
        Route("/api/agents/chat/resume", resume_generation, methods=["POST"]),
        Route("/api/agents/chat", start_generation, methods=["POST"]),
        Route("/api/agents/chat/{endpoint}", start_generation, methods=["POST"]),
    ]
