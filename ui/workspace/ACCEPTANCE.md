# PR #343 architecture and acceptance audit

Status: **Draft; incomplete migration; do not deploy**. Audit date: 2026-11-08.
This report records source inspection and executable evidence, not a declaration
of complete LibreChat feature parity. See MIGRATION.md for the migration history.

## Native tool boundary

The Agent obtains schemas from `tools.build_mcp(agent_dispatch=True)` and invokes
its original FastMCP manager. There is no second File/Job/Shell/GUI/Worker executor.
The `logical_session_id` transport credential is removed from model schemas and
injected by the server; models cannot forge it. Original argument validation,
watchdogs, preflight, auditing, idempotency and Worker routing remain in place.
Names retain their original spelling, without an `lsm_` prefix.

Public MCP continues to enforce its bundled OAuth contract. Internal Agent
calls use a frozen authenticated principal and operation-specific scopes, plus
per-machine policy from SQLite. They never receive extra OAuth scopes.

Policy inherits global → project → conversation, separately for each named
machine. Explicit `none` overrides inheritance; an unknown Worker is denied.
`local` is an ordinary machine. Controller registration administration alone is
bound to local, irrespective of the managed Worker's permission. Machine
ACLs are checked again at dispatch, and source/destination checks also apply
to persisted transfer jobs retried through `job_retry`.

The following table covers every registered native tool. A registry-completeness
test fails if any new tool lacks classification. Unclassified tools are hidden
and execution is denied even if a future readOnlyHint is optimistic. All remote
machine accesses additionally require `remote:use`. Existing native execution
constraints can still reject a call after the Agent permission gate.

| Native tool | Authority/target | Machine grant | Additional OAuth boundary |
| --- | --- | --- | --- |
| `workspace_open` | Live Workspace app | Separate flow | App credential contract; excluded from Agent dispatch |
| `open_live_workspace` | Live Workspace app | Separate flow | App credential contract; excluded from Agent dispatch |
| `live_workspace_reconnect` | Live Workspace app | Separate flow | App credential contract; excluded from Agent dispatch |
| `environment_get` | Selected machine (default local) | read | shell:read |
| `skill_list` | local | read | shell:read |
| `skill_load` | local | read | shell:read |
| `skill_read` | local | read | shell:read |
| `run_shell` | Selected machine (default local) | write | shell:write + shell:execute |
| `run_python` | Selected machine (default local) | write | shell:write + shell:execute |
| `shell_start` | Selected machine (default local) | write | shell:write + shell:execute |
| `shell_send` | Selected machine (default local) | write | shell:write + shell:execute |
| `shell_read` | Selected machine (default local) | read | shell:read |
| `shell_stop` | Selected machine (default local) | write | shell:write + shell:execute |
| `shell_list` | Selected machine (default local) | read | shell:read |
| `job_start` | Selected machine (default local) | write | shell:write + shell:execute |
| `job_list` | Selected machine (default local) | read | shell:read |
| `job_get` | Selected machine (default local) | read | shell:read |
| `job_tail` | Selected machine (default local) | read | shell:read |
| `job_stop` | Selected machine (default local) | write | shell:write + shell:execute |
| `job_retry` | Selected machine (default local); persisted transfer endpoints rechecked | write | shell:write + shell:execute |
| `file_list` | Selected machine (default local) | read | shell:read |
| `file_tree` | Selected machine (default local) | read | shell:read |
| `file_glob` | Selected machine (default local) | read | shell:read |
| `file_grep` | Selected machine (default local) | read | shell:read |
| `file_read` | Selected machine (default local) | read | shell:read |
| `image_view` | Selected machine (default local) | read | shell:read |
| `gui_list` | Selected machine (default local) | read | shell:read + shell:execute |
| `gui_state` | Selected machine (default local) | read | shell:read + shell:execute |
| `gui_action` | Selected machine (default local) | write | shell:write + shell:execute + shell:execute |
| `link_create` | local | write | shell:write + file:share |
| `link_list` | local | read | shell:read + file:share |
| `link_revoke` | local | write | shell:write + file:share |
| `file_write` | Selected machine (default local) | write | shell:write |
| `file_edit` | Selected machine (default local) | write | shell:write |
| `file_delete` | Selected machine (default local) | write | shell:write |
| `file_patch` | Selected machine (default local) | write | shell:write |
| `remote_transfer` | Source and destination | source read; destination write | shell:write |
| `session_manage` | Agent logical state | No machine grant | Authenticated owner; unexpired grant |
| `secret_scan` | local | read | shell:read |
| `plan_manage` | Agent logical state | No machine grant | Authenticated owner; unexpired grant |
| `audit_tail` | local | read | shell:read |
| `mcp_manage` | Controller local | write | shell:write + shell:execute |
| `mcp_tool_search` | Nested MCP | Separate flow | Discovery: shell:read; call: shell:execute + human approval |
| `mcp_tool_inspect` | Nested MCP | Separate flow | Discovery: shell:read; call: shell:execute + human approval |
| `mcp_tool_call` | Nested MCP | Separate flow | Discovery: shell:read; call: shell:execute + human approval |
| `browser_session` | Selected machine (default local) | list: read; all other actions: write | shell:read or shell:write + browser:use |
| `browser_snapshot` | Selected machine (default local) | read | shell:read + browser:use |
| `browser_act` | Selected machine (default local) | write | shell:write + shell:execute + browser:use |
| `browser_run_script` | Selected machine (default local) | write | shell:write + shell:execute + browser:use |
| `remote_manage` | Controller local | write | shell:write + remote:use |

