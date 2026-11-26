"""Connect source-ported Agent nodes to existing LSM dispatch and SQLite state."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time

from .agent_execution import execute_tool_batch, replay_key
from .agent_runtime import (
    AgentContext,
    AgentLoopState,
    AgentSuspended,
    RuntimeSafetyError,
    ToolBatchOutput,
    run_agent_loop,
)
from .agents import AgentRepository
from .approval_runtime import (
    ApprovalBatch,
    build_approval_payload,
    execute_approval_batch,
)
from .ask_user_tools import ASK_USER_TOOLS, build_ask_user_payload
from .checkpoints import SQLiteCheckpointSaver
from .handoff import (
    HandoffRouting,
    build_handoff_command,
    combine_handoff_commands,
    handoff_edge_for_call,
    handoff_tools,
    is_transfer_tool,
)
from .memory import (
    MEMORY_TOOL_USAGE_GUARD,
    MemoryRepository,
    agent_partition,
    execute_memory_tool,
    format_memory_context,
    memory_config,
    memory_enabled,
    tool_definitions,
)
from .memory_protection import configured_filters
from .providers import (
    ModelFinish,
    ModelThought,
    ModelToolCall,
    ModelUsage,
    provider_config,
    selected_provider,
)
from .semantic_index import (
    render_compaction_semantic_index,
    snapshot_compaction_semantic_index,
)
from .steering import SteeringStore, merged_text
from .sleep_tool import SLEEP_TOOLS, invoke_sleep, sleep_seconds
from .subagents import (
    MAX_SUBAGENT_DEPTH,
    build_subagent_configs,
    chat_subagent_config,
    invoke_subagent,
    subagent_tools,
)


class AgentRunner:
    def __init__(self, owner, generation, database, store, *, scopes, grant_expires,
                 stream_tools, stream_text, on_text, on_thought=None, agent=None, profile=None,
                 parameters=None, ask_user_enabled=False, mcp_enabled=False,
                 namespace="", child_configs=None, selected_tools=None,
                 resume_history=None, resume_namespace="", partial_text="",
                 approved_batch=None, graph_node=False, graph_definition=None,
                 graph_entry_id=None, graph_parallel=False, graph_max_handoffs=None,
                 authorization_conversation_id=None, background_deny=False,
                 task_control_host=None, task_control_id=None, subagent_depth=MAX_SUBAGENT_DEPTH,
                 on_injected=None, wakeup_lease=None, event_delivery_lease=None,
                 actor_lease=None, recovery_steers=False, on_tool_completed=None, compaction_semantic_index=None, webui_cookie=None, web_search_enabled=True,
                 parent_approval_mode=None):
        self.owner, self.generation, self.database, self.store = owner, generation, database, store
        self.scopes, self.grant_expires = scopes, grant_expires
        self.webui_cookie = webui_cookie
        self.web_search_enabled = web_search_enabled
        self.stream_tools, self.stream_text, self.on_text = stream_tools, stream_text, on_text
        self.on_thought = on_thought
        self.root_agent, self.initial_profile = agent, profile
        self.graph_definition = graph_definition if graph_definition is not None else agent
        self.graph_node = graph_node
        self.graph_entry_id = graph_entry_id or (self.graph_definition or {}).get("id") or "default"
        self.graph_parallel = graph_parallel
        self.graph_max_handoffs = graph_max_handoffs
        self.authorization_conversation_id = authorization_conversation_id or generation.conversation_id
        self.background_deny = background_deny
        self.parent_approval_mode = parent_approval_mode
        self.task_control_host, self.task_control_id = task_control_host, task_control_id
        self.subagent_depth = subagent_depth
        self.on_injected = on_injected
        self.wakeup_lease = wakeup_lease
        self.event_delivery_lease = event_delivery_lease
        self.actor_lease = actor_lease
        self.recovery_steers = recovery_steers
        self.on_tool_completed = on_tool_completed
        self.initial_parameters = parameters or {}
        self.ask_user_enabled, self.mcp_enabled = ask_user_enabled, mcp_enabled
        self.namespace, self.child_configs, self.selected_tools = namespace, child_configs, selected_tools
        self.resume_history, self.resume_namespace = resume_history, resume_namespace
        self.partial_text, self.approved_batch = partial_text, approved_batch
        # The caller's host-produced index is snapshotted before yielding to
        # the provider, preventing concurrent user-owned changes to hints.
        self.compaction_semantic_index = snapshot_compaction_semantic_index(compaction_semantic_index)
        self.repository = AgentRepository(database)
        self.saver = SQLiteCheckpointSaver(database, owner, actor_lease=actor_lease)
        self.steers = SteeringStore(database)
        self.config = self.saver.config(generation.conversation_id, generation.run_id,
                                       checkpoint_ns=namespace, event_actor=True)
        self.active_config = self.config
        self.cache = {}
        self.configs = {}
        self._injected_background_names: dict[str, frozenset[str]] = {}
        self.route = HandoffRouting(self.graph_entry_id, self.graph_max_handoffs, self.graph_parallel)
        self.memory_artifacts: dict[str, dict] = {}
        self._last_compaction_attempt_size = -1
        self._summary_failures = 0

    def _check_grant(self):
        if self.webui_cookie is not None:
            from ..settings import get_settings
            from .auth import WebAuthStore

            session = WebAuthStore(get_settings().state_dir).session(self.webui_cookie)
            if (session is None or session.owner != self.owner
                    or not set(self.scopes).issubset(set(session.scopes.split()))):
                raise RuntimeSafetyError("WebUI session expired or was signed out")
            # The JWT that began this run may have expired an hour ago; only
            # the live, revocable browser session controls its ongoing lease.
            self.grant_expires = session.grant_until
        if self.actor_lease is not None:
            self.actor_lease.assert_current()
        if self.grant_expires is not None and self.grant_expires <= time.time():
            raise RuntimeSafetyError("Authentication grant expired")
        if self.task_control_host is not None and self.task_control_id is not None:
            self.task_control_host.assert_execution_lease(self.task_control_id)
        if self.wakeup_lease is not None:
            from .subagent_wakeup import assert_wakeup_lease

            assert_wakeup_lease(self.database, self.owner,
                                self.generation.run_id, self.wakeup_lease)
        if self.event_delivery_lease is not None:
            from .event_triggers import assert_event_lease

            assert_event_lease(self.database, self.owner, self.generation.run_id,
                               self.event_delivery_lease)

    def _memory_context(self, agent: dict | None) -> str:
        from .misc_routes import effective_features
        from .storage import WorkspaceRepository

        settings = WorkspaceRepository(self.database)
        if not effective_features(self.owner, self.authorization_conversation_id, repo=settings)["memory"]:
            return ''
        if not memory_enabled(settings, self.owner):
            return ''
        # The original primary Agent reads shared personal memories even when
        # it has no inline memory tool. Only an Agent explicitly registering
        # the memory capability receives keys and a mutation-tool prompt.
        has_tools = ((agent is None or 'memory' in ((agent or {}).get('tools') or []))
                     and memory_enabled(settings, self.owner, tools=True))
        formatted = MemoryRepository(self.database).formatted(
            self.owner, agent_partition(agent), filters=configured_filters(settings, self.owner))
        if formatted.get('readFailed'):
            # Never lose the mutation consent rule when Memory reads fail.
            return MEMORY_TOOL_USAGE_GUARD if has_tools else ''
        explicit_memory_tool = bool(agent and 'memory' in ((agent or {}).get('tools') or []))
        endpoints = settings.setting(self.owner, 'endpoints', {})
        explicit_memory_config = (
            isinstance(settings.setting(self.owner, 'webui.memory.config'), dict)
            or isinstance((endpoints or {}).get('memory'), dict)
        )
        if (not explicit_memory_tool and not explicit_memory_config
                and not (formatted.get('withKeys') or formatted.get('withoutKeys'))):
            # An empty default-enabled store needs no memory-list preamble,
            # but the mutation consent rule must remain visible to the model
            # whenever its Memory tools are offered.
            return MEMORY_TOOL_USAGE_GUARD if has_tools else ''
        context = format_memory_context(formatted['withKeys'] if has_tools else formatted['withoutKeys'])
        return (context or '') + ('\n\n' + MEMORY_TOOL_USAGE_GUARD if has_tools else '')

    def _context(self, agent, *, profile=None, selected_tools=None):
        from .graph_topology import admit_agent_graph
        from .lsm_tool_registry import available_tools
        from .nested_mcp import nested_tools
        from .web_research import WEB_TOOLS

        self._check_grant()
        admit_agent_graph(self.owner, self.graph_definition, self.repository)
        selected = set(selected_tools if selected_tools is not None else (agent or {}).get("tools") or [])
        unrestricted = agent is None and selected_tools is None
        # Migrate the old Skill capability selection to the registered names.
        if {"skill", "skills"} & selected or (
            (agent or {}).get("skills_enabled") is True
        ):
            selected.update({"skill_list", "skill_load", "skill_read"})
        # Legacy agents retain their per-tool allowlist. Agents configured in
        # the new builder expose all audited native tools allowed by both ACLs.
        from .machine_permissions import agent_access_policy

        policy = agent_access_policy(agent or {})
        machine_configured = policy is not None
        machine_policy, machine_default = policy if policy is not None else (None, "write")
        native = available_tools(self.owner, self.authorization_conversation_id,
                                 scopes=set(self.scopes), expires=self.grant_expires,
                                 agent_permissions=machine_policy,
                                 agent_default_permission=machine_default)
        machine_exposed = selected_tools is None and machine_configured
        tools = [tool for tool in native
                 if (unrestricted or machine_exposed or tool["function"]["name"] in selected
                     or tool["function"]["name"] in {"session_manage", "plan_manage"})]
        from .misc_routes import effective_features
        from .storage import WorkspaceRepository

        settings = WorkspaceRepository(self.database)
        features = effective_features(self.owner, self.authorization_conversation_id, repo=settings)
        # An explicitly saved composer preference supersedes stale ephemeral
        # model-spec flags; legacy request flags still apply without a preference.
        web_default = settings.setting(self.owner, 'conversation.features.global', {})
        web_chat = settings.setting(self.owner, 'conversation.permissions.' + self.authorization_conversation_id, {}) if self.authorization_conversation_id else {}
        explicit_web = any(isinstance(value, dict) and type(value.get('web')) is bool
                           for value in (web_default, web_chat))
        if features["web"] and (self.web_search_enabled or explicit_web):
            tools += WEB_TOOLS
        native_names = frozenset(tool["function"]["name"] for tool in tools)
        tools += SLEEP_TOOLS
        if self.mcp_enabled and (agent or {}).get("mcp_servers") != []:
            mcp_configured = "mcp_servers" in (agent or {})
            mcp_exposed = mcp_configured or (selected_tools is None and not selected)
            tools += [tool for tool in nested_tools()
                      if unrestricted or machine_exposed or mcp_exposed
                      or tool["function"]["name"] in selected]
        from .content_filters import validate_agent_instructions, validate_model_parameters

        filters = configured_filters(settings, self.owner)
        validate_agent_instructions(str((agent or {}).get('instructions') or ''), filters)
        from .sampling import merge_sampling

        profile = profile or provider_config(selected_provider({}, agent), (agent or {}).get("model"))
        parameters = merge_sampling(profile.sampling, (agent or {}).get('model_parameters') or self.initial_parameters)
        if isinstance(parameters, dict):
            validate_model_parameters({'model_parameters': parameters}, filters)
        if ((unrestricted or 'memory' in selected)
                and features['memory']
                and memory_enabled(settings, self.owner, tools=True)):
            config = memory_config(settings, self.owner) or {}
            tools += tool_definitions(config.get('validKeys'))
        if self.ask_user_enabled and (unrestricted or "ask_user_question" in selected):
            tools += ASK_USER_TOOLS
        identity = (agent or {}).get("id") or "default"
        configs = self.child_configs if self.child_configs is not None else build_subagent_configs(
            self.owner, agent, self.database,
        )
        if unrestricted and self.child_configs is None and not self.namespace and not self.background_deny:
            configs = [chat_subagent_config(self.owner)]
        if self.subagent_depth <= 0:
            configs = []
        self.configs[identity] = configs
        if configs:
            from .subagent_task_host import check_background_task_tools

            tools += subagent_tools(configs, background=True, thread_continuation=True)
            tools += check_background_task_tools()
        if agent is not None:
            from .actions import ActionRepository

            tools += ActionRepository(self.database).tool_schemas(
                self.owner, agent, selected_tools=selected,
            )
        if self.graph_definition:
            tools += handoff_tools(self.owner, self.graph_definition, self.repository, source_agent_id=identity)
        background_names = frozenset()
        if not self.background_deny:
            from .background_tools import inject_tools

            tools, background_names = inject_tools(tools, agent, native_names=native_names)
            self._injected_background_names[identity] = background_names
            if background_names and not any(t["function"]["name"] == "check_background_task" for t in tools):
                from .subagent_task_host import check_background_task_tools

                tools += check_background_task_tools()
        override = (agent or {}).get("recursion_limit")
        limit = int(override) if type(override) in (int, float) and override > 0 else None
        return AgentContext(profile, tools, parameters,
                            recursion_limit=limit, tool_end=bool((agent or {}).get("end_after_tools")), agent=agent,
                            compaction_semantic_index=self.compaction_semantic_index)

    def _snapshot(self, state):
        return {"messages": state.messages, "step": state.step, "model_turn": state.model_turn,
                "agent_id": (state.context.agent or {}).get("id"),
                "pending_calls": [{"call_id": call.call_id, "name": call.name,
                                   "arguments": call.arguments, "provider_data": call.provider_data}
                                  for call in state.pending_calls],
                "tool_step_started": state.tool_step_started, "completed": state.completed,
                "partial_text": self.partial_text, "handoffState": self.route.snapshot(),
                "graph_commands": state.graph_commands}

    async def _save(self, state, calls):
        self._check_grant()
        if calls and not state.tool_step_started:
            self.cache = {}
        identity = f"{time.time_ns():020d}"
        self.active_config = self.saver.put(self.active_config, {
            "v": 1, "id": identity, "channel_values": self._snapshot(state),
            "channel_versions": {"messages": state.step}, "versions_seen": {},
        }, {"source": "loop", "step": state.step})
        if not calls:
            # Finish the durable OAuth replay fence only *after* the graph's
            # post-tool checkpoint has safely left the pending-call edge.
            self.store.clear_oauth_checkpoint(self.owner, self.generation.run_id)

    @staticmethod
    def _visible_tool_args(call):
        """Bound SSE previews; native and checkpoint arguments remain complete."""
        args = call.arguments
        if call.name == 'file_write' and isinstance(args, dict):
            content = args.get('content')
            if isinstance(content, str) and len(content) > 8192:
                return {**args, 'content': f'[omitted {len(content)} characters from file-write UI event]'}
        raw = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) <= 16 * 1024:
            return args
        return {"_truncated": True, "preview": raw.encode("utf-8")[:8192].decode(
            "utf-8", errors="ignore"), "note": "Full arguments retained for execution"}

    def _publishes_tool_steps(self) -> bool:
        # Graph members run inside a shared parent generation. A foreground
        # graph node can publish its tool cards; an isolated subagent (or
        # detached task) must keep its internal steps checkpoint-only.
        return not (getattr(self, "background_deny", False) or
                    (self.namespace and (not getattr(self, "graph_node", False)
                                         or '/subagent:' in self.namespace)))

    def _tool_step(self, call):
        checkpoint = self.active_config["configurable"].get("checkpoint_id", "")
        identity = "step_" + hashlib.sha256(
            (self.namespace + ":" + checkpoint + ":" + call.call_id).encode(),
        ).hexdigest()[:24]
        with self.database.connect() as database:
            prior = database.execute(
                "SELECT data FROM generation_events WHERE run_id=? AND "
                "json_extract(data,'$.event')='on_run_step' AND json_extract(data,'$.data.id')=? LIMIT 1",
                (self.generation.run_id, identity),
            ).fetchone()
            if prior:
                return json.loads(prior["data"])["data"]
            index = database.execute(
                "SELECT coalesce(max(json_extract(data,'$.data.index')),0)+1 FROM generation_events WHERE run_id=?",
                (self.generation.run_id,),
            ).fetchone()[0]
        step = {"type": "tool_calls", "id": identity, "index": index,
                "runId": self.generation.response_message_id, "status": "in_progress",
                "created_at": int(time.time() * 1000), "stepDetails": {
                    "type": "tool_calls", "tool_calls": [{
                        "id": call.call_id, "type": "tool_call", "name": call.name,
                        "args": self._visible_tool_args(call),
                    }],
                }}
        self.store.append(self.owner, self.generation.run_id, {"event": "on_run_step", "data": step},
                          actor_lease=self.actor_lease)
        return step

    async def _completed(self, call, record, *, executed: bool = True):
        output = record["output"]
        if isinstance(output, str):
            self.saver.put_writes(self.active_config, [("messages", {
                "role": "tool", "tool_call_id": call.call_id, "content": output,
            })], task_id=call.call_id)
        if not self._publishes_tool_steps():
            from .action_spec import is_action_tool

            if is_action_tool(call.name) and executed:
                self.store.oauth_dispatch(self.owner, self.generation.run_id, call.call_id, "completed")
            return
        step = self._tool_step(call)
        if call.name == "file_write" and isinstance(output, str):
            # Original callbacks.js `on_tool_end` publishes tool artifacts
            # separately from the model-visible tool result. The native LSM
            # file-write response is the trusted success/hash evidence; keep
            # the original file contents outside model message history.
            from contextlib import suppress

            from starlette.exceptions import HTTPException

            from ..settings import get_settings
            from .office_preview import publish_native_file_write

            # The authorized tool write already completed. An optional preview
            # failure cannot change the native result or its audit record.
            with suppress(ValueError, PermissionError, OSError, HTTPException):
                await publish_native_file_write(self.owner, self.generation, call, output,
                                                database=self.database, state_dir=get_settings().state_dir)
        preview = output if isinstance(output, str) else "Agent control transferred"
        preview = preview.encode("utf-8")[:128 * 1024].decode("utf-8", errors="ignore")
        # A UI resource marker is only resolvable after the original client
        # receives a canonical attachment. Derive it from the same native MCP
        # envelope retained in the checkpoint; never infer from display JSON.
        if call.name == "mcp_tool_call" and isinstance(output, str):
            from .mcp_projection import mcp_tool_history_message

            artifact = mcp_tool_history_message(call, output, self.initial_profile.provider if self.initial_profile else "openai").get("artifact")
            ui = artifact.get("ui_resources") if isinstance(artifact, dict) else None
            if isinstance(ui, dict) and isinstance(ui.get("data"), list) and ui["data"]:
                # SSE event storage has a strict byte ceiling. The full MCP
                # envelope remains in the durable tool checkpoint for replay;
                # oversized UI resources cannot invalidate a completed tool.
                import json

                payload = {
                    "event": "attachment", "data": {
                        "type": "ui_resources", "messageId": self.generation.response_message_id,
                        "toolCallId": call.call_id, "conversationId": self.generation.conversation_id,
                        "ui_resources": ui["data"],
                    },
                }
                if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= 240_000:
                    self.store.append(self.owner, self.generation.run_id, payload)
        artifacts = getattr(self, "memory_artifacts", {})
        end_at = int(time.time() * 1000)
        event = {
            "event": "on_run_step_completed", "data": {"result": {
                "id": step["id"], "index": step["index"], "completed_at": end_at,
                "type": "tool_call", "tool_call": {
                    "id": call.call_id, "name": call.name, "args": self._visible_tool_args(call),
                    "type": "tool_call", "output": preview, "progress": 1,
                    **({'artifact': artifacts[call.call_id]} if call.call_id in artifacts else {}),
                    **({"executed": False} if not executed else {}),
                },
            }},
        }
        # Persist completed tool evidence and Controller file links atomically.
        from .tool_attachments import controller_tool_file_ids

        identities = controller_tool_file_ids(output)
        if identities:
            self.store.append_tool_completion(
                self.owner, self.generation.run_id, event, call.call_id, identities,
                actor_lease=self.actor_lease,
                full_arguments=call.arguments if executed else None,
            )
        else:
            self.store.append(self.owner, self.generation.run_id, event,
                              actor_lease=self.actor_lease,
                              full_arguments=call.arguments if executed else None)
        # Source agents@4.0.1 Graph.closeRunStep: terminal closure is an
        # independent event. First close wins and survives SSE reconnect and
        # durable final history, including native tool denial/error paths.
        with self.database.connect() as db:
            previous = db.execute(
                "SELECT 1 FROM generation_events WHERE run_id=? AND "
                "json_extract(data,'$.event')='on_run_step_closed' AND "
                "json_extract(data,'$.data.id')=? LIMIT 1",
                (self.generation.run_id, step["id"]),
            ).fetchone()
        if previous is None:
            failed = isinstance(output, str) and (
                output.startswith("Tool failed (") or output.startswith("Blocked: ")
                or output.startswith("API call failed (")
            )
            self.store.append(self.owner, self.generation.run_id, {
                "event": "on_run_step_closed", "data": {
                    "id": step["id"], "index": step["index"], "type": "tool_calls",
                    "runId": step["runId"],
                    "status": "failed" if failed else "completed",
                    "closed_at": end_at, "created_at": step["created_at"],
                },
            }, actor_lease=self.actor_lease)
        from .action_spec import is_action_tool

        if is_action_tool(call.name) and executed:
            self.store.oauth_dispatch(self.owner, self.generation.run_id, call.call_id, "completed")
        callback = getattr(self, "on_tool_completed", None)
        if callback is not None:
            await callback(call)

    async def _invoke(self, call, state):
        from .lsm_tool_registry import ToolPermissionDenied, call_tool
        from .nested_mcp import approved_call, discover

        self._check_grant()
        if call.name not in {tool["function"]["name"] for tool in state.context.tools}:
            raise RuntimeSafetyError("Tool is not enabled for the current Agent")
        if call.name == "sleep":
            try:
                seconds = sleep_seconds(call.arguments)
            except ValueError as exc:
                return f"Tool failed (ValueError): {exc}"
            if self._publishes_tool_steps():
                step = self._tool_step(call)
                self.store.append(self.owner, self.generation.run_id, {
                    "event": "on_tool_calls_dispatched", "data": {
                        "dispatched_at": int(time.time() * 1000),
                        "runId": step["runId"],
                        "toolCalls": [{"id": call.call_id, "name": call.name, "stepId": step["id"]}],
                    },
                }, actor_lease=self.actor_lease)
            return await invoke_sleep(seconds, self._check_grant)
        if call.name in {'set_memory', 'delete_memory'}:
            from .storage import WorkspaceRepository
            settings = WorkspaceRepository(self.database)
            from .misc_routes import effective_features

            if (not effective_features(self.owner, self.authorization_conversation_id, repo=settings)["memory"]
                    or not memory_enabled(settings, self.owner, tools=True)):
                raise RuntimeSafetyError('Memory tools are disabled')
            config = {**(memory_config(settings, self.owner) or {}),
                      'filters': configured_filters(settings, self.owner)}
            result, artifact = execute_memory_tool(MemoryRepository(self.database), self.owner,
                state.context.agent or {}, call.name, call.arguments, config)
            if artifact is not None:
                self.memory_artifacts[call.call_id] = artifact
            return result
        if call.name in {"web_search", "web_fetch"}:
            from .misc_routes import effective_features
            from .storage import WorkspaceRepository
            from .web_research import invoke_web_tool

            if not effective_features(self.owner, self.authorization_conversation_id,
                                      repo=WorkspaceRepository(self.database))["web"]:
                raise RuntimeSafetyError("Web search is disabled for this conversation")

            return await invoke_web_tool(self.owner, call.name, call.arguments)
        if call.name == "check_background_task":
            from .background_tools import check_tool_task
            from .subagent_task_host import SQLiteSubagentTaskHost

            host = SQLiteSubagentTaskHost(
                self.database, self.owner, self.authorization_conversation_id,
                stream_tools=self.stream_tools, stream_text=self.stream_text,
            )
            task_id = call.arguments.get("background_task_id")
            action = call.arguments.get("action") or "poll"
            if isinstance(task_id, str) and task_id.startswith("tooltask_"):
                return json.dumps(check_tool_task(self.database, self.owner,
                                                  self.authorization_conversation_id, task_id, action,
                                                  claimant_run_id=self.generation.run_id,
                                                  claimant_call_id=call.call_id),
                                  ensure_ascii=False)
            child = await host.check(call.arguments, tool_call_id=call.call_id,
                                     parent_run_id=self.generation.run_id,
                                     parent_agent_id=(state.context.agent or {}).get("id", "default"))
            if not task_id and action == "poll":
                from .background_tools import check_tool_task

                try:
                    decoded = json.loads(child)
                except (TypeError, ValueError):
                    # Existing hosted task controllers may return a plain-text
                    # observation rather than the original JSON task list.
                    # Do not erase a valid result while merging ordinary tools.
                    return child
                if not isinstance(decoded, dict) or not isinstance(decoded.get("tasks"), list):
                    return child
                decoded["tasks"].extend(check_tool_task(
                    self.database, self.owner, self.authorization_conversation_id, None))
                decoded["outstanding"] = sum(task["status"] == "running" for task in decoded["tasks"])
                return json.dumps(decoded, ensure_ascii=False)
            return child
        if ("run_in_background" in call.arguments and
                call.name in self._injected_background_names.get(
                    (state.context.agent or {}).get("id") or "default", frozenset())):
            from .background_tools import eligible, start_tool_task
            from .lsm_tool_registry import call_tool as invoke_native

            shown = next((tool for tool in state.context.tools
                          if tool["function"]["name"] == call.name), None)
            params = (shown or {}).get("function", {}).get("parameters", {})
            if not eligible(call.name) or "run_in_background" not in params.get("properties", {}):
                raise RuntimeSafetyError("run_in_background was not enabled for this tool")
            args = {key: value for key, value in call.arguments.items() if key != "run_in_background"}
            native_call = ModelToolCall(call.call_id, call.name, args, call.provider_data)
            if call.arguments["run_in_background"] is True:
                if self.background_deny:
                    raise RuntimeSafetyError("Background execution is disabled in this child context")

                origin_agent = copy.deepcopy(state.context.agent)
                origin_agent_id = (origin_agent or {}).get("id")

                async def detached_dispatch(c, scopes, expires, authorization):
                    from ..skill_ops import managed_skill_context

                    token = managed_skill_context.set((self.database, self.owner, origin_agent))
                    try:
                        return await invoke_native(self.owner, self.generation.conversation_id, c,
                                                   granted_scopes=set(scopes), grant_expires=expires,
                                                   run_id=self.generation.run_id,
                                                   authorization_conversation_id=authorization,
                                                   agent_id=origin_agent_id)
                    finally:
                        managed_skill_context.reset(token)

                return await start_tool_task(self.database, self.owner,
                                             self.generation.conversation_id,
                                             self.authorization_conversation_id,
                                             self.generation.run_id, native_call,
                                             scopes=frozenset(self.scopes),
                                             grant_expires=self.grant_expires,
                                             dispatch=detached_dispatch,
                                             event_delivery_lease=self.event_delivery_lease)
            call = native_call
        if call.name == "subagent":
            from .subagent_task_host import SQLiteSubagentTaskHost

            host = SQLiteSubagentTaskHost(
                self.database, self.owner, self.authorization_conversation_id,
                stream_tools=self.stream_tools, stream_text=self.stream_text,
            )
            return await invoke_subagent(
                call, self.configs[(state.context.agent or {}).get("id") or "default"],
                execute_child=lambda invocation: self._child(
                    invocation, profile=state.context.profile, parameters=state.context.parameters,
                    parent_approval_mode=self._approval_mode(state.context.agent)),
                start_background=lambda invocation, thread: host.start(
                    invocation, thread_id=thread, mcp_enabled=self.mcp_enabled,
                    web_search_enabled=self.web_search_enabled,
                    chat_model=state.context.profile.model,
                    chat_parameters=state.context.parameters,
                    parent_approval_mode=self._approval_mode(state.context.agent)), owner=self.owner,
                conversation_id=self.authorization_conversation_id, parent_run_id=self.generation.run_id,
                parent_agent_id=(state.context.agent or {}).get("id"),
                scopes=frozenset(self.scopes), grant_expires=self.grant_expires, database=self.database,
                max_depth=self.subagent_depth,
                propagate_error=lambda error: isinstance(error, (AgentSuspended, RuntimeSafetyError)),
            )
        if is_transfer_tool(call.name):
            current = state.context.agent or {}
            graph = self.repository.get(self.owner, self.graph_definition["id"])
            if graph is None:
                raise RuntimeSafetyError("Agent graph is no longer available")
            if self.graph_definition.get('graphAgentIds'):
                # Graph-team subagents are admitted from an isolated snapshot
                # whose edges are not written to the entry Agent's standalone
                # definition. Revalidate ownership and that exact topology;
                # consulting the saved entry's unrelated edges rejects tools
                # already advertised by the team's admitted graph.
                from .graph_topology import admit_agent_graph

                admit_agent_graph(self.owner, self.graph_definition, self.repository)
                graph = self.graph_definition
            edge = handoff_edge_for_call(self.owner, graph, self.repository, call.name,
                                         source_agent_id=current["id"])
            return build_handoff_command(edge, current["id"], current.get("name") or current["id"],
                                         call.name, call.arguments, call.call_id, state.messages)
        from ..skill_ops import managed_skill_context

        token = managed_skill_context.set((self.database, self.owner, state.context.agent))
        try:
            from .action_spec import is_action_tool
            if is_action_tool(call.name):
                from .action_runtime import invoke_action
                current_id = (state.context.agent or {}).get("id")
                if not current_id:
                    raise RuntimeSafetyError("Action execution requires a saved Agent")
                from .action_oauth import access_token
                from .actions import ActionRepository

                action_repo = ActionRepository(self.database)
                record = action_repo.get_for_tool(self.owner, current_id, call.name)
                if record is None:
                    raise RuntimeSafetyError("Action is not bound to this Agent")
                meta, _, operation = record
                oauth_token = None
                if meta.get("auth", {}).get("type") == "oauth":
                    oauth_token = await access_token(action_repo, self.owner, operation["action_id"])
                    if not oauth_token:
                        if self.background_deny:
                            return "Blocked: OAuth Action requires foreground human authorization."
                        raise RuntimeSafetyError("OAuth Action authorization was revoked before dispatch")
                    # The claim-to-HTTP boundary is a one-way replay fence.
                    # A crash during external execution cannot safely resend
                    # a potentially consequential request.
                    self.store.oauth_dispatch(self.owner, self.generation.run_id, call.call_id, "dispatching")
                return await invoke_action(self.owner, current_id, call.name, call.arguments, self.database,
                                           oauth_token=oauth_token, expected_version=operation["action_version"])
            if call.name in {"mcp_tool_search", "mcp_tool_inspect"}:
                return await discover(self.owner, self.authorization_conversation_id, set(self.scopes), call,
                                      agent_id=(state.context.agent or {}).get("id"))
            if call.name == "mcp_tool_call":
                return await approved_call(self.owner, self.authorization_conversation_id, set(self.scopes), call,
                                           agent_id=(state.context.agent or {}).get("id"))
            return await call_tool(self.owner, self.generation.conversation_id, call,
                                   granted_scopes=set(self.scopes), grant_expires=self.grant_expires,
                                   run_id=self.generation.run_id,
                                   authorization_conversation_id=self.authorization_conversation_id,
                                   agent_id=(state.context.agent or {}).get("id"))
        except ToolPermissionDenied as error:
            return "Blocked: " + str(error)
        except PermissionError as error:
            raise RuntimeSafetyError(str(error)) from error
        except Exception as error:
            # Native/provider exceptions may contain credentials or headers.
            # Keep their type for recovery without copying secrets to the model.
            return "Tool failed (" + type(error).__name__ + ")"
        finally:
            managed_skill_context.reset(token)

    async def _child(self, invocation, *, profile=None, parameters=None, parent_approval_mode=None):
        async def quiet(text):
            pass

        child = AgentRunner(self.owner, self.generation, self.database, self.store,
                            scopes=self.scopes, grant_expires=self.grant_expires,
                            stream_tools=self.stream_tools, stream_text=self.stream_text,
                            on_text=quiet, agent=None if invocation.ordinary_chat else invocation.agent,
                            profile=(profile or self.initial_profile) if invocation.ordinary_chat else None,
                            parameters=(parameters or self.initial_parameters) if invocation.ordinary_chat else None,
                            mcp_enabled=self.mcp_enabled,
                            namespace=self.namespace + "/subagent:" + invocation.parent_tool_call_id,
                            child_configs=invocation.child_configs, selected_tools=invocation.selected_tools,
                            resume_history=self.resume_history, resume_namespace=self.resume_namespace,
                            partial_text=self.partial_text,
                            authorization_conversation_id=self.authorization_conversation_id,
                            background_deny=self.background_deny,
                            parent_approval_mode=parent_approval_mode or self._approval_mode(),
                            task_control_host=self.task_control_host, task_control_id=self.task_control_id,
                            subagent_depth=invocation.remaining_depth,
                            wakeup_lease=self.wakeup_lease,
                            event_delivery_lease=self.event_delivery_lease,
                            actor_lease=self.actor_lease, recovery_steers=self.recovery_steers,
                            web_search_enabled=self.web_search_enabled, webui_cookie=self.webui_cookie)
        from .attachments import with_agent_context

        history = with_agent_context(self.database, self.owner, invocation.agent,
                                     invocation.messages)
        return await child.run(history, recursion_limit=invocation.recursion_limit)

    async def _prepare_oauth(self, calls, state):
        """Durably suspend *before* launching side-effecting sibling tools.

        The pinned LibreChat model tool call remains in the existing checkpoint;
        the original React tool card consumes the OAuth sign-in delta. The
        Controller may now exit without a long-lived authorization waiter.
        """
        from .action_oauth import access_token, begin_flow
        from .action_spec import is_action_tool
        from .actions import ActionRepository

        current_id = (state.context.agent or {}).get("id")
        if not current_id:
            return
        repo = ActionRepository(self.database)
        for call in calls:
            if not is_action_tool(call.name):
                continue
            record = repo.get_for_tool(self.owner, current_id, call.name)
            if record is None:
                raise RuntimeSafetyError("Action is not bound to this Agent")
            metadata, _, operation = record
            if metadata.get("auth", {}).get("type") != "oauth":
                continue
            if await access_token(repo, self.owner, operation["action_id"]):
                continue
            if self.background_deny:
                # Detached tasks must never park on a hidden OAuth redirect.
                # _invoke returns a blocked tool result for this call instead.
                continue
            url, _ = begin_flow(repo, self.owner, operation["action_id"],
                                self.generation.run_id, call.call_id)
            step = self._tool_step(call)
            auth_delta = {"event": "on_run_step_delta", "data": {
                "id": step["id"], "delta": {"type": "tool_calls", "tool_calls": [
                    {"id": call.call_id, "name": call.name, "args": ""}],
                    "auth": url, "expires_at": int(time.time() * 1000) + 600_000},
            }}
            await self._pause({"type": "action_oauth", "action_id": operation["action_id"],
                               "action_version": operation["action_version"],
                               "tool_call_id": call.call_id, "tool_name": call.name,
                               "step_id": step["id"]},
                              state, oauth_delta=auth_delta)

    async def _pause(self, payload, state, *, approval=False, oauth_delta=None):
        import uuid

        pending = {"actionId": "action_" + uuid.uuid4().hex,
                   "streamId": self.generation.conversation_id,
                   "conversationId": self.generation.conversation_id,
                   "runId": self.generation.run_id,
                   "responseMessageId": self.generation.response_message_id,
                   "createdAt": int(time.time() * 1000), "namespace": self.namespace, "payload": payload}
        self.saver.put_writes(self.active_config, [("__interrupt__", pending)], task_id="human")
        if oauth_delta is not None:
            saved = self.store.pause_for_oauth(self.owner, self.generation.run_id, pending,
                                               state.messages, self.partial_text, oauth_delta,
                                               actor_lease=self.actor_lease)
        else:
            pause = self.store.pause_for_approval if approval else self.store.pause_for_question
            saved = pause(self.owner, self.generation.run_id, pending, state.messages,
                          self.partial_text, actor_lease=self.actor_lease)
        if not saved:
            raise RuntimeError("Unable to save pending Agent action")
        raise AgentSuspended()

    @staticmethod
    def _blocked_call(call: ModelToolCall) -> bool:
        return call.arguments == {'_content_filter_blocked': True}

    def _preflight_model_calls(self, calls: list[ModelToolCall], state: AgentLoopState) -> list[ModelToolCall]:
        """Strip forbidden model tool arguments before event/checkpoint writes."""
        from .content_filters import ContentFilterBlocked, validate_tool_arguments
        from .storage import WorkspaceRepository

        filters = configured_filters(WorkspaceRepository(self.database), self.owner)
        sanitized = []
        for call in calls:
            if self._blocked_call(call):
                sanitized.append(call)
                continue
            try:
                validate_tool_arguments(call.name, call.arguments, filters)
            except ContentFilterBlocked:
                sanitized.append(ModelToolCall(call.call_id, call.name,
                                               {'_content_filter_blocked': True}))
            else:
                sanitized.append(call)
        return sanitized

    async def _filtered_invoke(self, call, state):
        """Apply source-scoped input and output policy on every tool path.

        The same wrapper runs for ordinary batches and approved retries; it
        must not expose blocked credentials in checkpoints or result previews.
        """
        from .content_filters import (
            ContentFilterBlocked,
            filtered_tool_output,
            validate_tool_arguments,
        )
        from .storage import WorkspaceRepository

        if self._blocked_call(call):
            return 'Tool call blocked by configured content protection policy.'
        filters = configured_filters(WorkspaceRepository(self.database), self.owner)
        try:
            validate_tool_arguments(call.name, call.arguments, filters)
        except ContentFilterBlocked:
            return 'Tool call blocked by configured content protection policy.'
        result = await self._invoke(call, state)
        return filtered_tool_output(call.name, result, filters)

    def _approval_mode(self, agent=None):
        from .approval_settings import effective_mode
        from .storage import WorkspaceRepository

        return effective_mode(WorkspaceRepository(self.database), self.owner,
                              self.authorization_conversation_id, agent or self.root_agent,
                              parent_mode=self.parent_approval_mode)

    async def _dispatch(self, calls, state):
        from .routes import _repo

        calls = self._preflight_model_calls(calls, state)
        if len({call.call_id for call in calls}) != len(calls) or any(not call.call_id for call in calls):
            raise ValueError("Tool call IDs must be non-empty and unique")
        unresolved = [call for index, call in enumerate(calls) if replay_key(call, index) not in self.cache]
        enabled = {tool["function"]["name"] for tool in state.context.tools}
        if any(call.name not in enabled for call in unresolved):
            raise RuntimeSafetyError("Tool is not enabled for the current Agent")
        if self._publishes_tool_steps():
            for call in unresolved:
                self._tool_step(call)
        endpoints = _repo().setting(self.owner, "endpoints", {}) or {}
        policy = (endpoints.get("agents") or {}).get("toolApproval")
        from .approval_settings import call_decision

        mode = self._approval_mode(state.context.agent)
        ask = []
        questions = []
        for call in unresolved:
            decision = call_decision(mode, policy, call.name, call.arguments)
            if self._blocked_call(call):
                continue
            if decision and decision["decision"] == "deny":
                output = "Blocked: " + decision.get("reason", "Rejected by policy")
                record = {"proposal": {"name": call.name, "args": copy.deepcopy(call.arguments)}, "output": output}
                await self._completed(call, record)
                self.cache[replay_key(call, calls.index(call))] = record
            elif decision and decision["decision"] == "ask":
                ask.append(call)
            elif call.name == "ask_user_question":
                questions.append(call)
        if ask and self.background_deny:
            # LibreChat SubagentExecutor.executeDetached: a detached child cannot
            # park the parent generation for HITL; deny the protected tools.
            for requested in ask:
                blocked = "Blocked: Approval required for \"" + requested.name + "\" in background execution."
                record = {"proposal": {"name": requested.name,
                                       "args": copy.deepcopy(requested.arguments)}, "output": blocked}
                await self._completed(requested, record)
                self.cache[replay_key(requested, calls.index(requested))] = record
        elif ask:
            await self._pause(build_approval_payload(ask), state, approval=True)
        if questions and self.background_deny:
            for requested in questions:
                blocked = "Blocked: Ask User requires foreground human interaction."
                record = {"proposal": {"name": requested.name,
                                       "args": copy.deepcopy(requested.arguments)}, "output": blocked}
                await self._completed(requested, record)
                self.cache[replay_key(requested, calls.index(requested))] = record
        elif questions:
            if len(calls) != 1:
                raise ValueError("Ask User cannot run in parallel with another tool")
            await self._pause(build_ask_user_payload(questions[0].arguments, questions[0].call_id), state)
        await self._prepare_oauth(
            [call for call in unresolved if replay_key(call, calls.index(call)) not in self.cache], state,
        )
        outputs = await execute_tool_batch(
            calls, lambda call: self._filtered_invoke(call, state), settled=self.cache,
            interrupting_names=frozenset({"subagent"}),
            is_interrupt=lambda error: isinstance(error, AgentSuspended),
            check_breaker=self._check_grant, on_completed=self._completed,
        )
        commands = [output for output in outputs if isinstance(output, dict) and output.get("graph")]
        from .mcp_projection import mcp_tool_history_message

        messages = [mcp_tool_history_message(call, output, state.context.profile.provider)
                    for call, output in zip(calls, outputs, strict=True) if isinstance(output, str)]
        if not commands:
            return ToolBatchOutput(messages)
        combined = combine_handoff_commands(commands)
        self.route.finalize(combined, {"messages": state.messages, "handoffState": self.route.snapshot()}, self.active_config)
        # StateGraph is the sole owner of transfer scheduling. In particular,
        # never revive the former single-recipient context-switch fallback.
        if not self.graph_node:
            raise RuntimeSafetyError("Handoff commands require an active StateGraph node")
        return ToolBatchOutput(messages, graph_commands=combined)

    @staticmethod
    def _steer_message(item):
        content = merged_text(item)
        if item.get("files"):
            content += "\n\nController attachments (use authorized LSM file tools): " + json.dumps(
                item["files"], ensure_ascii=False,
            )
        return {"role": "user", "content": content, "source": "steer",
                "files": item.get("files") or [], "quotes": item.get("quotes") or [],
                **({'steerId': item['steerId'], 'id': 'steer:' + item['steerId']}
                   if isinstance(item.get('steerId'), str) else {})}

    def _reconcile_drained_steers(self, state):
        """Recover durable applied steers not yet included in a model checkpoint.

        drain() records an applied receipt before the graph snapshot. A crash
        in that window must not silently lose the accepted user instruction.
        Match stable steer identities, never the text of older user turns.
        If the interrupted checkpoint ends in pending tool calls, queue
        recovered steers until those tool results have been appended.
        """
        if self.namespace:
            return
        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'",
                (self.generation.run_id, self.owner),
            ).fetchone()
        if row is None:
            return
        parts = json.loads(row["state"]).get("steerParts") or []
        checkpoint_ids = {m.get('steerId') for m in state.messages
                          if isinstance(m, dict) and m.get('source') == 'steer'
                          and isinstance(m.get('steerId'), str)}
        missing = []
        for part in parts:
            if (not isinstance(part, dict) or not isinstance(part.get('steer'), str)
                    or not isinstance(part.get('steerId'), str)):
                continue
            if part['steerId'] not in checkpoint_ids:
                missing.append(self._steer_message(part))
                checkpoint_ids.add(part['steerId'])
        if state.pending_calls:
            self._pending_recovered_steers = missing
        else:
            state.messages.extend(missing)
            if missing:
                state.completed = False

    async def _summarize_history(self, messages, *, manual=False, max_tokens=2048,
                                 prompt=None, update_prompt=None, head_count=0,
                                 semantic_index=None, retained_tail=None, profile=None):
        """Request the original checkpoint prompt from the selected model.

        A failed/partial summary is never written, and never makes the old
        context unreachable. The live model receives the same intact history.
        """
        from .compaction import (
            DEFAULT_SUMMARIZATION_PROMPT,
            DEFAULT_UPDATE_SUMMARIZATION_PROMPT,
            build_summarization_instruction,
            build_summary_carrier_text,
        )
        from .tokenizer import count_tokens

        prior = ''
        for item in reversed(messages):
            text = item.get('content')
            if item.get('role') == 'system' and isinstance(text, str) and text.startswith('<summary>\n'):
                prior = text[len('<summary>\n'):].split('\n</summary>', 1)[0]
                break
        render_messages = messages
        if semantic_index is None and not self.namespace:
            # formatAgentMessages derives source indices from persisted host
            # content. Reconstruct only one-to-one tool outcomes verified by
            # the owner-bound SQLite ancestry and provider-visible text.
            from .semantic_index_source import derive_persisted_semantic_index

            semantic_index, render_messages = derive_persisted_semantic_index(
                self.database, self.owner, self.generation.conversation_id,
                self.generation.user_message_id, messages)
        semantic = render_compaction_semantic_index(semantic_index, render_messages)
        effective = build_summarization_instruction(
            prompt or DEFAULT_SUMMARIZATION_PROMPT,
            update_prompt or DEFAULT_UPDATE_SUMMARIZATION_PROMPT,
            prior or None,
            semantic['appendix'],
        )
        # The source renderer preserves JavaScript UTF-16 truncation semantics,
        # including a half-surrogate at an astral boundary. Preserve its
        # differential output; escape only invalid Unicode at the provider
        # HTTP JSON boundary so utf-8 encoding cannot abort compaction.
        effective = effective.encode('utf-8', 'backslashreplace').decode('utf-8')
        instruction = {'role': 'user', 'content': effective}
        summary_messages = [*messages, instruction]
        # Compaction must see the exact owner-scoped steering attachments that
        # ordinary generation sends; otherwise the checkpoint drops their text.
        from .content_filters import inspect_content, model_message_fragments
        from .steer_media import stamp_model_messages
        from .storage import WorkspaceRepository

        # The database and its attachment storage share the same state root.
        # Do not initialize global settings while summarizing: detached/test
        # runtimes can have a different workspace (or no writable /workspace).
        summary_messages = await stamp_model_messages(
            self.database, self.owner, summary_messages, self.database.root)
        policy = configured_filters(WorkspaceRepository(self.database), self.owner)
        if inspect_content(model_message_fragments(summary_messages), policy) is not None:
            raise RuntimeSafetyError('Summary context was blocked by content protection')
        chunks = []
        finish_reason = None
        limit = max(128, min(int(max_tokens), 16384))
        profile = profile or self.initial_profile or self._context(self.root_agent).profile
        if profile.provider in {"anthropic", "google"}:
            from .provider_tool_protocols import stream_native_tools

            response = stream_native_tools(profile, summary_messages, tools=[],
                                           max_tokens=limit, temperature=None,
                                           emit_finish_reason=True)
        else:
            response = self.stream_text(profile, summary_messages, max_tokens=limit,
                                        emit_finish_reason=True)
        async for value in response:
            if isinstance(value, str):
                chunks.append(value)
            elif isinstance(value, (ModelUsage, ModelThought)):
                # A summarizer's provider metadata must never be inserted into
                # user-visible checkpoint text or mistaken for a tool call.
                continue
            elif isinstance(value, ModelFinish):
                finish_reason = value.reason.lower()
            else:
                raise ValueError('Summary provider returned a tool call instead of text')
        summary = ''.join(chunks).strip()
        if not summary:
            raise ValueError('Summarization produced empty output')
        if finish_reason in {'length', 'max_tokens', 'max_tokens_reached', 'max_output_tokens',
                             'max_output_tokens_reached', 'incomplete'}:
            raise ValueError('Summary response was truncated by the provider output limit')
        # Some OpenAI-compatible endpoints omit finish_reason entirely. For
        # them, refuse near-limit output instead of committing a partial
        # checkpoint whose source conversation would become unreachable.
        if finish_reason in {None, 'unknown'} and count_tokens(summary, exact=False) >= limit * 0.85:
            raise ValueError('Summary completion is unverified near output token limit')
        count = count_tokens(build_summary_carrier_text(summary), exact=False)
        covered_calls = set()
        covered_steers = set()
        for message in messages:
            if message.get('role') == 'user' and message.get('source') == 'steer':
                ident = message.get('steerId')
                if isinstance(ident, str):
                    covered_steers.add(ident)
            if message.get('role') == 'assistant':
                covered_calls.update(call['id'] for call in message.get('tool_calls') or []
                                     if isinstance(call, dict) and isinstance(call.get('id'), str))
            elif message.get('role') == 'tool' and isinstance(message.get('tool_call_id'), str):
                covered_calls.add(message['tool_call_id'])
        self.store.stage_summary(self.owner, self.generation.run_id, summary, count,
                                 boundary=head_count, manual=manual,
                                 retained_tail=retained_tail,
                                 covered_tool_call_ids=sorted(covered_calls),
                                 covered_steer_ids=sorted(covered_steers),
                                 visible_text_boundary=len(self.partial_text),
                                 model_history_start=(
                                     sum(1 for message in messages if message.get('role') == 'system'
                                         and not (isinstance(message.get('content'), str)
                                                  and message['content'].startswith('<summary>\n')))
                                     + 1 + len(retained_tail))
                                 if retained_tail is not None and not manual and not self.namespace else None)
        if not self.namespace:
            import secrets
            identity = 'summary_' + secrets.token_hex(8)
            self.store.append(self.owner, self.generation.run_id, {
                'event': 'on_run_step_completed', 'data': {'result': {
                    'id': identity, 'type': 'summary', 'summary': {
                        'type': 'summary', 'content': [{'type': 'text', 'text': summary}],
                        'boundary': {'messageIndex': head_count}, 'tokenCount': count,
                        **({'initiatedBy': 'user'} if manual else {}),
                    }},},
            })
        return summary

    def _context_limit(self, state: AgentLoopState, settings: dict | None = None) -> int | None:
        """Resolve the explicit agent limit first, then this channel's model limit."""
        if settings is None:
            from .storage import WorkspaceRepository
            settings = WorkspaceRepository(self.database).setting(self.owner, 'endpoints', {}) or {}
        params = state.context.parameters or {}
        agents = settings.get('agents') or {}
        raw = (params.get('max_context_tokens') or params.get('maxContextTokens')
               or agents.get('maxContextTokens'))
        if type(raw) in (int, float) and 0 < raw <= 2_000_000:
            return int(raw)
        from .provider_profiles import profile

        channel = (state.context.agent or {}).get('provider')
        if not channel:
            with self.database.connect() as db:
                row = db.execute('SELECT state FROM runs WHERE id=?', (self.generation.run_id,)).fetchone()
            channel = (json.loads(row['state']).get('provider') if row else None)
        if not isinstance(channel, str) or not channel:
            return None
        try:
            stored = profile(channel)
        except ValueError:
            return None
        limit = (stored.get('model_contexts') or {}).get(state.context.profile.model)
        return limit if type(limit) is int and 0 < limit <= 2_000_000 else None

    async def _observe_model_usage(self, usage: ModelUsage, state: AgentLoopState) -> None:
        """Update cumulative raw/provider ratio only on genuine usage frames."""
        if self.namespace or usage.provider != state.context.profile.provider:
            return
        if usage.input_tokens <= 0:
            return
        from .context_budget import calculate_budget, provider_usage_snapshot

        # Persist actual provider counts on every confirmed primary call, even
        # when the model has no configured context limit. The previous path
        # only saved a calibrated estimate and skipped unknown limits entirely.
        try:
            from .storage import WorkspaceRepository
            settings = WorkspaceRepository(self.database).setting(self.owner, 'endpoints', {}) or {}
            options = settings.get('summarization') or {}
            ratio = options.get('reserveRatio', 0.05) if isinstance(options, dict) else 0.05
            calibration = self.store.token_calibration(self.owner, self.generation.run_id,
                state.context.profile.provider, state.context.profile.model)
            snapshot = provider_usage_snapshot(
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                provider=usage.provider, model=state.context.profile.model,
                messages=state.provider_projection or state.messages, tools=state.context.tools,
                max_context_tokens=self._context_limit(state, settings),
                reserve_ratio=ratio, calibration_ratio=calibration.ratio,
                run_id=self.generation.run_id,
                agent_id=(state.context.agent or {}).get('id'))
            self.store.record_context_usage(self.owner, self.generation.run_id, snapshot)
        except Exception as exc:
            logging.getLogger(__name__).warning('Provider context usage unavailable (%s)', type(exc).__name__)

        profile = state.context.profile
        try:
            estimate = calculate_budget(state.provider_projection or state.messages,
                                    state.context.tools, 2_000_000,
                                        reserve_ratio=0)
            instruction_overhead = estimate.instruction_tokens + estimate.tool_schema_tokens
            calibration = self.store.token_calibration(self.owner, self.generation.run_id,
                                                       profile.provider, profile.model)
            updated = calibration.observe(provider_input_tokens=usage.input_tokens,
                                          raw_sent_this_turn=estimate.message_tokens,
                                          instruction_overhead=instruction_overhead)
            if updated != calibration:
                self.store.record_token_calibration(self.owner, self.generation.run_id,
                                                    profile.provider, profile.model, updated)
        except Exception as exc:
            # Usage is observational metadata; a failed calibration update
            # cannot invalidate an otherwise successful model response.
            logging.getLogger(__name__).warning('Token calibration failed (%s)', type(exc).__name__)

    def _project_model_messages(self, state: AgentLoopState) -> list[dict]:
        from .agents import AgentRepository
        from .fading_projection import project_faded_provider_messages
        from .machine_permissions import machine_access_context
        from .storage import WorkspaceRepository

        agent = state.context.agent
        if (agent or {}).get("id"):
            # The dispatch gate also reloads the Agent ACL for every action.
            current = AgentRepository(self.database).get(self.owner, agent["id"])
            agent = current if current is not None else {"machine_default_permission": "none"}
        restrictions = machine_access_context(
            self.owner, self.authorization_conversation_id, agent=agent,
            scopes=set(self.scopes), expires=self.grant_expires,
            repo=WorkspaceRepository(self.database),
        )
        projected = project_faded_provider_messages(state.messages, state.context.fading_tier)
        if restrictions:
            return [{"role": "system", "content": restrictions}, *projected]
        return projected

    def _update_fading_tier(self, state: AgentLoopState, budget, calibration, config, window: int) -> None:
        from .fading import (
            resolve_fading_tier,
            seed_fading_tier,
        )

        profile = state.context.profile
        agent_id = (state.context.agent or {}).get('id') or 'default'
        current = state.context.fading_tier or self.store.fading_tier(
            self.owner, self.generation.run_id, agent_id, profile.provider, profile.model)
        seeded = seed_fading_tier(window, current)
        current_turn = []
        for message in reversed(state.messages):
            if message.get('role') == 'user':
                break
            current_turn.append(message)
        width = max((len(message.get('tool_calls') or []) for message in current_turn), default=1)
        effective = max(0, budget.available_for_messages / calibration.ratio)
        window_available = max(1, window - budget.reserve_tokens)
        pressure = (window - budget.reserve_tokens - budget.remaining_context_tokens) / window_available
        signals = {'contextPressure': pressure, 'effectiveRawTokens': effective,
                   'summarizationEnabled': config.get('enabled') is not False,
                   'toolExchangeWidth': max(1, width)}
        resolved = resolve_fading_tier(seeded, window, signals)
        state.context.fading_tier = resolved
        if resolved != current:
            self.store.record_fading_tier(self.owner, self.generation.run_id,
                                          agent_id, profile.provider, profile.model, resolved)

    async def _before_model(self, state):
        """SDK-style recency + trigger, using the shared SQLite checkpoint."""
        from .compaction import build_summary_carrier_text
        from .content_filters import inspect_content, model_message_fragments
        from .context_budget import (
            calculate_budget,
            should_trigger_summarization,
            split_recent_turns,
        )
        from .storage import WorkspaceRepository

        repository = WorkspaceRepository(self.database)
        policy = configured_filters(repository, self.owner)
        blocked = inspect_content(model_message_fragments(state.messages), policy)
        if blocked is not None:
            # No source text is copied into a model/user-visible error.
            raise RuntimeSafetyError('Assembled model context was blocked by content protection')
        if self.namespace:
            return
        settings = repository.setting(self.owner, 'endpoints', {}) or {}
        max_raw = self._context_limit(state, settings)
        if max_raw is None:
            return
        calibration = self.store.token_calibration(
            self.owner, self.generation.run_id,
            state.context.profile.provider, state.context.profile.model)
        try:
            config = settings.get('summarization') or {}
            if not isinstance(config, dict):
                config = {}
            budget = calculate_budget(state.messages, state.context.tools, int(max_raw),
                                      reserve_ratio=config.get('reserveRatio', 0.05),
                                      calibration_ratio=calibration.ratio)
            self._update_fading_tier(state, budget, calibration, config, int(max_raw))
            if config.get('enabled') is False or (budget.remaining_context_tokens > 0 and not isinstance(config.get('trigger'), dict)):
                return
            if len(state.messages) == self._last_compaction_attempt_size or self._summary_failures >= 3:
                return
            system = [message for message in state.messages if message.get('role') == 'system']
            messages = [message for message in state.messages if message.get('role') != 'system']
            retain = config.get('retainRecent') or {}
            head, tail = split_recent_turns(messages, turns=retain.get('turns', 2), tokens=retain.get('tokens'))
            if not should_trigger_summarization(
                messages_to_refine_count=len(head), trigger=config.get('trigger'),
                max_context_tokens=budget.max_context_tokens,
                pre_prune_context_tokens=budget.max_context_tokens - budget.remaining_context_tokens,
                remaining_context_tokens=budget.remaining_context_tokens,
            ):
                return
            self._last_compaction_attempt_size = len(state.messages)
            if budget.instruction_tokens + budget.tool_schema_tokens >= budget.max_context_tokens:
                return
            try:
                options = config.get('parameters') or {}
                summary = await self._summarize_history(
                    [*system, *head], head_count=len(head),
                    max_tokens=options.get('maxSummaryTokens', 2048),
                    prompt=config.get('prompt'), update_prompt=config.get('updatePrompt'),
                    semantic_index=state.context.compaction_semantic_index,
                    retained_tail=tail, profile=state.context.profile)
                # Keep stable instructions and current summary, then the exact
                # retained recent turns. Original messages stay in SQLite.
                plain_system = [message for message in system if not (
                    isinstance(message.get('content'), str)
                    and message['content'].startswith('<summary>\n'))]
                state.messages = [*plain_system, {'role': 'system', 'content': build_summary_carrier_text(summary)}, *tail]
                self._summary_failures = 0
                await self._save(state, [])
                # History length may return to its pre-compaction value after
                # the next tool batch. Do not suppress that distinct input as
                # if it were an attempted retry of the old oversized history.
                self._last_compaction_attempt_size = None
                # A committed summary replaces the old prefix; restore a
                # fresh v2 fading tier so past masking doesn't pin this run.
                from .fading import create_fading_tier

                state.context.fading_tier = create_fading_tier(int(max_raw))
                try:
                    self.store.record_fading_tier(
                        self.owner, self.generation.run_id,
                        (state.context.agent or {}).get('id') or 'default',
                        state.context.profile.provider, state.context.profile.model,
                        state.context.fading_tier)
                except Exception as error:
                    logging.getLogger(__name__).warning('Fading reset failed (%s)', type(error).__name__)
            except Exception:
                self._summary_failures += 1
                # The source leaves the state intact on summary failure; never
                # substitute an empty checkpoint or truncate a tool result.
                return

        finally:
            # The pinned frontend consumes this event before the model call and
            # reads the same last snapshot from response metadata after reload.
            from .context_budget import context_usage_snapshot

            config = settings.get('summarization') or {}
            ratio = config.get('reserveRatio', 0.05) if isinstance(config, dict) else 0.05
            snapshot = context_usage_snapshot(
                state.messages, state.context.tools, int(max_raw), reserve_ratio=ratio,
                run_id=self.generation.run_id,
                agent_id=(state.context.agent or {}).get('id'),
                calibration_ratio=calibration.ratio,
            )
            self.store.record_context_usage(self.owner, self.generation.run_id, snapshot)

    async def _manual_compact(self, history):
        from .storage import WorkspaceRepository
        settings = WorkspaceRepository(self.database).setting(self.owner, 'endpoints', {}) or {}
        config = settings.get('summarization') or {}
        if isinstance(config, dict) and config.get('enabled') is False:
            raise ValueError('Compaction is disabled for this deployment')
        config = config if isinstance(config, dict) else {}
        from .content_filters import inspect_content, model_message_fragments

        if inspect_content(model_message_fragments(history),
                           configured_filters(WorkspaceRepository(self.database), self.owner)) is not None:
            raise RuntimeSafetyError('Assembled model context was blocked by content protection')
        non_system = [message for message in history if message.get('role') != 'system']
        if not non_system:
            raise ValueError('Nothing to compact')
        await self._summarize_history(history, manual=True, head_count=len(non_system),
            max_tokens=(config.get('parameters') or {}).get('maxSummaryTokens', 2048),
            prompt=config.get('prompt'), update_prompt=config.get('updatePrompt'),
            semantic_index=self.compaction_semantic_index)
        # Explicit compaction, like its automatic counterpart, resets the
        # hysteresis ladder after the checkpoint was safely staged.
        params = self.initial_parameters or {}
        raw = params.get('max_context_tokens') or params.get('maxContextTokens') or (settings.get('agents') or {}).get('maxContextTokens')
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and 0 < raw <= 2_000_000:
            from .fading import create_fading_tier

            try:
                self.store.record_fading_tier(
                    self.owner, self.generation.run_id,
                    (self.root_agent or {}).get('id') or 'default',
                    self.initial_profile.provider, self.initial_profile.model,
                    create_fading_tier(int(raw)))
            except Exception as exc:
                logging.getLogger(__name__).warning('Manual fading reset failed (%s)', type(exc).__name__)
        return history

    async def run(self, history, *, recursion_limit=None):
        if not self.namespace and self.store.manual_compaction(self.owner, self.generation.run_id):
            return await self._manual_compact(history)
        from .graph_topology import admit_agent_graph

        topology = admit_agent_graph(self.owner, self.graph_definition, self.repository)
        if topology is not None and not self.graph_node:
            from .graph_runtime import run_multi_agent_graph

            return await run_multi_agent_graph(self, history, topology, recursion_limit=recursion_limit)
        restored = self.saver.get_tuple(self.config)
        context = self._context(self.root_agent, profile=self.initial_profile, selected_tools=self.selected_tools)
        if (not self.namespace or
                (self.graph_node and self.namespace.startswith('/graph:')) or
                '/subagent:' in self.namespace):
            from .skill_runtime import catalog

            skills_text = catalog(self.database, self.owner, self.root_agent)
            # Personal memory remains scoped to the main agent; delegated Agents
            # must independently receive their own selected Skill catalog.
            memory_text = self._memory_context(self.root_agent) if (
                not self.namespace or self.graph_node) else ''
            supplementary = []
            if memory_text:
                supplementary.append({'role': 'system', 'content': memory_text})
            if skills_text:
                supplementary.append({'role': 'system', 'content': skills_text})
            if not self.namespace:
                # The selection is stored on the exact user message in SQLite,
                # rather than carrying a transient HTTP field across retries.
                with self.database.connect() as db:
                    record = db.execute(
                        'SELECT m.metadata FROM messages m JOIN conversations c '
                        'ON c.id=m.conversation_id WHERE m.id=? AND c.owner=? '
                        'AND m.conversation_id=? AND m.role=\'user\'',
                        (self.generation.user_message_id, self.owner,
                         self.generation.conversation_id)).fetchone()
                if record is not None:
                    selected_ids = json.loads(record['metadata']).get('manualSkills') or []
                    if selected_ids:
                        from .skill_runtime import manual_context

                        selected_text = manual_context(self.database, self.owner,
                                                       self.root_agent, selected_ids)
                        if selected_text:
                            supplementary.append({'role': 'system', 'content': selected_text})
            if supplementary:
                # Preserve the built-in artifact/Agent system message as the
                # single leading prompt, appending Memory/Skill context to it.
                # Empty memories must never inject a second system message.
                index = 0
                while index < len(history) and history[index].get('role') == 'system':
                    index += 1
                if index:
                    last = dict(history[index - 1])
                    last['content'] = str(last['content']) + '\n\n' + '\n\n'.join(
                        item['content'] for item in supplementary)
                    history = [*history[:index - 1], last, *history[index:]]
                else:
                    history = [*supplementary, *history]
        state = AgentLoopState(context, history)
        if restored:
            self.active_config = restored["config"]
            snapshot = restored["checkpoint"]["channel_values"]
            current = self.repository.get(self.owner, snapshot["agent_id"]) if snapshot.get("agent_id") else None
            if snapshot.get("agent_id") and current is None:
                raise RuntimeSafetyError("Checkpoint Agent is no longer available")
            state = AgentLoopState(self._context(current, profile=self.initial_profile if (current or {}).get("id") == (self.root_agent or {}).get("id") else None,
                                                selected_tools=self.selected_tools), snapshot["messages"],
                                   snapshot["step"], snapshot["model_turn"],
                                   [ModelToolCall(**call) for call in snapshot.get("pending_calls", [])],
                                   snapshot.get("tool_step_started", False), snapshot.get("completed", False),
                                   snapshot.get("graph_commands", []))
            self.partial_text = snapshot.get("partial_text", self.partial_text)
            self.route.restore(snapshot.get("handoffState"))
            completed = [value for _, channel, value in restored["pendingWrites"] if channel == "messages"]
            if self.resume_namespace == self.namespace:
                completed.extend(message for message in self.resume_history or [] if message.get("role") == "tool")
            for index, call in enumerate(state.pending_calls):
                match = next((message for message in reversed(completed) if message.get("tool_call_id") == call.call_id), None)
                if match:
                    self.cache[replay_key(call, index)] = {"proposal": {"name": call.name, "args": copy.deepcopy(call.arguments)},
                                                         "output": match["content"]}
                    self.saver.put_writes(self.active_config, [("messages", match)], task_id=call.call_id)
        # Crash seam: the durable FIFO/event claim may have committed before
        # the model-loop checkpoint recorded its injected HumanMessage. Repair
        # against deterministic IDs, so retries and parallel graph reducers
        # never create a second public steer part.
        is_foreground = (not self.namespace or
                         (self.graph_node and self.namespace.startswith("/graph:")))
        self._pending_recovered_steers = []
        if is_foreground and not self.recovery_steers:
            self._reconcile_drained_steers(state)
        if is_foreground and self.recovery_steers:
            existing_steers = {message.get("steerId") for message in state.messages
                               if isinstance(message, dict)}
            for part in self.steers.applied_parts(self.owner, self.generation.run_id,
                                                   namespace=self.namespace):
                steer_id = part.get("steerId")
                if not isinstance(steer_id, str) or steer_id in existing_steers:
                    continue
                recovered = self._steer_message(part)
                # The checkpoint may still contain assistant tool calls without
                # their corresponding tool responses. Inject the recovered user
                # steer only after dispatch restores those responses.
                if state.pending_calls:
                    self._pending_recovered_steers.append(recovered)
                else:
                    state.messages.append(recovered)
                    state.completed = False
                existing_steers.add(steer_id)
        if recursion_limit is not None:
            state.context.recursion_limit = recursion_limit
        review = self.store.approved_review(self.owner, self.generation.run_id)
        if review and review.get("namespace", "") == self.namespace:
            self.resume_namespace = self.namespace
            self.approved_batch = self.store.approved_batch(self.owner, self.generation.run_id)
        if self.approved_batch is not None and self.resume_namespace == self.namespace:
            pending_ids = {call.call_id for call in state.pending_calls}
            remaining = tuple(entry for entry in self.approved_batch.entries
                              if entry.call_id in pending_ids)
            if not remaining:
                # The persisted checkpoint already passed ToolNode and model
                # execution resumed. Retiring the proof prevents a subsequent
                # restart from re-running tools that are no longer pending.
                completed_ids = {m.get('tool_call_id') for m in state.messages
                                 if isinstance(m, dict) and m.get('role') == 'tool'}
                expected_ids = {entry.call_id for entry in self.approved_batch.entries}
                if not expected_ids.issubset(completed_ids):
                    raise RuntimeSafetyError('Approved tool checkpoint is missing persisted outcomes')
                if review:
                    self.store.complete_approval_batch(self.owner, self.generation.run_id,
                                                       review['actionId'], state.messages, self.partial_text)
                self.approved_batch = None
                review = None
            else:
                self.approved_batch = ApprovalBatch(remaining)
        if self.approved_batch is not None and self.resume_namespace == self.namespace:
            # LibreChat ToolNode approval can precede a browser OAuth login.
            # Resolve all Action credentials before executing *any* reviewed
            # sibling; pending review proof remains in SQLite across login.
            reviewed_calls = [entry.tool_call() for entry in getattr(self.approved_batch, "entries", ())
                              if entry.decision["type"] in {"approve", "edit"} and
                              not any(call.call_id == entry.call_id and
                                      replay_key(call, index) in self.cache
                                      for index, call in enumerate(state.pending_calls))]
            await self._prepare_oauth(reviewed_calls, state)

            async def completed(result):
                original = next(call for call in state.pending_calls if call.call_id == result.call.call_id)
                record = {"proposal": {"name": original.name, "args": copy.deepcopy(original.arguments)}, "output": result.raw_content if result.raw_content is not None else result.content}
                self.cache[replay_key(original, state.pending_calls.index(original))] = record
                await self._completed(result.call, record,
                                      executed=getattr(result, "decision", "approve") in {"approve", "edit"})

            async def reviewed_dispatch(call):
                original = next(item for item in state.pending_calls if item.call_id == call.call_id)
                cached = self.cache.get(replay_key(original, state.pending_calls.index(original)))
                if cached:
                    return cached["output"]
                if call.name == "ask_user_question":
                    await self._pause(build_ask_user_payload(call.arguments, call.call_id), state)
                    raise AssertionError("Suspended question should not return")
                return await self._filtered_invoke(call, state)

            await execute_approval_batch(self.approved_batch, dispatch=reviewed_dispatch,
                                         on_completed=completed)
        async def emit(text):
            if not self.namespace:
                self.partial_text += text
            await self.on_text(text)

        async def inject(current, boundary):
            if not self.task_control_host or not self.task_control_id:
                return False
            ids = {m.get("id") for m in current.messages if isinstance(m, dict)}
            additions = self.task_control_host.pending(self.task_control_id, boundary, ids)
            if additions:
                current.messages.extend(additions)
                current.completed = False
                await self._save(current, [])
            self.task_control_host.acknowledge(
                self.task_control_id, boundary,
                {m.get("id") for m in current.messages if isinstance(m, dict) and m.get("id")},
            )
            return bool(additions)

        async def inject_steers(current, boundary):
            # A stolen Controller actor may not dequeue or publish a steer.
            self._check_grant()
            # Foreground graph nodes share the originating generation's user
            # steer queue. Detached subagents have their own control channel.
            # BEGIN IMMEDIATE drain elects one consumer in parallel fan-out.
            if self.namespace and not (self.graph_node and self.namespace.startswith("/graph:")):
                return False
            recovered = self._pending_recovered_steers if boundary == "post_tools" else []
            if recovered:
                self._pending_recovered_steers = []
            applied = self.steers.drain(self.owner, self.generation.run_id, boundary=boundary,
                                        actor_lease=self.actor_lease,
                                        recipient_namespace=self.namespace)
            if (recovered or applied) and self.on_injected is not None:
                await self.on_injected()
            current.messages.extend(recovered)
            for item in applied:
                # The graph checkpoint contains only durable owned references.
                # Encode actual media per provider request, never persist base64.
                current.messages.append({"role": "user", "content": merged_text(item),
                                         "source": "steer", "steerId": item["steerId"],
                                         "id": "steer:" + item["steerId"],
                                         "files": item.get("files", [])})
            return bool(recovered or applied)

        async def should_seal_stream():
            # Check even tool-only provider chunks: they produce no on_text
            # callback, but may otherwise schedule irreversible tools.
            self._check_grant()
            owns_user_queue = (not self.namespace or
                               (self.graph_node and self.namespace.startswith("/graph:")))
            return owns_user_queue and self.steers.has_preempt(self.owner, self.generation.run_id)

        async def prepared_provider_messages(messages):
            from ..settings import get_settings
            from .content_filters import inspect_content, model_message_fragments
            from .steer_media import stamp_model_messages
            from .storage import WorkspaceRepository

            prepared = await stamp_model_messages(self.database, self.owner, messages,
                                                  get_settings().state_dir)
            # Before-model inspection covers canonical checkpoint messages, but
            # steer_media can add text from an owned file only at provider time.
            # Check the exact expanded request before either provider stream.
            if any(message.get('role') == 'user' and message.get('source') == 'steer'
                   and message.get('files') for message in messages):
                policy = configured_filters(WorkspaceRepository(self.database), self.owner)
                if inspect_content(model_message_fragments(prepared), policy) is not None:
                    raise RuntimeSafetyError('Assembled model context was blocked by content protection')
            return prepared

        async def stream_tools_with_media(profile, messages, **kwargs):
            prepared = await prepared_provider_messages(messages)
            async for event in self.stream_tools(profile, prepared, **kwargs):
                yield event

        async def stream_text_with_media(profile, messages, **kwargs):
            prepared = await prepared_provider_messages(messages)
            async for event in self.stream_text(profile, prepared, **kwargs):
                yield event

        result = await run_agent_loop(
            state, stream_tools=stream_tools_with_media, stream_text=stream_text_with_media,
            dispatch=self._dispatch, on_text=emit, on_thought=self.on_thought,
            save_state=self._save,
            before_model=self._before_model, on_model_usage=self._observe_model_usage,
            project_messages=self._project_model_messages,
            preflight_calls=self._preflight_model_calls,
            on_boundary=inject_steers, on_stream_chunk=should_seal_stream,
            inject_controls=inject if self.task_control_host else None,
            should_preempt=(lambda: self.task_control_host.has_interrupt(self.task_control_id))
            if self.task_control_host and self.task_control_id else None,
        )
        self.graph_commands = state.graph_commands
        if review and review.get("namespace", "") == self.namespace:
            self.store.complete_approval_batch(self.owner, self.generation.run_id,
                                               review["actionId"], result, self.partial_text,
                                               actor_lease=self.actor_lease)
        return result
