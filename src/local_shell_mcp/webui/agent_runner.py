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
    build_approval_payload,
    execute_approval_batch,
    truncate_approval_result,
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
    receive_handoff,
)
from .providers import ModelToolCall, provider_config, selected_provider
from .subagents import build_subagent_configs, invoke_subagent, subagent_tools


class AgentRunner:
    def __init__(self, owner, generation, database, store, *, scopes, grant_expires,
                 stream_tools, stream_text, on_text, agent=None, profile=None,
                 parameters=None, ask_user_enabled=False, mcp_enabled=False,
                 namespace="", child_configs=None, selected_tools=None,
                 resume_history=None, resume_namespace="", partial_text="",
                 approved_batch=None):
        self.owner, self.generation, self.database, self.store = owner, generation, database, store
        self.scopes, self.grant_expires = scopes, grant_expires
        self.stream_tools, self.stream_text, self.on_text = stream_tools, stream_text, on_text
        self.root_agent, self.initial_profile = agent, profile
        self.initial_parameters = parameters or {}
        self.ask_user_enabled, self.mcp_enabled = ask_user_enabled, mcp_enabled
        self.namespace, self.child_configs, self.selected_tools = namespace, child_configs, selected_tools
        self.resume_history, self.resume_namespace = resume_history, resume_namespace
        self.partial_text, self.approved_batch = partial_text, approved_batch
        self.repository = AgentRepository(database)
        self.saver = SQLiteCheckpointSaver(database, owner)
        self.config = self.saver.config(generation.conversation_id, generation.run_id,
                                       checkpoint_ns=namespace, event_actor=True)
        self.active_config = self.config
        self.cache = {}
        self.configs = {}
        self.route = HandoffRouting((agent or {}).get("id") or "default")

    def _check_grant(self):
        if self.grant_expires is not None and self.grant_expires <= time.time():
            raise RuntimeSafetyError("Authentication grant expired")

    def _context(self, agent, *, profile=None, selected_tools=None):
        from .graph_topology import admit_agent_graph
        from .lsm_tool_registry import available_tools
        from .nested_mcp import nested_tools

        self._check_grant()
        admit_agent_graph(self.owner, self.root_agent, self.repository)
        selected = set(selected_tools if selected_tools is not None else (agent or {}).get("tools") or [])
        unrestricted = agent is None and selected_tools is None
        native = available_tools(self.owner, self.generation.conversation_id,
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
        self.configs[identity] = configs
        tools += subagent_tools(configs)
        if agent is not None:
            from .actions import ActionRepository
            tools += ActionRepository(self.database).tool_schemas(self.owner, agent)
        if self.root_agent:
            tools += handoff_tools(self.owner, self.root_agent, self.repository, source_agent_id=identity)
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
                "partial_text": self.partial_text, "handoffState": self.route.snapshot()}

    async def _save(self, state, calls):
        if calls and not state.tool_step_started:
            self.cache = {}
        identity = f"{time.time_ns():020d}"
        self.active_config = self.saver.put(self.active_config, {
            "v": 1, "id": identity, "channel_values": self._snapshot(state),
            "channel_versions": {"messages": state.step}, "versions_seen": {},
        }, {"source": "loop", "step": state.step})

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
                        "args": call.arguments,
                    }],
                }}
        self.store.append(self.owner, self.generation.run_id, {"event": "on_run_step", "data": step})
        return step

    async def _completed(self, call, record):
        output = record["output"]
        if isinstance(output, str):
            self.saver.put_writes(self.active_config, [("messages", {
                "role": "tool", "tool_call_id": call.call_id, "content": output,
            })], task_id=call.call_id)
        if self.namespace:
            return
        step = self._tool_step(call)
        preview = output if isinstance(output, str) else "Agent control transferred"
        preview = preview.encode("utf-8")[:128 * 1024].decode("utf-8", errors="ignore")
        self.store.append(self.owner, self.generation.run_id, {
            "event": "on_run_step_completed", "data": {"result": {
                "id": step["id"], "index": step["index"], "completed_at": int(time.time() * 1000),
                "type": "tool_call", "tool_call": {
                    "id": call.call_id, "name": call.name, "args": call.arguments,
                    "type": "tool_call", "output": preview, "progress": 1,
                },
            }},
        })

    async def _invoke(self, call, state):
        from .lsm_tool_registry import call_tool
        from .nested_mcp import approved_call, discover

        self._check_grant()
        if call.name not in {tool["function"]["name"] for tool in state.context.tools}:
            raise RuntimeSafetyError("Tool is not enabled for the current Agent")
        if call.name == "subagent":
            return await invoke_subagent(
                call, self.configs[(state.context.agent or {}).get("id") or "default"],
                execute_child=self._child, owner=self.owner,
                conversation_id=self.generation.conversation_id, parent_run_id=self.generation.run_id,
                scopes=frozenset(self.scopes), grant_expires=self.grant_expires, database=self.database,
                propagate_error=lambda error: isinstance(error, (AgentSuspended, RuntimeSafetyError)),
            )
        if is_transfer_tool(call.name):
            current = state.context.agent or {}
            graph = self.repository.get(self.owner, self.root_agent["id"])
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
                return await invoke_action(self.owner, current_id, call.name, call.arguments, self.database)
            if call.name in {"mcp_tool_search", "mcp_tool_inspect"}:
                return await discover(self.owner, self.generation.conversation_id, set(self.scopes), call)
            if call.name == "mcp_tool_call":
                return await approved_call(self.owner, self.generation.conversation_id, set(self.scopes), call)
            return await call_tool(self.owner, self.generation.conversation_id, call,
                                   granted_scopes=set(self.scopes), grant_expires=self.grant_expires)
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
                            partial_text=self.partial_text)
        return await child.run(invocation.messages, recursion_limit=invocation.recursion_limit)

    async def _pause(self, payload, state, *, approval=False):
        import uuid

        pending = {"actionId": "action_" + uuid.uuid4().hex,
                   "streamId": self.generation.conversation_id,
                   "conversationId": self.generation.conversation_id,
                   "runId": self.generation.run_id,
                   "responseMessageId": self.generation.response_message_id,
                   "createdAt": int(time.time() * 1000), "namespace": self.namespace, "payload": payload}
        self.saver.put_writes(self.active_config, [("__interrupt__", pending)], task_id="human")
        pause = self.store.pause_for_approval if approval else self.store.pause_for_question
        if not pause(self.owner, self.generation.run_id, pending, state.messages, self.partial_text):
            raise RuntimeError("Unable to save pending Agent action")
        raise AgentSuspended()

    async def _dispatch(self, calls, state):
        from .routes import _repo

        if len({call.call_id for call in calls}) != len(calls) or any(not call.call_id for call in calls):
            raise ValueError("Tool call IDs must be non-empty and unique")
        if sum(is_transfer_tool(call.name) for call in calls) > 1:
            raise RuntimeSafetyError("Parallel handoff recipients require the source StateGraph executor")
        unresolved = [call for index, call in enumerate(calls) if replay_key(call, index) not in self.cache]
        enabled = {tool["function"]["name"] for tool in state.context.tools}
        if any(call.name not in enabled for call in unresolved):
            raise RuntimeSafetyError("Tool is not enabled for the current Agent")
        if not self.namespace:
            for call in unresolved:
                self._tool_step(call)
        asking = [call for call in unresolved if call.name == "ask_user_question"]
        if asking:
            if len(calls) != 1:
                raise ValueError("Ask User cannot run in parallel with another tool")
            await self._pause(build_ask_user_payload(asking[0].arguments, asking[0].call_id), state)
        endpoints = _repo().setting(self.owner, "endpoints", {}) or {}
        policy = (endpoints.get("agents") or {}).get("toolApproval")
        ask = []
        for call in unresolved:
            decision = approval_policy_decision(policy, call.name)
            if decision and decision["decision"] == "deny":
                output = "Blocked: " + decision.get("reason", "Rejected by policy")
                record = {"proposal": {"name": call.name, "args": copy.deepcopy(call.arguments)}, "output": output}
                await self._completed(call, record)
                self.cache[replay_key(call, calls.index(call))] = record
            elif decision and decision["decision"] == "ask":
                ask.append(call)
        if ask:
            await self._pause(build_approval_payload(ask), state, approval=True)
        outputs = await execute_tool_batch(
            calls, lambda call: self._invoke(call, state), settled=self.cache,
            interrupting_names=frozenset({"subagent"}),
            is_interrupt=lambda error: isinstance(error, AgentSuspended),
            check_breaker=self._check_grant, on_completed=self._completed,
        )
        commands = [output for output in outputs if isinstance(output, dict) and output.get("graph")]
        messages = [{"role": "tool", "tool_call_id": call.call_id,
                     "content": truncate_approval_result(output, 400_000)}
                    for call, output in zip(calls, outputs, strict=True) if isinstance(output, str)]
        if not commands:
            return ToolBatchOutput(messages)
        combined = combine_handoff_commands(commands)
        self.route.finalize(combined, {"messages": state.messages, "handoffState": self.route.snapshot()}, self.active_config)
        recipients = []
        for command in combined:
            goto = command["goto"]
            if isinstance(goto, str):
                recipients.append((goto, command.get("update") or {}))
            else:
                recipients.extend((send["node"], send["args"]) for send in goto)
        if len(recipients) != 1:
            raise ValueError("Parallel handoff recipients require the graph fan-out executor")
        destination, update = recipients[0]
        target = self.repository.get(self.owner, destination)
        if target is None:
            raise RuntimeSafetyError("Handoff destination is no longer available")
        received = receive_handoff(update.get("messages") or [], destination)
        history = received["filteredMessages"] if received else update.get("messages") or []
        history = [message for message in history if message.get("role") != "system"]
        instructions = target.get("instructions") or ""
        if received and received.get("instructions"):
            instructions += "\n\n" + received["instructions"]
        if instructions:
            history.insert(0, {"role": "system", "content": instructions})
        return ToolBatchOutput(messages, next_context=self._context(target), replace_messages=history)

    async def run(self, history, *, recursion_limit=None):
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
                                   snapshot.get("tool_step_started", False), snapshot.get("completed", False))
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
        if recursion_limit is not None:
            state.context.recursion_limit = recursion_limit
        review = self.store.approved_review(self.owner, self.generation.run_id)
        if review and review.get("namespace", "") == self.namespace:
            self.resume_namespace = self.namespace
            self.approved_batch = self.store.approved_batch(self.owner, self.generation.run_id)
        if self.approved_batch is not None and self.resume_namespace == self.namespace:
            async def completed(result):
                original = next(call for call in state.pending_calls if call.call_id == result.call.call_id)
                record = {"proposal": {"name": original.name, "args": copy.deepcopy(original.arguments)}, "output": result.raw_content if result.raw_content is not None else result.content}
                self.cache[replay_key(original, state.pending_calls.index(original))] = record
                await self._completed(original, record)

            async def reviewed_dispatch(call):
                original = next(item for item in state.pending_calls if item.call_id == call.call_id)
                cached = self.cache.get(replay_key(original, state.pending_calls.index(original)))
                return cached["output"] if cached else await self._invoke(call, state)

            await execute_approval_batch(self.approved_batch, dispatch=reviewed_dispatch,
                                         on_completed=completed)
        async def emit(text):
            if not self.namespace:
                self.partial_text += text
            await self.on_text(text)

        result = await run_agent_loop(state, stream_tools=self.stream_tools, stream_text=self.stream_text,
                                      dispatch=self._dispatch, on_text=emit, save_state=self._save)
        if review and review.get("namespace", "") == self.namespace:
            self.store.complete_approval_batch(self.owner, self.generation.run_id,
                                               review["actionId"], result, self.partial_text)
        return result