Agent-owned Ask User and configured child-agent delegation/handoff use their
separate owner-scoped runtime and do not acquire machine authority themselves.
A child agent's ability to perform tools is not yet equivalent to the full
LibreChat runtime.

### Permission evidence and remaining limits

Tests exercise actual registered file/session/plan calls, readonly job metadata
and tails, original Worker RPC forwarding, write rejection, OAuth expiry,
owner isolation, global/project/conversation inheritance, explicit revocation,
Controller management, both transfer endpoints, persisted transfer retries,
and browser session list vs start.

Revocation fences the **next dispatch** and resumed human actions. It does not
yet terminate a native long-running call or a previously launched background job
as soon as permissions change. This remains an acceptance blocker. Arbitrary
`run_shell` text always requires write and execution scopes, including `ls`.

## Capability audit

| Capability | Actual implementation / verification | Remaining acceptance work |
| --- | --- | --- |
| Python + SQLite single service | Native Python routes; React build embedded for Controller; no Node or Mongo service at runtime | Full distribution acceptance on current head |
| Providers | OpenAI-compatible, Anthropic, Gemini text SSE; native tool SSE adapters for all three | New Anthropic/Gemini adapters tested with mock HTTP/SSE; live vendor validation and advanced thinking/multimodal variants pending |
| Tool execution | Original MCP registry/executor; source tool step/completion fields; tool cards/results retained in history and verified after React reload | Full rich/non-text MCP results and complete event-actor lifecycle |
| Agents/subagents/handoff | Original optional subagent config/schema, isolated shared native child executor; original transfer tools switch the current Agent; owned Builder validation/references | Graph teams, parallel handoff recipients, background/child threads, full actor/progress/resume manifest parity |
| Ask User | Source-ported 1–4 question schema and ID-keyed answers; original React batch interaction verified | Full graph checkpoint/retained-answer/admin gating parity |
| Nested MCP | Existing registry discovery/config/execution; optional source endpoint approval policy; durable batch decisions and native edited/rejected execution | Full hook/eager policy layers, remembered review/context semantics and management UI walkthrough |
| Conversations/projects | CRUD, search, archive, fork, complete message graph, project aliases, active-branch model history | Comprehensive retained-client contract suite, search/prompt/preset/tag parity |
| Context | Active ancestry; owned SQLite node cursor/pending writes, sibling-result replay, completed-node restart tests | Full graph actor/orphan continuation, automatic/manual semantic compact and memories |
| Attachments | Controller private directory, real local path, owner metadata; streaming size/path checks | Full project/remote attachment lifecycle and deletion/download browser coverage |
| Native control pages | Reuse existing Python Files/Terminal/GUI/Remote/Settings/Audit handlers | End-to-end validation of each page, GUI permissions and mobile/dark-mode walkthrough |
| SQLite migration | Default backend; transactional incremental legacy import; original files retained; DB writes win over old files | Production-scale legacy snapshot, rollback rehearsal, oversized legacy entry policy |
| Retired code | `integrations/` has zero tracked files | Python legacy `hosted_chat*` and `librechat_integration.py` remain and are not yet eliminated |

## Verification checkpoints

- Incoming local `36efcb06`: full Python regression **2165 passed, 2 skipped**.
- Review/permission changes at `69ada869`: full regression **2179 passed, 2 skipped**.
- Native provider protocol and related targeted suites: **35 passed**.
- Original-source Ask User schema/resume differential + related suites: **20 passed**, including 91 Node reference vectors.
- Original React batch Ask User interaction in Chromium: **passed**.
- Restored retained React utility/Ask User test entry: **22 suites, 557 tests passed**.
- React production build and TypeScript check: passed before restored tests;
  source-aligned Zod/declaration/path build and type-check now pass with tests included.
- Native UI PTY smoke and browser smoke: passed after local dependency build.
- Shared-runtime local full gate: **2287 passed, 2 skipped**, **95.30% total**, all modules at least90%; HTTP/MCP/PTY/browser smoke passed.
- Original React Ask User plus native tool card/output/reload E2E: **2 passed** (native variant added after that full collection).
- CI at `f9480228` and `20830300` passed all platforms before these newer runtime changes.
- Current full regression, branch coverage gate, updated React/browser CI and
  release matrix: consult the current PR checks; previous green runs do not
  validate later source changes. Do not lower 95% total / 90% per-module gates.

## Merge decision

Not ready to merge. Keep Draft and production unchanged until the remaining
functional and validation gaps above are closed. In particular, passing unit
or build checks does not constitute complete LibreChat equivalence.

Source-port status and the exact upstream commits are authoritative in PORTING_MAP.md and UPSTREAM_LOCK.json.
