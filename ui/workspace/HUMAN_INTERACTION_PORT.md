# Human interaction port: source mapping and acceptance

Fixed upstream baseline: LibreChat e8f3be08623663d4ad7f7241e693c94469b63bb0,
npm @librechat/agents 4.0.1 (c4ffb9b1b78421bf63eba3e56993017f922387f3).

## Source to Python to React

| Upstream | Python | Scope |
| --- | --- | --- |
| packages/api/src/agents/hitl/askUserQuestionTool.ts; agents/src/hitl/askUserQuestions.ts | webui/ask_user_tools.py, agent_runner.py | Optional 1-4 questions, bounded IDs/answers, interrupts |
| packages/api/src/agents/hitl/policy.ts | webui/approval_runtime.py, agent_runner.py | Explicit allow/ask/deny precedence; default approval exemption for Ask User; approval payload and decisions |
| packages/api/src/agents/hitl/resume.ts; api/server/controllers/agents/resume.js | webui/tool_approval.py, generations.py, generation_routes.py | Validated answers/decisions, owner/epoch/Agent checks, one-shot SQLite claim, exact retry |
| packages/api/src/agents/checkpointer.ts; packages/api/src/stream/GenerationJobManager.ts | webui/checkpoints.py, generations.py, agent_runner.py, main.py | Shared checkpoint and event log; controller restart re-parks original interrupted action |
| client/src/hooks/SSE/useResumeOnLoad.ts; useResumableSSE.ts; client/src/components/Chat/Messages/Content/AskUserQuestions.tsx; ToolApproval.tsx; client/src/components/Chat/approval/Review.tsx | generation_routes.py:status,stream,resume; generations.py:resume_snapshot | Original React components unchanged; status.resumeState and SSE sync/pendingAction protocol |
| api/server/controllers/agents/steer.js; packages/api/src/agents/steering/{request,runtime}.ts; packages/api/src/stream/interfaces/IJobStore.ts | webui/steering.py, agent_runtime.py, agent_runner.py, generation_routes.py, generations.py | Owner/epoch-fenced durable FIFO queue, replay receipts, arm/cancel/leftover, provider-safe token-boundary preempt, PostToolBatch + terminal continuation, React SSE and status projections; not yet the entire upstream multi-actor lease protocol |

## Protocol and recovery

The existing POST /api/agents/chat/resume accepts actionId, conversationId,
generationCreatedAt, optional agent_id/model and answers or decisions. On success
the body status is resuming. Pending actions include the original stream/conversation/
run/response identity, payload, creation time and the source default 24h TTL.

BEGIN IMMEDIATE consumes a valid pending action and durably saves the exact
original pendingAction and submission as resumeClaim with history and partial text.
An approval also retains its complete approvedToolBatch. A same-owner retry with
identical action/answer can restart from this claim; a changed submission cannot.
The startup recovery step re-parks a crashed claimed action under requires_action
and re-emits the original on_pending_action before the normal orphan cleanup.
The browser must authenticate and resubmit; restart never directly grants execution.
Tool execution still calls the native registry and re-checks current OAuth scopes,
machine permissions and nested MCP access.

GET /api/agents/chat/status/{conversationId} returns resumeState with runSteps,
aggregatedContent, responseMessageId, userMessage and pendingAction. GET
/api/agents/chat/stream/{conversationId}?resume=true returns a sync frame
from a consistent SQLite event watermark, followed by newer events. It does not
create a new runtime.

Source-compatible explicit Ask User approval consists of two interrupts:
tool approval followed by the question itself; an explicit deny produces
a blocked tool result without showing the question. The old approval evidence
is retired when the second interrupt is persisted.

## Steering lifecycle

POST /api/agents/chat/steer and /steer/deliver accept bounded steer text,
validated owner-scoped file references, source-normalized quoted excerpts,
and optional preempt requests. The strict delivery route requires a
clientSteerId; ordinary steers may omit one. SQLite serializes admission,
client-idempotency receipts and the FIFO queue in the originating generation's
state, with the source 10-inflight-steer and 100-receipt bounds.
A receipt can replay even after a successor generation starts. Cancel can
remove a queued instruction or settle an old leftover; Arm upgrades an
existing FIFO item and increments preemptRevision without changing identity.

