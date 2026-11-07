# Unified web workspace

The **unified LSM web workspace** is the recommended way to use local-shell-mcp day to day. It combines AI chat, project history and the LSM control plane in one responsive interface, based on a modified, vendored LibreChat frontend. You can still connect external MCP clients such as [ChatGPT](chatgpt-connector.md) or [Gemini](gemini-spark.md).

The workspace is **self-hosted and optional to install**: it is a separate web service, not part of the minimal Controller image, standalone executable or remote Worker bundle. Controller-only deployments retain the original browser UI and OpenTUI.

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

1. [Install and start an LSM Controller](quickstart.md) with OAuth, an appropriately isolated workspace and persistent `file` or `redis` state storage. Install Docker Compose and clone the repository to the host running the web stack.
2. Provide **two HTTPS origins on the same site**, such as `https://lsm.example.org` for Controller and `https://chat.example.org` for the workspace. The chat service is not exposed directly on an untrusted network.
3. Generate one bridge secret with `openssl rand -hex 32`. Configure these environment variables on the **Controller service**, using that secret, then restart it:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. In the repository checkout, configure the optional web stack. Use a private environment file, or export the values shown below; generate unique strong secrets, and do not commit them:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Render the private config, then build and start the separately deployed chat stack:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

When using the root Docker Compose deployment, the Controller variables above belong in the root `.env` and are forwarded to the container. The chat service values can be provided through shell exports or a private environment file. The Controller container must be reachable from the chat container at `http://local-shell-mcp:8765` on the named Docker network. Reverse-proxy port `127.0.0.1:3080` to the chat HTTPS origin, preserve the external host, and follow the [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) in the repository. The web stack runs Node.js, MongoDB, Meilisearch and SearXNG; they are **not** included in Workers. This separate deployment is not started by a plain `docker compose up -d` in the repository root.

## Sign in and use chat

1. Open `https://lsm.example.org/ui`, authenticate using the **LSM Controller** login, and follow the one-time handoff into the web workspace. You do not create a second LibreChat user account.
2. Configure an available LLM provider or model endpoint for the chat service. The workspace supplies the chat interface and tool bridge; **it does not include a model or API credits**.
3. Create a conversation. Web search and LSM tools are enabled by default, subject to Controller permissions. Use the per-conversation **Web**, **LSM**, **External MCP** and **Memory** controls as needed.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Chat uploads (up to 32 MiB) are stored under the Controller workspace and their absolute paths are supplied to the model. Browser uploads do not grant additional file permissions. Model-facing tool calls pass through LSM authorization, audit and the remote-worker router.

## External MCP, security and data

Use the workspace MCP sidebar to manage nested external MCP servers. This supports local stdio servers and HTTP servers, including separate private environment variables and request headers. Secrets are not returned to the browser. The **External MCP** chat toggle allows search, inspection and invocation of nested tools; it does not grant the model `mcp_manage` when native LSM tools are disabled. UI management is protected by normal Controller authorization.

Chat messages, projects and archives are stored server-side in the web stack's MongoDB; search uses Meilisearch. The Controller separately owns tool permissions, Worker identities, session state and audit. Back up both data stores if you need to retain all history. The chat backend is single-user under LSM's login; do not expose its internal API or databases to the public.

The UI is a top-level app, **not an iframe**. If the optional chat service is not configured, `/ui` continues to serve the original LSM WebUI. Native OpenTUI and external clients remain supported.

## Troubleshooting

- **Redirect remains on the original UI:** check `LOCAL_SHELL_MCP_LIBRECHAT_URL`, a persistent Controller state backend and the web stack's HTTPS reverse proxy.
- **Login or handoff fails:** verify the exact same 32-byte-or-longer bridge secret on both sides, matching same-site origins, HTTPS and server clocks.
- **Chat loads but cannot answer:** set up an actual model endpoint or API credential and check chat container logs.
- **MCP tools are missing:** verify Controller scopes and per-conversation toggles; the nested server registry is separate from the LibreChat MCP database.
- **Files or sessions appear empty:** verify that chat reaches the correct Controller and workspace, and inspect its API authentication logs.

For implementation details and updates, see [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) and the [human interface guide](../guides/human-interface.md).
