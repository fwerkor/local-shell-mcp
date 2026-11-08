# Unified web workspace

The **unified LSM web workspace** is the recommended way to use local-shell-mcp day to day. It combines AI chat, project history and the LSM control plane in one responsive interface, based on a modified, vendored LibreChat frontend. You can still connect external MCP clients such as [ChatGPT](chatgpt-connector.md) or [Gemini](gemini-spark.md).

The workspace is included with the single LSM Controller, not deployed as a separate service. Python and SQLite own all server data.

## What is in the workspace?

| Area | What you can do |
|---|---|
| Chat and projects | Choose a configured model, create conversations, organize projects, find past chats and archive conversations. History remains on the server. |
| Controller overview | View health, recent activity and connected machines. |
| Files | Browse and manage local or remote files. |
| Terminals | Work with persistent terminals on the Controller or Workers. |
| Desktop | Inspect and control remote GUI sessions. |
| Sessions | Inspect durable LSM tasks and their lifecycle. |
| Remotes | Connect and administer outbound Workers. |
| Audit | Inspect model-originated tool activity. |
| Nested MCP | Register, edit, enable, disable, refresh and remove external MCP servers behind LSM. |

The Controller routes are `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` and `/control/audit`. Chat opens at `/c/new`. The LSM MCP manager controls **LSM's nested MCP registry**; it does not create a second registry in LibreChat.

## Deploy the optional chat stack

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Sign in and use chat

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Chat uploads (up to 32 MiB) are stored under the Controller workspace and their absolute paths are supplied to the model. Browser uploads do not grant additional file permissions. Model-facing tool calls pass through LSM authorization, audit and the remote-worker router.

## External MCP, security and data

Use the workspace MCP sidebar to manage nested external MCP servers. This supports local stdio servers and HTTP servers, including separate private environment variables and request headers. Secrets are not returned to the browser. The **External MCP** chat toggle allows search, inspection and invocation of nested tools; it does not grant the model `mcp_manage` when native LSM tools are disabled. UI management is protected by normal Controller authorization.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Troubleshooting

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

For implementation details and updates, see [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) and the [human interface guide](../guides/human-interface.md).
