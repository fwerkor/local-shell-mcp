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
| api/server/controllers/agents/steer.js; packages/api/src/agents/steering/request.ts | NOT COMPLETE | Durable steer/arm/cancel, preempt and cross-actor lifecycle still require source port |

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

## Validation

- Upstream Node-based ask-answer (91) and tool decision (60) differential cases.
- SQLite tests: owner-bound recovery, restart, stale epoch/action, concurrent
  duplicate retry, conflicting answer, expired/cancelled and rejected requests.
- Original React Chromium: Ask User and approval panels survive page reload,
  submit the original request, continue the same generation and render saved
  completed history after another reload. No React component rewritten.
- Coverage floors unchanged: total >=95%, every measured module >=90%.
  Final CI result must validate the combined process tests.

## Integration blockers for graph-runtime PR

The complete multi-agent StateGraph event actor, nested/parallel interrupt
collection, retained Ask User answers through compaction, steer/arm/cancel,
cross-process execution lease ownership and the complete upstream tool-hook
lifecycle remain unverified. This feature is PARTIAL rather than full
LibreChat parity until they have source-level and browser coverage.
