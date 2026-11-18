"""Connect source-ported Agent nodes to existing LSM dispatch and SQLite state."""

from __future__ import annotations

import copy
import hashlib
import json
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
    approval_policy_decision,
    ask_user_approval_policy,
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
from .providers import ModelToolCall, provider_config, selected_provider
from .steering import SteeringStore, merged_text
from .subagents import MAX_SUBAGENT_DEPTH, build_subagent_configs, invoke_subagent, subagent_tools


class AgentRunner:
    def __init__(self, owner, generation, database, store, *, scopes, grant_expires,
                 stream_tools, stream_text, on_text, agent=None, profile=None,
                 parameters=None, ask_user_enabled=False, mcp_enabled=False,
                 namespace="", child_configs=None, selected_tools=None,
                 resume_history=None, resume_namespace="", partial_text="",
                 approved_batch=None, graph_node=False, graph_definition=None,
                 graph_entry_id=None, graph_parallel=False, graph_max_handoffs=None,
                 authorization_conversation_id=None, background_deny=False,
                 task_control_host=None, task_control_id=None, subagent_depth=MAX_SUBAGENT_DEPTH,
                 on_injected=None, wakeup_lease=None, actor_lease=None, recovery_steers=False):
        self.on_injected = on_injected
        self.owner, self.generation, self.database, self.store = owner, generation, database, store
        self.scopes, self.grant_expires = scopes, grant_expires
        self.stream_tools, self.stream_text, self.on_text = stream_tools, stream_text, on_text
        self.root_agent, self.initial_profile = agent, profile
        self.graph_definition = graph_definition if graph_definition is not None else agent
        self.graph_node = graph_node
        self.graph_entry_id = graph_entry_id or (self.graph_definition or {}).get("id") or "default"
        self.graph_parallel = graph_parallel
        self.graph_max_handoffs = graph_max_handoffs
        self.authorization_conversation_id = authorization_conversation_id or generation.conversation_id
        self.background_deny = background_deny
        self.task_control_host, self.task_control_id = task_control_host, task_control_id
        self.subagent_depth = subagent_depth
        self.wakeup_lease = wakeup_lease
        self.actor_lease = actor_lease
        self.recovery_steers = recovery_steers
        self.initial_parameters = parameters or {}
        self.ask_user_enabled, self.mcp_enabled = ask_user_enabled, mcp_enabled
        self.namespace, self.child_configs, self.selected_tools = namespace, child_configs, selected_tools
        self.resume_history, self.resume_namespace = resume_history, resume_namespace
        self.partial_text, self.approved_batch = partial_text, approved_batch
        self.repository = AgentRepository(database)
        self.saver = SQLiteCheckpointSaver(database, owner, actor_lease=actor_lease)
        self.steers = SteeringStore(database)
        self.config = self.saver.config(generation.conversation_id, generation.run_id,
                                       checkpoint_ns=namespace, event_actor=True)
        self.active_config = self.config
        self.cache = {}
        self.configs = {}
        self.route = HandoffRouting(self.graph_entry_id, self.graph_max_handoffs, self.graph_parallel)

    def _check_grant(self):
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

    def _context(self, agent, *, profile=None, selected_tools=None):
        from .graph_topology import admit_agent_graph
        from .lsm_tool_registry import available_tools
        from .nested_mcp import nested_tools

        self._check_grant()
        admit_agent_graph(self.owner, self.graph_definition, self.repository)
        selected = set(selected_tools if selected_tools is not None else (agent or {}).get("tools") or [])
        unrestricted = agent is None and selected_tools is None
        native = available_tools(self.owner, self.authorization_conversation_id,
                                 scopes=set(self.scopes), expires=self.grant_expires)
        tools = [tool for tool in native if unrestricted or tool["function"]["name"] in selected
                 or tool["function"]["name"] in {"session_manage", "plan_manage"}]
        if self.mcp_enabled:
            tools += [tool for tool in nested_tools()
                      if unrestricted or tool["function"]["name"] in selected]
        if self.ask_user_enabled and (unrestricted or "ask_user_question" in selected):
            tools += ASK_USER_TOOLS
        identity = (agent or {}).get("id") or "default"
        configs = self.child_configs if self.child_configs is not None else build_subagent_configs(
            self.owner, agent, self.database,
        )
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
        override = (agent or {}).get("recursion_limit")
        limit = override if type(override) in (int, float) and override > 0 else 50
        return AgentContext(profile or provider_config(selected_provider({}, agent), (agent or {}).get("model")),
                            tools, (agent or {}).get("model_parameters") or self.initial_parameters,
                            recursion_limit=limit, tool_end=bool((agent or {}).get("end_after_tools")), agent=agent)

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
        """Bound SSE argument previews; persisted/native arguments remain complete."""
        args = call.arguments
        raw = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) <= 16 * 1024:
            return args
        return {"_truncated": True, "preview": raw.encode("utf-8")[:8192].decode(
            "utf-8", errors="ignore"), "note": "Full arguments retained for execution"}

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

    async def _completed(self, call, record):
        output = record["output"]
        if isinstance(output, str):
            self.saver.put_writes(self.active_config, [("messages", {
                "role": "tool", "tool_call_id": call.call_id, "content": output,
            })], task_id=call.call_id)
        if self.namespace and not self.graph_node:
            from .action_spec import is_action_tool

            if is_action_tool(call.name):
                self.store.oauth_dispatch(self.owner, self.generation.run_id, call.call_id, "completed")
            return
        step = self._tool_step(call)
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
        event = {
            "event": "on_run_step_completed", "data": {"result": {
                "id": step["id"], "index": step["index"], "completed_at": int(time.time() * 1000),
                "type": "tool_call", "tool_call": {
                    "id": call.call_id, "name": call.name, "args": self._visible_tool_args(call),
                    "type": "tool_call", "output": preview, "progress": 1,
                },
            }},
        }
        # Persist the completion evidence with its Controller file links.
        from .action_spec import is_action_tool
        from .tool_attachments import controller_tool_file_ids

        identities = controller_tool_file_ids(output)
        if identities:
            self.store.append_tool_completion(
                self.owner, self.generation.run_id, event, call.call_id, identities,
                actor_lease=self.actor_lease,
            )
        else:
            self.store.append(self.owner, self.generation.run_id, event,
                              actor_lease=self.actor_lease)
        if is_action_tool(call.name):
            self.store.oauth_dispatch(self.owner, self.generation.run_id, call.call_id, "completed")

    async def _invoke(self, call, state):
        from .lsm_tool_registry import call_tool
        from .nested_mcp import approved_call, discover

        self._check_grant()
        if call.name not in {tool["function"]["name"] for tool in state.context.tools}:
            raise RuntimeSafetyError("Tool is not enabled for the current Agent")
        if call.name == "check_background_task":
            from .subagent_task_host import SQLiteSubagentTaskHost

            host = SQLiteSubagentTaskHost(
                self.database, self.owner, self.authorization_conversation_id,
                stream_tools=self.stream_tools, stream_text=self.stream_text,
            )
            return await host.check(call.arguments, tool_call_id=call.call_id,
                                    parent_run_id=self.generation.run_id,
                                    parent_agent_id=(state.context.agent or {}).get("id", "default"))
        if call.name == "subagent":
            from .subagent_task_host import SQLiteSubagentTaskHost

            host = SQLiteSubagentTaskHost(
                self.database, self.owner, self.authorization_conversation_id,
                stream_tools=self.stream_tools, stream_text=self.stream_text,
            )
            return await invoke_subagent(
                call, self.configs[(state.context.agent or {}).get("id") or "default"],
                execute_child=self._child, start_background=lambda invocation, thread: host.start(
                    invocation, thread_id=thread, mcp_enabled=self.mcp_enabled), owner=self.owner,
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
            edge = handoff_edge_for_call(self.owner, graph, self.repository, call.name,
                                         source_agent_id=current["id"])
            return build_handoff_command(edge, current["id"], current.get("name") or current["id"],
                                         call.name, call.arguments, call.call_id, state.messages)
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
                return await discover(self.owner, self.authorization_conversation_id, set(self.scopes), call)
            if call.name == "mcp_tool_call":
                return await approved_call(self.owner, self.authorization_conversation_id, set(self.scopes), call)
            return await call_tool(self.owner, self.generation.conversation_id, call,
                                   granted_scopes=set(self.scopes), grant_expires=self.grant_expires,
                                   run_id=self.generation.run_id,
                                   authorization_conversation_id=self.authorization_conversation_id)
        except PermissionError as error:
            raise RuntimeSafetyError(str(error)) from error
        except Exception as error:
            # Native/provider exceptions may contain credentials or headers.
            # Keep their type for recovery without copying secrets to the model.
            return "Tool failed (" + type(error).__name__ + ")"

    async def _child(self, invocation):
        async def quiet(text):
            pass

        child = AgentRunner(self.owner, self.generation, self.database, self.store,
                            scopes=self.scopes, grant_expires=self.grant_expires,
                            stream_tools=self.stream_tools, stream_text=self.stream_text,
                            on_text=quiet, agent=invocation.agent, mcp_enabled=self.mcp_enabled,
                            namespace=self.namespace + "/subagent:" + invocation.parent_tool_call_id,
                            child_configs=invocation.child_configs, selected_tools=invocation.selected_tools,
                            resume_history=self.resume_history, resume_namespace=self.resume_namespace,
                            partial_text=self.partial_text,
                            authorization_conversation_id=self.authorization_conversation_id,
                            background_deny=self.background_deny,
                            task_control_host=self.task_control_host, task_control_id=self.task_control_id,
                            subagent_depth=invocation.remaining_depth,
                            wakeup_lease=self.wakeup_lease, actor_lease=self.actor_lease,
                            recovery_steers=self.recovery_steers)
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

    async def _dispatch(self, calls, state):
        from .routes import _repo

        if len({call.call_id for call in calls}) != len(calls) or any(not call.call_id for call in calls):
            raise ValueError("Tool call IDs must be non-empty and unique")
        unresolved = [call for index, call in enumerate(calls) if replay_key(call, index) not in self.cache]
        enabled = {tool["function"]["name"] for tool in state.context.tools}
        if any(call.name not in enabled for call in unresolved):
            raise RuntimeSafetyError("Tool is not enabled for the current Agent")
        if not self.namespace or self.graph_node:
            for call in unresolved:
                self._tool_step(call)
        endpoints = _repo().setting(self.owner, "endpoints", {}) or {}
        policy = (endpoints.get("agents") or {}).get("toolApproval")
        ask = []
        questions = []
        for call in unresolved:
            selected_policy = ask_user_approval_policy(policy) if call.name == "ask_user_question" else policy
            decision = approval_policy_decision(selected_policy, call.name)
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
            calls, lambda call: self._invoke(call, state), settled=self.cache,
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

    async def run(self, history, *, recursion_limit=None):
        from .graph_topology import admit_agent_graph

        topology = admit_agent_graph(self.owner, self.graph_definition, self.repository)
        if topology is not None and not self.graph_node:
            from .graph_runtime import run_multi_agent_graph

            return await run_multi_agent_graph(self, history, topology, recursion_limit=recursion_limit)
        restored = self.saver.get_tuple(self.config)
        context = self._context(self.root_agent, profile=self.initial_profile, selected_tools=self.selected_tools)
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
        if is_foreground and self.recovery_steers:
            existing_steers = {message.get("steerId") for message in state.messages
                               if isinstance(message, dict)}
            for part in self.steers.applied_parts(self.owner, self.generation.run_id,
                                                   namespace=self.namespace):
                steer_id = part.get("steerId")
                if not isinstance(steer_id, str) or steer_id in existing_steers:
                    continue
                state.messages.append({"role": "user", "content": merged_text(part),
                                       "source": "steer", "steerId": steer_id,
                                       "id": "steer:" + steer_id, "files": part.get("files", [])})
                existing_steers.add(steer_id)
                state.completed = False
        if recursion_limit is not None:
            state.context.recursion_limit = recursion_limit
        review = self.store.approved_review(self.owner, self.generation.run_id)
        if review and review.get("namespace", "") == self.namespace:
            self.resume_namespace = self.namespace
            self.approved_batch = self.store.approved_batch(self.owner, self.generation.run_id)
        if self.approved_batch is not None and self.resume_namespace == self.namespace:
            # LibreChat ToolNode approval can precede a browser OAuth login.
            # Resolve all Action credentials before executing *any* reviewed
            # sibling; pending review proof remains in SQLite across login.
            reviewed_calls = [entry.tool_call() for entry in self.approved_batch.entries
                              if entry.decision["type"] in {"approve", "edit"} and
                              not any(call.call_id == entry.call_id and
                                      replay_key(call, index) in self.cache
                                      for index, call in enumerate(state.pending_calls))]
            await self._prepare_oauth(reviewed_calls, state)

            async def completed(result):
                original = next(call for call in state.pending_calls if call.call_id == result.call.call_id)
                record = {"proposal": {"name": original.name, "args": copy.deepcopy(original.arguments)}, "output": result.raw_content if result.raw_content is not None else result.content}
                self.cache[replay_key(original, state.pending_calls.index(original))] = record
                await self._completed(original, record)

            async def reviewed_dispatch(call):
                original = next(item for item in state.pending_calls if item.call_id == call.call_id)
                cached = self.cache.get(replay_key(original, state.pending_calls.index(original)))
                if cached:
                    return cached["output"]
                if call.name == "ask_user_question":
                    await self._pause(build_ask_user_payload(call.arguments, call.call_id), state)
                    raise AssertionError("Suspended question should not return")
                return await self._invoke(call, state)

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
            applied = self.steers.drain(self.owner, self.generation.run_id, boundary=boundary,
                                        actor_lease=self.actor_lease,
                                        recipient_namespace=self.namespace)
            if applied and self.on_injected is not None:
                await self.on_injected()
            for item in applied:
                # The graph checkpoint contains only durable owned references.
                # Encode actual media per provider request, never persist base64.
                current.messages.append({"role": "user", "content": merged_text(item),
                                         "source": "steer", "steerId": item["steerId"],
                                         "id": "steer:" + item["steerId"],
                                         "files": item.get("files", [])})
            return bool(applied)

        async def should_seal_stream():
            # Check even tool-only provider chunks: they produce no on_text
            # callback, but may otherwise schedule irreversible tools.
            self._check_grant()
            owns_user_queue = (not self.namespace or
                               (self.graph_node and self.namespace.startswith("/graph:")))
            return owns_user_queue and self.steers.has_preempt(self.owner, self.generation.run_id)

        async def stream_tools_with_media(profile, messages, **kwargs):
            from ..settings import get_settings
            from .steer_media import stamp_model_messages

            prepared = await stamp_model_messages(self.database, self.owner, messages, get_settings().state_dir)
            async for event in self.stream_tools(profile, prepared, **kwargs):
                yield event

        async def stream_text_with_media(profile, messages, **kwargs):
            from ..settings import get_settings
            from .steer_media import stamp_model_messages

            prepared = await stamp_model_messages(self.database, self.owner, messages, get_settings().state_dir)
            async for event in self.stream_text(profile, prepared, **kwargs):
                yield event

        result = await run_agent_loop(
            state, stream_tools=stream_tools_with_media, stream_text=stream_text_with_media,
            dispatch=self._dispatch, on_text=emit, save_state=self._save,
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