The model runtime probes the same durable queue at provider chunk boundaries;
an armed preempt closes the model stream before continuing with queued user
instructions. Post-tool-batch and terminal boundaries also inject the queue
without losing unarmed messages. The persisted steer parts are projected in
chronological SSE on_steer_applied events, status.resumeState.aggregatedContent
and final response content. Pending steers are projected in
resumeState.pendingSteers or recovered as terminal pendingSteers so React can
retain unsent follow-ups. Follow-on prompts replay the saved steer as a user
instruction rather than attributing it to the assistant.

## Validation

- Upstream Node-based ask-answer (91) and tool decision (60) differential cases.
- SQLite tests: owner-bound recovery, restart, stale epoch/action, concurrent
  duplicate retry, conflicting answer, expired/cancelled and rejected requests.
- Steer HTTP/SQLite/model tests: source guard ladder, quotes/attachment refs,
  queue/receipt bounds and expired receipt cleanup, duplicate replay across
  generations, atomic parallel enqueue, arm/cancel/terminal leftovers,
  strict delivery and safe stream preemption with real model re-entry.
- Nested single subagent Tool Approval: original agent checkpoints resume the
  same child and root call; tests also re-park a claimed child approval before
  resuming (crash/restart simulation).
- Original React Chromium: live preemptive Steer enters the provider,
  renders its inline receipt between old/new text at source runStep indices,
  and preserves that order after full page reload.
- Original React Chromium: Ask User and approval panels survive page reload,
  submit the original request, continue the same generation and render saved
  completed history after another reload. No React component rewritten.
- Coverage floors unchanged: total >=95%, every measured module >=90%.
  Final CI result must validate the combined process tests.

## Integration blockers for graph-runtime PR

The complete multi-agent StateGraph event actor and parallel interrupt
fan-in/fan-out, retained Ask User answers through semantic compaction,
cross-process generation lease ownership/fencing, media-native inline steer
attachments, and the complete upstream graph hook/event lifecycle remain
unverified. Source React's live applied-steer/reload behavior is verified;
abort/late-ACK/queued-chip and nested parallel graph steering still need
additional Chromium differential coverage. Current SQLite preemption
durably emits an applied steer before the next graph checkpoint commits; a
controller crash in that window cannot guarantee the original actor's
exactly-once model consumption. Generation recovery currently parks/interrupts
orphans rather than silently resuming their machine grants. These constraints
are documented rather than advertising full LibreChat runtime parity.

## Cross-PR integration acceptance (Draft Graph #354 + HITL #357)

A separate integration branch merges the exact independent Draft histories (without
mutating either source branch). It combines the graph scheduler with source HITL
approval precedence, durable resume-claim replay, original React status/SSE sync,
and the Steer HTTP FIFO. Foreground graph node model streams now consume Steer;
detached subagent graph nodes are not allowed to steal the root user queue.
The stable `on_injected` callback moves the original React message-creation
index after an applied Steer, including when a graph node is producing text.

Regression: `tests/test_webui_graph_steer_integration.py` exercises real
Python LangGraph and a preempted foreground graph node; its model observes the
user's new instruction before the stale old response can finish.
The initial combined full-suite run completed **2479 passed, 4 skipped** before
new graph-Steer regressions were added. The dedicated real LangGraph tests now
cover both a serial steer and concurrent fan-out where one SQLite receipt is
applied exactly once. The next Graph lease patch is carried into each compiled
child node; a real SQLite wakeup takeover test now proves that the old graph
actor is fenced before the next model call.

Unverified: deterministic Steer delivery across simultaneous fan-out siblings,
true cross-process root-generation actor ownership/lease fencing, full original
rich-media Steer encoding, exact-once provider/tool effects after a crash, and
full graph actor event-hook parity. The merged implementation must not be
advertised as exact full upstream parity without those tests and fixes.

Local complete suite after the Graph trigger retry update: **2490 passed,
5 skipped**. The additional graph actor lease-takeover regression was added
after that full run and separately passed with the serial/parallel steer tests.

## 2026-11-14 — foreground actor leases, crash repair and native Steer media

A separate source-compatible integration continuation on Draft PR #358 adds the
following controller-only paths; Worker still has no React, browser, LangGraph
or additional runtime dependency:

- `generation_actor_lease.py` and SQLite `generation_actor_leases` now provide
  fresh high-entropy lease tokens, transactional single-actor admission,
  20-second renewal, 120-second expiry, transactional event/final/Steer commit
  fencing, and per-token safe release. `AgentRunner`, its compiled StateGraph
  members and synchronous child agents inherit the parent lease; interrupted
  tool-only provider streams re-check the token before executing proposals.
