# Unified Python WebUI and SQLite migration

> **Status: work in progress. Do not deploy this branch.** This is a migration
> plan and the first implementation slice. The complete LibreChat backend is
> **not** yet reproduced. Keep the existing Controller deployment unchanged.

## End state

- One `local-shell-mcp` service and public HTTP origin, with LSM identity,
  authorization, files, terminal, remote, GUI, tools and chat managed together.
- The **existing vendored LibreChat React UI and full behavior** are the UI
  contract. The discontinued LSM Hosted Chat is not an implementation base.
- The Python runtime implements the functionality currently provided by the
  vendored LibreChat Node backend, including all Agent streaming/continuation,
  tools, subagents, handoff, Ask User, models, memory, projects, chats, archives,
  attachments, and settings. No MongoDB, Meilisearch or Node process at runtime.
- SQLite is a single persistent database at `<state_dir>/lsm.sqlite3`, with WAL,
  structured data, FTS5 and transactional internal state. Audit, sessions,
  remote identities, jobs and other LSM state must end up in this database.
- Built React assets live inside the LSM Python package. Build-time JS tooling
  is excluded from Python Worker wheels and Controller runtime.
- Persisted assets stay under `.local-shell-mcp/`; short-lived OS temporary
  files are allowed. Do not create sibling files alongside the executable.

## Implementation slices

| Area | Status | Evidence / remaining contract |
| --- | --- | --- |
| SQLite schema, transactions, files-to-SQLite import | Partial | `sqlite_store.py`, unit tests; schema evolution and production data migration pending |
| Existing LSM StateStore to SQLite | Partial | `sqlite` is default; incremental legacy import works, but direct file-only consumers and tests need migration |
| SQLite OAuth secret | Implemented | Preserves legacy secret; tests for persistence and isolation |
| React auth/LSM single sign-on | Implemented and browser-verified | LSM PIN/OAuth ticket handoff, HttpOnly session, server-issued bearer; no extra LibreChat auth |
| Conversations, messages, projects | Partial | Python repository, HTTP routes and tests; full LibreChat variants/filters/uploads pending |
| Chat search | Partial | SQLite FTS5 trigram + short Chinese query fallback; Meilisearch parity pending |
| React SPA hosting | Implemented and browser-verified | First-party `ui/workspace` React build, deterministic compressed assets, safe Python extraction, real Chromium startup and chat tests |
| Provider endpoints and credentials | Partial | OpenAI-compatible, Anthropic and Gemini text streaming through lazy httpx, secret isolation verified; credentials configuration and usage accounting incomplete |
| Agent runtime + resumable event protocol | Partial and browser-verified | Python SQLite text generation, SSE delta/replay, idempotency, abort, startup-orphan recovery; tool callbacks/steering/approvals incomplete |
| MCP and native tool execution | Partial | The Agent derives its tool schemas directly from `tools.build_mcp()` and calls the original FastMCP tool manager, including existing Job/Shell/File/GUI/Browser behavior and Worker RPC. Per-machine `none/read/write` permissions are checked before execution (global → project → conversation). Nested MCP requires SQLite-backed human approval; multi-provider function calling and batch approvals remain pending. |
| Ask User, handoff and delegated subagents | Partial | SQLite-backed Ask User pause/answer/resume plus bounded owner-scoped delegated subagent and handoff flows with SQLite lifecycle records; multi-question batches, richer handoff context and complete UI parity remain pending |
| Prompt/context, memory, attachments and projects | Not started | Full conversation functionality and client compatibility |
| LSM Controller control routes | Implemented at routing level | Existing `/api/ui/*` handlers mounted directly under `/api/lsm/controller/*`, without Node proxy; remaining browser control flows require E2E parity |
| Remove duplicate Hosted Chat and legacy UI | Deferred | Delete only after full parity, without leaving an undocumented fallback implementation |
| Standalone Controller packaging + Worker compatibility | Partial | Compressed React bundle embedded by standalone binary CI, no Node runtime or browser dependency in Worker; full release matrix verification still needed |
| End-to-end UI tests and rollout | Partial | Reproducible Chromium-to-Python-to-SQLite streaming reply test passes; full Agent/browser/authorization parity, production migration and rollback pending |

## Data and API safety

- SQLite is the code default. Bootstrap imports durable old LSM state before
  OAuth initialization, leaves original files intact, and retries changed
  historical files without replacing authoritative SQLite writes. `file`
  remains an explicit rollback configuration; do not deploy until direct-file
  consumers and the full regression matrix are migrated.
- Old unpublished Hosted Chat profiles, conversations, encryption keys and
  archives are deliberately excluded from migration; the new React chat model
  starts clean. Existing LSM sessions, audits, jobs and worker credentials
  remain protected and must survive.
- `SQLiteStateStore` imports historical durable files transactionally and retains
  the originals until an operator verifies the migration. SQLite backup API is
  used for consistent snapshots, not an ordinary copy of the WAL file set.
