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
| React auth/LSM single sign-on | Partial | One-use login ticket, HttpOnly session, LSM bearer in Python; real frontend integration pending |
| Conversations, messages, projects | Partial | Python repository, HTTP routes and tests; full LibreChat variants/filters/uploads pending |
| Chat search | Partial | SQLite FTS5 trigram + short Chinese query fallback; Meilisearch parity pending |
| React SPA hosting | Partial | Python static/safe SPA routing; vendor build and client compatibility pending |
| Provider endpoints and credentials | Not started | OpenAI/Anthropic/Google/other model configs, streaming, token accounting |
| Agent runtime + resumable event protocol | Not started | Exact `api/agents/chat` SSE contract, optimistic messages, checkpoint/recovery |
| MCP and native tool execution | Not started | LSM native/external tool toggles, tool permissions, approvals, auditing |
| Ask User, handoff and delegated subagents | Not started | Durable task graph, parent/child lifecycle, resume, cancel, event propagation |
| Prompt/context, memory, attachments and projects | Not started | Full conversation functionality and client compatibility |
| LSM Controller control routes | Partial | Existing `/api/ui/*`; must replace Node `/api/lsm/controller/*` proxy with direct Python handlers |
| Remove duplicate Hosted Chat and legacy UI | Deferred | Delete only after full parity, without leaving an undocumented fallback implementation |
| Standalone Controller packaging + Worker compatibility | Not started | Compiled React static files in executable, no Node runtime in Worker |
| End-to-end UI tests and rollout | Not started | Real browser flows, authorization, generation, migration and rollback |

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

The complete original test suite must pass in both file and SQLite modes before
switching production to `sqlite`. A passing subset does not establish readiness.
