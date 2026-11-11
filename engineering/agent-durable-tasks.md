# Agent-owned durable Job and Shell tasks

The Python + SQLite WebUI records **native** Job/Shell task ownership before dispatching creation. The original LSM executors, shell backends, timeout policy, audit events, Worker RPCs and public MCP clients remain authoritative; no parallel task runner is introduced.

## Machine authorization

The WebUI resolves explicit grants by **global → project → conversation**, with each more-specific named machine value overriding the previous value. Unlisted machines are denied. The Controller (`local`) and Workers are peers with the same `none` / `read` / `write` levels. `read` does not allow commands or task mutation, including commands that look read-only.

| Native tool class | Required machine level | Additional restrictions |
| --- | --- | --- |
| `environment_get`, `skill_*`, `shell_read`, `shell_list`, `job_list`, `job_get`, `job_tail`, `file_list`, `file_tree`, `file_glob`, `file_grep`, `file_read`, `image_view`, `gui_list`, `gui_state`, `link_list`, `secret_scan`, `audit_tail`, `browser_snapshot` | `read` on selected machine | Native scopes still apply (e.g. `file:share`, `browser:use`). |
| `file_write`, `file_edit`, `file_delete`, `file_patch`, `link_create`, `link_revoke`, `browser_session` mutations | `write` | Native scopes and approval/validation still apply. |
| `run_shell`, `run_python`, `shell_start`, `shell_send`, `shell_stop`, `job_start`, `job_stop`, `job_retry`, `browser_act`, `browser_run_script`, `gui_action` | `write` | Execution still requires `shell:execute` and any native tool-specific scopes. |
| `remote_transfer` | Source `read`, destination `write` | Both endpoints checked; tracked as one Controller-managed job. |
| `mcp_manage`, `remote_manage` | Controller `local=write` only | Their existing management scopes apply; a target Worker does not need `write`. |
| `session_manage`, `plan_manage` | None | Authentication, logical-session ownership and native operation constraints still apply. |

Tool availability in the model schema does not confer runtime authorization. **Every native invocation is rechecked**, including expiry and policy changes. The `run_shell` and `run_python` commands require `write` regardless of command text or `persist_on_timeout`.

## Persistence and cancellation

The SQLite `agent_durable_tasks` table, in `.local-shell-mcp/lsm.sqlite3`, records the owner, conversation, run, tool-call identity, required machines/levels, OAuth scopes and grant expiry, hashed request identity, original native idempotency key, real returned Job/Shell ID, state, and retry schedule. An intent is committed **before** calling the native executor. The WebUI Agent rejects caller-supplied native idempotency keys instead of replacing them: otherwise a concurrent or existing public MCP call could own the same key. The Controller generates a high-entropy key and reuses the persisted value on replay. Public MCP clients retain their original explicit-key support. The native execution ID is bound from structured native results, never fabricated from the command or name.

`agent_run_cancellations` durably marks a generation as aborted before cancelling its coroutine. Affected tasks switch to `cancel_pending`. Revoking a machine grant, moving or deleting a conversation/project, or passing the original authentication expiry also schedules cancellation. A Controller reconciliation loop checks stored grants and uses native `job_stop`/`shell_kill`, retaining pending cancellations when a Worker is offline or delivery fails. A Controller restart marking a generation `interrupted` does **not** stop its already-started background jobs; those jobs survive until an explicit abort, permission loss, grant expiry or an authorized native stop. Reconnection/restart repeats the same stop operation; no creation is retried to infer an unknown ID. Native read-only idempotency inspection can recover a lost creation response, including when the intent was committed but the Controller restarted before receiving the result.

For `job_retry`, both the original ownership and current write authorization are required. Controller-managed transfer retries also revalidate persisted source/destination ACLs. A retry retains the native job's real ID and is tracked separately from the initial creation lease. Stop/send operations from a WebUI Agent are restricted to jobs and shells owned by that conversation; this rule does not change public MCP tooling.

## Crash and compatibility notes

- There can be a persisted reservation without a native ID if a crash occurs before or during creation. Only a **positive native idempotency lookup** permits cancellation. An inconclusive lookup leaves `cancel_pending` for later investigation or reconciliation; it never stops other tasks based on names or partial IDs.
- Newly upgraded Workers support `job_lookup_idempotency` and `shell_lookup_idempotency` as **read-only, internal RPCs**. Existing Workers continue to serve legacy tools; missing lookup support leaves an unknown-ID cancellation pending rather than risking a foreign task. Upgrade Workers for full lost-response recovery.
- This mechanism is limited to Python WebUI Agent-created durable Job/Shell operations. Regular public MCP clients and their pre-existing jobs retain their original behavior and are not retroactively claimed.
- The recovery loop is in the Controller. Worker bundles remain lightweight Python packages and do not require React, Node, MongoDB or the WebUI service.
- A durable task need not stop when its creating model response completes normally. Explicit abort, permission loss and expiry are distinct from normal generation completion.