- The Controller's frozen single-file executable defaults its workspace to
  the executable's directory and persists under the adjacent `.local-shell-mcp/`.
  Source deployments keep `/workspace` as their default. Explicit overrides
  continue to take priority.
- SQLite and its importer use Python's standard library. Optional FTS5/trigram
  absence degrades local search to regular SQL `LIKE`; imports of the new
  WebUI persistence layer are deferred until used. If SQLite itself cannot
  load, set `LOCAL_SHELL_MCP_STATE_BACKEND=file` to recover the Controller;
  do not edit or delete the database until a verified backup exists.
- Nested MCP discovery and execution use the original registered LSM
  `mcp_tool_search` / `mcp_tool_inspect` / `mcp_tool_call` schemas and FastMCP
  handlers. The conversation's `mcp` setting and OAuth scopes still gate them. The Agent sees only
  `mcp_tool_search`, `mcp_tool_inspect`, and `mcp_tool_call`; `mcp_manage` is
  never exposed to the model. External calls pause with a durable
  `tool_approval` action, and require an authenticated, generation-fenced
  `approve` decision and `shell:execute` scope before execution. A rejection
  continues the model without executing the tool. The first slice supports
  a single tool decision at a time; batch/edited/remembered approvals remain
  for later.
- For Agents configured with `ask_user`, the Python model loop can pause
  durably on a single question, persist the pending action and model history in
  SQLite, deliver `on_pending_action` to React, then resume the same generation
  after an owner-authenticated answer. The action ID is one-shot, and a stale
  or mismatched ID returns 409. Multistep human reviews and delegated Agent
  handoffs are separate remaining tasks.
- The Controller host itself is an ordinary machine named **`local`**.
  It is listed next to remote Workers and uses exactly the same machine-
  permission gate for Agent operations. Tool definitions are not separately
  copied into the WebUI: the Python Agent derives its exposed tools, their
  parameters and read-only annotations from LSM's existing `tools.build_mcp()`
  registry. The call path uses that registry's original FastMCP executor, with
  original validation, audit, preflight, timeout/watchdog rules and Worker routing. `local` is
  normalized to the original tools' local/`None` machine argument.
- A `read` grant permits existing observational tools such as `environment_get`,
  `job_list`, `job_get`, `job_tail`, `shell_list`, `shell_read`, `file_tree`,
  `file_glob`, `file_grep` and `file_read`. `write` additionally permits
  `job_start`, `job_stop`, `job_retry`, `shell_send`, `file_write`, `file_edit`,
  `file_patch`, `run_shell` and related mutating tools, subject to the
  existing OAuth scopes. Shell commands are conservatively write-capable even
  when their text appears to be observational. Cross-machine transfer checks
  both endpoints (source read, destination write). Administrative `mcp_manage`
  and `remote_manage` are not model tools. No separate LSM Job/Shell/File
  implementation is maintained by the WebUI.
- These machine grants apply only to Agent-initiated operations; they do not
  replace a human administrator's direct Controller authorization. Permissions
  are rechecked immediately before every native tool invocation and cannot
  elevate the user's frozen OAuth scopes.
- Agent machine permissions are **per machine**, with `none`, `read`, `write`
  levels. They inherit **global defaults → project defaults → conversation
  overrides** in the same SQLite database. An explicit `none` blocks inherited
  access, and unknown/new Worker machines start without permission. The legacy
  chat-level `lsm` Boolean is informational and **cannot** grant access.
- Each function call rechecks the effective policy before touching the machine.
  Read operations require `shell:read`; write operations additionally require
  `shell:write`; remote operations require `remote:use`, including OAuth expiry
  fencing. The `file_list`, `file_read` and bounded `file_write` tools support
  local and remote Workers, with workspace confinement and private-state file
  exclusions. Arbitrary shell or nested MCP management is not enabled by a
  machine grant alone; other tool categories await the human-approval runtime.
  Tool calls are audited without exposing content or secrets and recorded as
  resumable SQLite generation steps.
- The internal single-user WebUI is identified by the existing LSM OAuth
  principal, never by a browser-supplied user ID. All reads and mutations must
  verify the owner and relevant scopes. One-time login tickets are hashed,
  expire after 60 seconds and cannot be replayed.
- Original LibreChat routes, event formats and frontend hooks are the source of
  truth; do not substitute a simplistic chat-completions implementation for
  Agents, approvals, or continuation functionality.

## Local checks

```sh
python -m pytest -q tests/test_sqlite_store.py tests/test_webui_storage.py \
  tests/test_webui_routes.py tests/test_webui_auth.py tests/test_webui_frontend.py
python -m ruff check src/local_shell_mcp/sqlite_store.py src/local_shell_mcp/webui
```

The full native Python regression suite passed locally (2049 passed, 6 skipped
at commit `6b7cc04d`). A true Chromium streaming-chat test now also passes with
an in-process mocked provider, validating SSE and SQLite persistence. The
coverage gate remains below 95% in this draft, and LibreChat's advanced Agent
features and full browser workflows are **not** ready. Do not merge or switch
production until these blockers are resolved and the full CI matrix is green.