- Startup recognizes foreign live Controller leases and does not terminate
  their runs. A crashed ordinary actor's checkpoint remains available in
  SQLite for **fresh authorized browser SSE/resume** reattachment, which
  resolves the Agent and machine grants anew; startup does not silently
  re-execute native tools using an expired OAuth token. Closed event-loop task
  handles are pruned before a new Controller loop can schedule/reap tasks.
- Source `steering/runtime.ts:drainAndBuildInjections` applies an event before
  asynchronous media encoding. SQLite similarly commits the applied receipt
  and SSE atomically. `SteeringStore.applied_parts` plus deterministic
  `steer:<steerId>` message IDs re-inject only uncheckpointed applied parts
  during an authenticated recovery, not on an ordinary parallel graph run.
  The same SQLite drain transaction privately stores the elected graph node
  namespace for each claimed steer; only that node can consume its recovery
  message if sibling nodes race after a crash. The public SSE part excludes
  the node namespace, retaining the original React contract.
- `steer_media.py` resolves every media file from its **owner-scoped SQLite**
  ID at the injection boundary; only legitimate attachments under the private
  state directory are read. Image formats (JPEG/PNG/GIF/WebP), PDF and bounded
  UTF-8 file context can be assembled into native OpenAI-compatible,
  Anthropic and Gemini request formats; malformed/oversized/revoked files
  degrade to text without discarding the user instruction. File bytes are
  never included in source React SSE events, persisted chat parts or graph
  checkpoints. `provider_multimodal.py` encodes model-turn content transiently
  and preserves plain-string Anthropic compatibility.
- The original unmodified React Chromium client is tested against a real
  Python LangGraph graph in both a direct serial edge and parallel fan-out:
  its child Agent asks a question, the page reloads, the exact pending action
  resumes after a valid answer, and the conversation remains coherent after
  a second reload. The completed parallel sibling is not re-executed by
  the resumed graph scheduler. Standalone Python Graph tests also verify
  this checkpointed sibling result at the model-call level. A second real
  Python parallel StateGraph test checks a tool approval/rejection interrupt:
  rejected tool actions cannot run, the question/approval branch continues,
  and its completed sibling never executes again.

Validation: real two-Controller SQLite claim races, stale-token model/event/
final-result refusal, expired-lease takeover, no-checkpoint orphan behavior,
no-checkpoint applied Steer replay, document/image owner authorization,
transient historical media replay and native provider wire payloads. Malformed
provider-specific media metadata is bounded/ignored rather than executed or
sent onward to an untrusted media URL.
The full source-oracle coverage suite completed **2514 passed, 5 skipped**;
HTTP, MCP, actual native PTY and original React browser smoke checks also
passed. An additional **123 focused tests passed**, including local Graph
fan-out Ask User, Tool Approval, Steer recovery, Provider multimodal wire
formats, actor claims and native registry guard paths. Combined branch coverage
passes unchanged quality gates: **95.35% total, every module >=90%**
(`agent_runner.py` 96.6%, `steering.py` 94.2%, `provider_multimodal.py`
98.2%, `steer_media.py` 98%+, `generation_actor_lease.py` 98%+). The frozen
GitHub cross-platform CI must finish before the Draft can be marked ready.

Not claimed: the source's complete arbitrary Agent Trigger system, every
LangGraph event hook and callback payload, rich audio/video attachment
transcoding, or an exactly-once guarantee for *external irreversible native
side effects* across a crash. An old actor may have completed an external
operation before losing its lease; native tool replay still depends on the
underlying LSM idempotency/ownership contract. These are separate from the
once-only persisted Steer receipt and replay-safe graph checkpoint claims.

## 2026-11-14 — transactional checkpoint and HITL lease fencing

After merging the then-current `main` (`992c3c74`) into the isolated stacked
branch, the Provider's new model-level `top_p` sampling contract coexists with
source preemptive Steer stream control. Ordinary and parallel Graph actor
ownership is now verified **inside the same `BEGIN IMMEDIATE` transaction** as
SQLite agent checkpoint writes, checkpoint pending tool/interrupt writes,
human Ask User or Tool Approval pause, approval proof retirement, as well as
original generation SSE/final state and Steer FIFO commits. The sibling
LangGraph saver inherits the exact parent actor lease. An old Controller whose
lease expired cannot publish an old graph checkpoint or pending action even
when the token was valid before the transaction started. Regressions include
a full two-Controller takeover between checkpoint creation and subsequent
writes, stale tool-step refusal, and a successful fresh lease writing the same
owned checkpoint. Original local and graph-only savers without an active HTTP
actor keep their existing separate owner-bound semantics.
