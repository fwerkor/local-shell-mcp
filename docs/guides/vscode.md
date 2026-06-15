# VS Code extension

Release assets include a VS Code extension package named `local-shell-mcp-vscode-<version>.vsix`.

The extension is a thin launcher around the server. It is designed to make ChatGPT collaboration feel closer to a coding-agent workflow while still using the ChatGPT web/app UI.

## When to use it

Use the extension when:

- You normally start work from a VS Code project folder.
- You want quick start/stop commands without managing a terminal service manually.
- You want a ready-to-copy ChatGPT setup prompt for the current workspace.
- You are using a local tunnel or reverse proxy for ChatGPT access.

Use Docker Compose instead when you want stronger isolation or a richer preinstalled toolchain.

## Features

- Start and stop `local-shell-mcp` for the current workspace.
- Show server output in a VS Code output channel.
- Check `/healthz`.
- Copy the local MCP URL.
- Copy a ChatGPT setup prompt.
- Configure public base URL and full-container behavior.

## Install

1. Install the `local-shell-mcp` executable from a GitHub Release or with `pipx install local-shell-mcp`.
2. Download `local-shell-mcp-vscode-<version>.vsix` from the same release.
3. Install the VSIX in VS Code:

```bash
code --install-extension local-shell-mcp-vscode-<version>.vsix
```

Or use **Extensions: Install from VSIX...** from the command palette.

## Basic workflow

1. Open a project folder.
2. Run **local-shell-mcp: Start Server**.
3. Run **local-shell-mcp: Check Health**.
4. Run **local-shell-mcp: Copy MCP URL** or **local-shell-mcp: Copy ChatGPT Setup Prompt**.
5. Add the endpoint to ChatGPT or another MCP client.

## Public ChatGPT access

ChatGPT must reach the server over HTTPS. A server bound only to `127.0.0.1` is useful for local MCP clients, but it is not reachable from ChatGPT web/app.

Expose the local server through a tunnel or reverse proxy, then configure:

```text
local-shell-mcp.publicBaseUrl = https://your-public-host.example.com
```

The endpoint copied for ChatGPT should end with `/mcp`:

```text
https://your-public-host.example.com/mcp
```

## Settings

| Setting | Purpose | Recommended value |
|---|---|---|
| `local-shell-mcp.publicBaseUrl` | Public HTTPS origin used in copied prompts and URLs | Your tunnel/proxy origin |
| `local-shell-mcp.allowFullContainer` | Allow full-container behavior instead of workspace-only operation | `false` on host; `true` only in disposable containers/VMs |
| `local-shell-mcp.executablePath` | Path to the server executable if it is not on `PATH` | Explicit release binary or `pipx` shim path |

## Safety notes

The extension usually runs on the host. That is different from the Docker Compose deployment where the container is the intended safety boundary. For host-launched usage:

- Keep the workspace narrow.
- Do not expose unrelated directories.
- Avoid long-lived credentials in the workspace.
- Keep full-container mode disabled.
- Prefer Docker when the task needs package installation, arbitrary build scripts, or untrusted repositories.
