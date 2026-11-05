# LibreChat as the LSM Chat subsystem (experimental)

This integration embeds a **pinned, patched LibreChat v0.8.8** instead of extending
the handwritten Hosted Chat UI. The old implementation remains a fallback until
a full deployment and auth/tool end-to-end acceptance test is completed.

## Ownership and capabilities

| Subsystem | Owner |
| --- | --- |
| Login, authenticated subject, original OAuth scopes | LSM Controller |
| LSM tool execution, nested MCP gateway, worker permissions, audit | LSM |
| Conversation/project/message/archive storage | LibreChat MongoDB on the server |
| Search index | server-side Meilisearch |
| Model profiles, model-specific reasoning, human-in-the-loop Ask User | LibreChat |
| Subagents and agent handoff | LibreChat Agent Runtime |
| Web search and page retrieval | LibreChat web tool using SearXNG |
| Chat attachments | LSM Controller's **local** workspace, path in composer |
| Per-conversation web/LSM/memory toggles | LibreChat MongoDB; LSM MCP tool veto replicated in LSM server state |

There is exactly one configured external MCP server, **LSM**. It points to the
Controller's existing nested MCP service, without exposing LibreChat's MCP
server editor/marketplace. This configuration disables the separate code
runner, file-search chat tool, Skills and Artifacts capabilities; it preserves
the native **Ask User**, **subagents**, and **handoff** facilities.

**Permission invariant:** LSM tools ON implies web search ON. Either can be
turned off; web search may stay ON with LSM tools OFF. Memory can independently
be turned off; the agent request stops loading/injecting long-term memories and
gates its inline memory write/delete tools. Ordinary chat transcript remains
available.

## Prepare the pinned upstream

From the repository root:

```sh
python3 integrations/librechat/prepare.py
```

This clones the exact upstream commit
`e8f3be08623663d4ad7f7241e693c94469b63bb0` into the gitignored
`integrations/librechat/upstream-src` and applies only the reviewed patches.
It also generates a private random SearXNG secret (file mode 0600). Re-running
`prepare.py` verifies the commit and is idempotent.

The integration patch set is intentionally separate from LibreChat's source.
When updating LibreChat, explicitly re-pin, rebase the patches, and rerun
the UI, authentication and tool-policy tests.

## Deployment requirements

LSM retains its existing UI login. Configure these values in the **LSM
Controller environment** (not in the user's local browser):

- `LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org` — public LibreChat
  origin, with HTTPS and the same *site* as the Controller (avoid browsers
  blocking third-party cookies inside the iframe).
- `LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=<random 32+ byte secret>` — shared
  with the chat service as `LSM_LIBRECHAT_BRIDGE_SECRET`.
- Persistent LSM state backend: `file` or `redis`; never `memory`.

Set these values for the optional Chat Compose stack (use an encrypted secrets
store; do not commit its `.env`):

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET=... # exactly the Controller bridge secret
export JWT_SECRET=...
export JWT_REFRESH_SECRET=...
export CREDS_KEY=...
export CREDS_IV=...
export MEILI_MASTER_KEY=...
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

`LSM_DOCKER_NETWORK` is the existing network containing the LSM
`local-shell-mcp` service, reachable as
`http://local-shell-mcp:8765`. Do not expose the controller's internal MCP
port publicly or substitute an untrusted network for the private Docker
network.

Once secrets, DNS, HTTPS and the existing Docker network are available,
deploy with:

```sh
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

The example Compose file intentionally does **not** set up HTTPS/TLS or LSM
production credentials. Place LibreChat behind the existing HTTPS proxy, with
`X_FRAME_OPTIONS=off` and a narrow `CSP_FRAME_ANCESTORS` allowlist containing
only the Controller origin. The API and DB containers must remain private.

Opening **Chat** in LSM WebUI first authenticates against LSM, exchanges a
short-lived signed ticket (never placed in a URL) for LibreChat's session,
then embeds the LibreChat client. A conversation's LSM MCP tools run under
a mapped, expiring LSM principal; disabled LSM tools are rejected again at
the Controller's `tools/call` boundary.

## Uploaded files

The native LibreChat chat composer uses **Attach to LSM** rather than the
separate LibreChat file uploader. Each file is written by an authenticated,
size-limited streaming upload to:

```text
<LSM_WORKSPACE_ROOT>/.lsm-chat-uploads/<owner hash>/<UUID>-<original filename>
```

The absolute path is inserted into the current composer, where an LSM tool
can inspect it. A file upload does *not* grant any additional tool permission:
if the conversation disables LSM tools, the model cannot read the file through
them. Files are on the Controller's **local machine/container**, not on the
mobile browser, the remote worker, or the LibreChat image layer. Files need
normal LSM workspace backup/retention policy.

## Validation and rollout boundaries

Local checks cover ticket signing, stable user mappings, authorization scopes,
local upload integrity, forbidden unauthorized service calls, per-conversation
tool denial, WebUI TypeScript and a patched LibreChat frontend build.

**Not yet production-validated:** true multi-container login and refresh-cookie
flow, end-to-end LSM MCP handshake inside a LibreChat agent turn, OAuth
revocation/timeout UX, network-search provider reachability, project memory
isolation and database migrations. No production deployment or automatic
removal of the old Hosted Chat is performed by this patch. Integration remains
explicitly **opt-in** until these acceptance tests pass.
