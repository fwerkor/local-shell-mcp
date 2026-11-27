# Goals, scheduled chats and long-running work

## Choose the right mechanism

| Mechanism | Purpose |
|---|---|
| Ordinary chat generation | Respond to the current prompt, including tool calls |
| Chat Goal | Continue an active logical-session plan across model turn boundaries |
| Scheduled chat | Start an Agent with a saved prompt on a recurring cadence |
| Persistent job or terminal | Run a command independently of a single model request |
| Subagent | Delegate a bounded task to another Agent thread |

A scheduled chat is not a persistent shell job. A Logical Session is not a conversation or an OS process. Cancelling one does not necessarily terminate everything started by its tools.

## Chat Goal

For a long task, ask the Agent to define a concrete objective and maintain a plan using the Logical Session tools. The plan records steps and their statuses. The chat runtime can continue an active plan at model turn boundaries without waiting for a new user prompt or the external MCP Live Workspace inactivity timer.

Inspect the plan and progress, and pause, resume or cancel using the available Goal controls. Continuation requires an active plan and an eligible run; it should not continue a completed, blocked or cancelled plan. Repeated identical replies without progress trigger a pause rather than an infinite loop (currently after three unchanged boundaries). Resolve the actual blocker before resuming.

Define completion criteria. For example: inspect a repository, implement a fix, run the relevant test suite and report any failures. Ask the Agent to record exact commit IDs and test results rather than declaring success solely from its own plan.

The external MCP client Goal mechanism is separate; see [Human interface](../guides/human-interface.md) for the Logical Session and Live Workspace handoff workflow.

## Create a scheduled chat

Open scheduled chat management. Create a schedule with a descriptive name, a saved Agent, prompt, timezone and cadence. Choose its conversation target, optionally select a project for a new conversation, save and enable the schedule. Use the manual run control to validate the configuration before depending on it.

Supported cadence includes hourly, daily, weekdays, weekly, five-field cron and continuous execution. Continuous execution starts subsequent occurrences after the configured delay; a zero delay can generate sustained provider and machine load. Ordinary recurring schedules enforce a minimum interval of five minutes. Use an explicit IANA timezone such as `Asia/Shanghai` or `UTC`; inspect the displayed next run after saving.

A cron example for 09:00 on weekdays:

```text
0 9 * * 1-5
```

This uses the selected timezone, not necessarily the Controller's system timezone. Check daylight-saving transitions if the chosen timezone observes them.

## Conversation targets

- **New chat:** start a separate conversation for each occurrence; useful for independent reports.
- **Reuse chat:** create a conversation on the first run and reuse it for subsequent occurrences; useful for cumulative monitoring.
- **Existing chat:** choose an existing conversation that will receive scheduled turns.

A reused or existing conversation can grow and require compaction. Choose independent chats when historical context is unnecessary. Scheduled runs depend on the selected Agent and model channel still existing and being usable.

## Unattended permissions

Scheduled execution is Controller-owned, with saved authorized scope names rather than a retained browser login token. Save or manually run a schedule to authorize it when required. The named Agent's machine permissions apply; ordinary project/chat machine overrides are not the schedule's machine policy. Controller restrictions, saved authorization, tool capabilities and tool approval remain relevant.

Use a read-only Agent for monitoring. Explicitly describe the allowed targets, desired output and actions to avoid. If a scheduled task needs human input or approval, inspect pending interactions; do not assume that unattended execution implies unrestricted access. A monitoring prompt example:

```text
Inspect the specified training job and its logs.
Report current step, loss, throughput, ETA and any new errors.
Do not modify files, restart the job or launch new work.
If the data is unavailable, report the exact reason.
```

## Lifecycle and recovery

The Controller persists schedules and run state and claims occurrences transactionally to avoid duplicate starts. A browser tab need not remain open. Do not assume missed occurrences are always replayed or that all external work survives a Controller restart. Check last run, next run, in-flight execution and the associated chat after downtime.

Disable a schedule to prevent future automatic occurrences. Inspect an already running occurrence separately; stopping future scheduling is not a guarantee of cancelling a live generation or shell job. Remove schedules no longer needed and revoke unneeded Agent permissions.

A tracked Job or terminal created by a WebUI Agent can survive normal model-response completion, and a Controller restart alone does not necessarily terminate it. Explicit abort, loss of machine permission or grant expiry can trigger cancellation of Agent-owned work. If the Worker is offline, cancellation may remain pending until it can be delivered. Inspect the job or terminal itself before declaring that execution has stopped. The Agent can only send to or stop its own conversation-owned jobs/shells through the guarded WebUI tool path. External MCP clients retain their native semantics.

For commands that should outlive an individual tool request, use LSM tracked jobs or persistent terminals. Save output to a log file, record job identifiers, and check real progress. See [Usage patterns](../guides/usage-patterns.md).
