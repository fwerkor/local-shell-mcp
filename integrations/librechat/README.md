# Local Shell MCP unified WebUI (vendored LibreChat)

This is LSM's **primary self-hosted browser workspace**. The user-facing [unified web workspace guide](../../docs/getting-started/web-workspace.md) covers installation, sign-in, chat, Controller pages and troubleshooting. This file documents the implementation and deployment boundaries.

The **main LSM workspace** uses a directly vendored, modified LibreChat v0.8.8
frontend and backend at [`app/`](./app/). LSM Controller pages are React routes
within the same LibreChat shell, sidebar, navigation and theme. The LSM logo
and favicon are used for the workspace. The previous LSM WebUI is retained
only for authentication/fallback and for Controller deployments without chat.

**No clone of LibreChat is required or performed by build, test or startup.**
`compose.yaml` builds exclusively from `./app`; all vendor changes are ordinary,
reviewable source files. Installing third-party package dependencies still
requires access to the configured package registries unless cached or mirrored.

## Source and licensing

The initial upstream base is LibreChat **v0.8.8**, commit
`e8f3be08623663d4ad7f7241e693c94469b63bb0`. Source and attribution are
retained in `app/LICENSE` and `app/`. See [VENDORED.md](./VENDORED.md)
for upgrade expectations. There are **no submodules, online prepare scripts or
runtime patch-appliers**.

The entire application source is intentionally version-controlled in this PR.
Dependency directories, generated assets, credentials and backend databases
are excluded. This does **not** make the optional chat runtime part of LSM's
standalone Python/binary or minimal Docker Controller image.

## Architecture

