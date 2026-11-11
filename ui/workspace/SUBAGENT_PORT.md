# Subagent source port boundary

Sources: LibreChat `e8f3be08623663d4ad7f7241e693c94469b63bb0`,
@librechat/agents 4.0.1 `c4ffb9b1b78421bf63eba3e56993017f922387f3`.

| Upstream function | Python | Verification |
| --- | --- | --- |
| `SubagentTool.ts:buildSubagentToolParams` | `webui/subagents.py:build_subagent_tool_params` | Exact Node schema/description differential across four host capability combinations |
| `agents/config.ts:resolveRecursionLimit/resolveSubagentMaxTurns` | `resolve_subagent_max_turns` | 45 original Node cascade cases |
| `agents/run.ts:buildSubagentConfigs` | `build_subagent_configs` | Enabled/allowSelf defaults, explicit owner-scoped agents, ancestor pruning, depth5/config100 bounds, isolated selected tools |
| `Graph.ts:createAgentNode` wrapper | `invoke_subagent` | Original description fallback, optional thread rejection, injected shared child runtime, no parent transcript |
| `SubagentExecutor.ts:filterSubagentResult` | `filter_subagent_result` | 126 original Node result-projection cases; reasoning/tool data excluded |

Canonical tool name is `subagent`; arguments are `description` and `subagent_type`
with the source optional `intent` label. No `delegate_agent` alias is introduced.
The host does not advertise detached/background/thread fields until a task store
is implemented. Child graphs preserve their own selected tools and original
recursion budget; every native dispatch remains subject to the inherited parent
machine policy/scopes and grant expiry through the existing MCP registry.

The callback integration test performs three actual provider SSE requests with
native `file_read` and `file_write`, returns only final text, and verifies that a
revoked write grant prevents the next child from writing. This is independent of
production model credentials.

## Remaining integration requirements

The production shared graph must invoke this adapter and preserve its structured
child configurations. Parent checkpoint/replay manifests, nested approval/HITL
resume, lazy config/version binding, graph subagent teams, detached host task
stores and subagent update-event forwarding are not completed by this module.
Configured graph subagents currently fail explicitly rather than silently being
run as a single agent. This port must not be described as full SDK parity.
