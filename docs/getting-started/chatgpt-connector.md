# ChatGPT connector

This page covers ChatGPT as a client connection. It does not choose the runtime. Before using this page, run the server with Docker, the VS Code extension, a binary, or a Python install.

`local-shell-mcp` is designed for ChatGPT Developer Mode and full MCP clients. It also exposes read-only connector-style `search` and `fetch` tools for connector discovery.

## Runtime prerequisites

Pick and start one runtime first:

| Runtime | Page |
|---|---|
| Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| VS Code extension | [VS Code extension runtime](../installation/vscode-extension.md) |
| Standalone binary | [Standalone binary runtime](../installation/binary.md) |
| Python / pipx / source | [Python runtimes](../installation/python.md) |

Then expose that runtime through a network path ChatGPT can reach. See [network connectivity](../clients/connectivity.md).

## Public URL

ChatGPT must reach the server over HTTPS. The MCP endpoint is:

```text
https://your-public-host.example.com/mcp
```

Make sure `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` matches the public origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Do not include `/mcp` in `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## OAuth setup

Recommended public settings:

```env
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<long random value>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<long random value>
LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S=0
```

Access tokens do not expire by default because long coding sessions can exceed short token lifetimes. Revoke access by rotating the JWT secret or redeploying with a fresh state when needed.

## Adding the connector

1. Open ChatGPT connector or Developer Mode MCP settings.
2. Add a custom MCP server.
3. Enter the MCP URL: `https://your-public-host.example.com/mcp`.
4. Complete OAuth.
5. Approve the tool surface.

## First prompt

```text
Use local-shell-mcp. First call environment_info, then list the workspace root. Do not modify files yet.
```

This verifies connectivity without making changes.

## Recommended operating rules

Give the model clear constraints:

- Work inside `/workspace` unless explicitly told otherwise.
- Run tests before committing.
- Use `secret_scan` before pushing.
- Use `create_file_link` only for files that are safe to share.
- Prefer persistent shell sessions for long-running processes.
- Summarize all commands that changed files.

## Tool discovery issues

If ChatGPT can authenticate but does not show expected tools:

- Confirm the endpoint ends in `/mcp`.
- Check `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY`.
- Check reverse proxy headers and request body limits.
- Inspect `docker compose logs --tail=200 local-shell-mcp`.
- Confirm the service is in `mcp` or `both` mode.

## Safety notes

Public deployments must keep OAuth enabled. Do not expose unauthenticated full MCP tools on the public internet. Treat every approved tool as part of the connected model's effective authority.