| Concern | Owner |
| --- | --- |
| Single-user LSM login, original permission scopes, tools, workers, audit | LSM Controller |
| Unified navigation, chat UI and Controller React pages | Vendored LibreChat app |
| Chat, messages, projects, archives, settings | LibreChat MongoDB (server-side) |
| Chat and project search | Meilisearch |
| Web search | LibreChat with SearXNG |
| LSM native and external MCP tool execution | LSM Controller and its nested MCP gateway |
| LibreChat MCP management sidebar | LSM Controller nested MCP registry (not LibreChat's MCP DB) |
| Controller metrics, file/terminal/GUI/remote/session operations | Existing LSM Controller APIs |
| Chat attachment storage | Controller local workspace |

**Single-user boundary:** LSM owns authentication and the chat backend has one fixed
internal workspace account (`workspace@local-shell-mcp.invalid`). Independent
LibreChat registration, passwords, password reset, third-party sign-in, 2FA,
admin and account-deletion flows are disabled or removed from navigation.
The backend retains a lightweight private JWT session and the MongoDB user
foreign key required by LibreChat's chat/project data model; these are not a
second user-management system. Chat refresh checks the current LSM grant
through the private Controller API and refuses expired grants.

**Controller routes:** `/control/overview`, `/control/files`,
`/control/terminals`, `/control/desktop`, `/control/sessions`,
`/control/remotes`, `/control/audit`. The workspace homepage is
`/control/overview`; chat remains at `/c/new`. Mobile and desktop share
LibreChat's responsive navigation and light/dark theme tokens.

The LSM WebUI's ordinary `/ui` URL performs an authenticated handoff to
the **top-level LibreChat workspace** when the Controller advertises LibreChat.
A short-lived, one-use signed ticket authenticates the user to the chat backend
via a top-level POST; there is **no iframe wrapper** or cross-frame upload path.
Configure the chat and Controller HTTPS origins on the **same site**.
The original LSM WebUI is retained for Controller deployments without chat.

## Authentication and API boundary

LibreChat's backend exposes `/api/lsm/controller/*`. It validates the
LibreChat JWT session, accepts **only mapped LSM users**, allowlists supported
Controller operations and forwards them via its private Docker network.
The bridge carries an administrator-managed secret and the fixed internal
LibreChat account ID; the LSM Controller reconstructs the active single-user
LSM identity and authorization scopes **for every request**, enforcing its
existing per-operation checks. Anonymous web requests and arbitrary forwarded
headers cannot impersonate an LSM user. Controller credentials are never sent
to the browser or stored in LibreChat user profiles. Server-side requests
do not follow redirects.

Read operations and mutating operations use the same Controller API and audit
hooks as the original WebUI. Requests for shell execution, remote access or
file modification still require their original scopes. The terminal and GUI
components do not bypass these authorization checks.

Per-conversation **web / LSM native tools / external MCP / memory** toggles
are stored in LibreChat's MongoDB. LSM native and external MCP permissions
are independent: with LSM disabled but external MCP enabled, the model only
receives `mcp_tool_search`, `mcp_tool_inspect` and `mcp_tool_call` through
LSM's MCP gateway. It never receives `mcp_manage` in that mode. The Controller
enforces this allowlist again for every MCP `tools/call`, including JSON-RPC
batches, so saved Agents and wildcard tool selections cannot bypass it. A chat attachment is an authenticated, streaming,
size-limited upload (maximum 32 MiB) to:

```text
<LSM_WORKSPACE_ROOT>/.lsm-chat-uploads/<owner hash>/<UUID>-<filename>
```

Its absolute path is inserted into the composer for inspection through
the LSM tools. Uploading does not grant new read or tool permissions.

LibreChat's original file-search, code runner and skill marketplace are
disabled. Its MCP **sidebar** now manages LSM's *nested* MCP registry through
the authenticated Controller `/api/ui/nested-mcp` endpoint. It can register,
edit connection settings without losing existing private credentials,
enable/disable, refresh or remove stdio/HTTP servers, and set/unset their
private environment variables and headers. No additional MCP servers are
persisted in LibreChat's own MCP database. Controller-scope validation and
secret redaction remain active. The only LibreChat-side MCP connection is
the LSM parent, so nested tools stay behind `mcp_tool_*`. Web search and
LSM/external MCP tools are enabled by default; Ask User, delegated agents
and handoff are retained.

## Configuration

Set on the **LSM Controller**, not in a browser:

- `LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org`
- `LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=<32+ byte random secret>`
- A persistent `file` or `redis` state backend; `memory` is not supported.

Set for the **optional LibreChat Compose stack** (use secret storage, never
commit an `.env`):

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET=... # same as Controller secret
export JWT_SECRET=...
export JWT_REFRESH_SECRET=...
export CREDS_KEY=...      # 64 hexadecimal characters
export CREDS_IV=...       # 32 hexadecimal characters
export MEILI_MASTER_KEY=...
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

The Docker network must contain the private Controller service
`http://local-shell-mcp:8765`. Neither the Controller's internal MCP
port nor the LibreChat API and database containers should be made
public. The example Compose stack only binds chat to
`127.0.0.1:3080` and requires an external HTTPS reverse proxy.

Build and launch directly from the **checked-in** source:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

The generated `librechat.runtime.yaml` contains the bridge secret,
is mode 0600 and is gitignored; regenerate it after secret rotation.
The proxy must send the external HTTPS host correctly and allow the
Controller origin as a **narrow** CSP frame ancestor. Internal names
are restricted by the config renderer; never disable DNS rebinding
protection to make the integration work.

## Validation and rollout

Relevant automated checks cover LSM identity and expiry, Controller
API authorization, chat permissions, local attachments, the API proxy
allowlist and the vendored source layout. The vendored client and
server must also pass build and HTTPS browser smoke checks before
production rollout.

The vendored source excludes upstream developer automation, e2e suites,
example deployment material and most unrelated upstream tests; source size
was reduced from approximately 78 MiB to about 42 MiB. The chat Docker image
uses a separate runtime stage without the build-time Python/uv tooling.

The optional chat stack requires MongoDB, Meilisearch and SearXNG.
The Controller's standalone binary and light Docker packaging do not
include those services, or a second full development environment.
Production deployment and data migrations are deliberate operations;
this source change alone does not deploy to production.
