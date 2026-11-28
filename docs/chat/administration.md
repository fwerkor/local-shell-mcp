# Administration and troubleshooting

## Deployment architecture

The WebUI frontend is served from the Python Controller at the same origin as its REST and MCP endpoints. The default state backend is SQLite. Released binaries and wheels include compiled frontend assets; building from source requires the JavaScript build toolchain, not running an installed Controller. Node.js, MongoDB, Meilisearch and a separately deployed LibreChat backend are not required.

Use the [Quickstart](../getting-started/quickstart.md) and [Configuration reference](../reference/configuration.md). For source builds, consult the [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Secure a deployment

Use a trusted HTTPS reverse proxy or tunnel, authentication and strong secrets. Keep the Controller inside an appropriate container or VM boundary. Limit incoming access and protect outbound credentials. Do not expose an unauthenticated execution endpoint on the public Internet.

A proxy must support streaming responses without buffering them until completion, and support WebSocket upgrades for interfaces that require them. Use suitable read/idle timeouts for long model and tool requests and allow intended upload sizes. Keep the configured public URL consistent with the browser origin and OAuth callbacks. Do not fix TLS failures by globally disabling certificate checks.

Model requests originate on the Controller, and model-visible messages, attachments and tool results may be sent to the selected upstream API. Assess provider data-handling terms before using confidential content. Protect external MCP secrets and Worker invite tokens too.

## State, backup and upgrade

The default state directory is `.local-shell-mcp` under the configured workspace; `LOCAL_SHELL_MCP_STATE_DIR` can change it. The shared database is `lsm.sqlite3`. Chats, projects, settings, Agents, memory, schedules and execution state are stored on the server; attachments, workspace files and other artifacts may be outside the database.

Back up the complete state directory, configured state outside it, deployment environment/secrets and relevant workspace files. Treat backups as sensitive. A database-only backup may omit attachments or configuration. Use a quiescent Controller or a consistent SQLite backup mechanism; copying only a live SQLite main database file can omit committed WAL content. Verify backups by restoring to an isolated test deployment.

Before an upgrade, record the current version, runtime path, configuration, state location and active jobs. Stop or safely drain relevant execution, take a consistent backup, upgrade the same installation and verify authentication, chat history, model generation, streaming, Workers and scheduled tasks. SQLite migration from older state is supported on startup; preserve legacy files until you have verified the migration. Do not replace a production data directory with an empty test one.

Rollback is not simply changing the binary if a database migration has changed persisted state. Restore compatible state when needed, and avoid running two independently configured Controllers on the same live storage.

## Diagnose a failed chat

| Symptom | Check first |
|---|---|
| Cannot load UI | Controller process, frontend bundle, correct URL, proxy and authentication |
| Model missing | Channel configuration, model discovery, model ID, account authorization |
| HTTP 401/403 from provider | API key/account, provider permissions, selected channel and protocol |
| HTTP 429 | Upstream rate/quota limits, concurrent requests, account/plan status |
| HTTP 400/413/422 | Request compatibility, input/context size, attachment limits, model parameters |
| HTTP 5xx or timeout | Provider health, network, model serving capacity, proxy timeouts |
| Output stops streaming | Reconnect/reload; inspect generation status and detailed error |
| Tool unavailable | Feature toggle, Agent capabilities, machine ACL, OAuth scopes, Controller switches |
| Worker offline | Worker registration, outbound connection, heartbeat and Controller logs |
| Pending approval/question | Open the conversation and inspect the requested action |
| Schedule does not run | Enabled state, timezone, Agent/channel, target, saved authorization, last run |

Do not assume all HTTP errors come from the same service: distinguish an LSM login failure, an upstream model API error, an external MCP error and a Worker transport error. Check detailed errors and relevant Controller logs; redact keys, bearer tokens and callback URLs before sharing them.

## Provider retries and recovery

Transient connection errors and selected HTTP errors (408, 429, 500, 502, 503, 504) can be retried with bounded backoff before a model response begins. The current ordinary retry delays are 1, 2, 4, 8, 16, 30, 30 and 30 seconds (eight retries after the initial request). HTTP Retry-After can extend a delay up to 120 seconds; certain stream errors add jitter. The retry budget applies to an individual model request, rather than being a lifetime count for the conversation. Compaction has its own recovery path. A rate limit caused by exhausted credits may remain until the provider replenishes quota. Automatic retry does not guarantee eventual success and does not make a subscription unlimited.

A mid-stream interruption differs from an error before the first response event. Do not rely on automatic replay of a partially executed tool sequence. Inspect saved history and external state before retrying. If the run is still active, reconnect rather than starting duplicate work. If it ended in failure, use the chat recovery/retry controls as appropriate, or start a new chat with an explicit handoff if the original cannot continue.

Context-compaction failures should be investigated separately from ordinary model generation errors. Verify the effective context limit, model compatibility, oversized tool results and available quota. See [Memory and context](context.md).

## What to include in a bug report

Report the LSM version/commit, installation method, OS, model protocol, sanitized endpoint type, model ID, approximate time, reproduction steps, relevant chat/run status and sanitized detailed error. For a remote issue, add Worker version, machine name and heartbeat/poll status. Include a small reproduction when possible; never send API keys, OAuth tokens, private prompts or unnecessary personal data.
