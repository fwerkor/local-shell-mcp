# VS Code extension runtime

The VS Code extension is a launcher and convenience UI for the same `local-shell-mcp` server. It is a runtime choice because it starts the server process for the current editor workspace.

It is not the ChatGPT connector itself. ChatGPT still connects to a public HTTPS `/mcp` endpoint when used from the web/app.

## What the extension does

The extension:

- Starts `local-shell-mcp` for the current VS Code workspace.
- Stops and restarts the server.
- Shows server output in a VS Code output channel.
- Checks `/healthz`.
- Copies the MCP URL.
- Copies a ChatGPT setup prompt containing the workspace and endpoint.

The extension does not bundle the server binary. Install `local-shell-mcp` separately, then point the extension at that executable if it is not on `PATH`.

## When to use it

Use this runtime when:

- You normally start work from a VS Code folder.
- You want a button/command-palette flow instead of manually launching a terminal command.
- The project already has dependencies installed on the host.
- You are working on trusted repositories or a narrow workspace.
- You are comfortable exposing only that workspace to the model.

Use Docker instead when:

- The repository is untrusted.
- The task will install arbitrary packages.
- The task needs a broad preinstalled toolchain.
- You want easy reset by recreating a container.
- You want a cleaner boundary than your host account.

## Install the executable

Choose one server install method:

```bash
pipx install local-shell-mcp
```

or download the release binary for your OS and put it on `PATH`.

Then install the VSIX release asset:

```bash
code --install-extension local-shell-mcp-vscode-<version>.vsix
```

Alternatively, use **Extensions: Install from VSIX...** in the command palette.

## Extension settings

| Setting | Purpose | Typical value |
|---|---|---|
| `local-shell-mcp.executablePath` | Path to the server executable | `local-shell-mcp` or an absolute binary path |
| `local-shell-mcp.host` | Bind address for the local server | `127.0.0.1` for local-only, `0.0.0.0` only behind a controlled network/proxy |
| `local-shell-mcp.port` | Local server port | `8765` |
| `local-shell-mcp.workspaceRoot` | Workspace exposed to MCP | Empty for the first VS Code folder, or an explicit path |
| `local-shell-mcp.authMode` | Authentication mode | `oauth` for ChatGPT, `none` only for trusted localhost testing |
| `local-shell-mcp.publicBaseUrl` | Public HTTPS origin copied into prompts and URLs | Tunnel/proxy origin such as `https://mcp.example.com` |
| `local-shell-mcp.oauthAdminPin` | PIN for OAuth authorization | Strong random value for public use |
| `local-shell-mcp.allowFullContainer` | Full-container behavior flag | Keep `false` for direct host usage |
| `local-shell-mcp.extraEnv` | Extra environment for server process | Project-specific safe values only |

## Basic flow

1. Open a project folder in VS Code.
2. Run **local-shell-mcp: Start Server**.
3. Run **local-shell-mcp: Show Server Status** or **Check Health** if available.
4. Run **local-shell-mcp: Copy MCP URL** for a local MCP client, or **Copy ChatGPT Setup Prompt** for ChatGPT.
5. Add the endpoint to your client.

The local endpoint usually looks like:

```text
http://127.0.0.1:8765/mcp
```

This is useful for local clients but is not reachable by ChatGPT web/app.

## Using it with ChatGPT

To use a VS Code-launched server from ChatGPT, add an HTTPS tunnel or reverse proxy in front of the local port.

Example shape:

```text
ChatGPT
  -> https://your-public-host.example.com/mcp
  -> tunnel or reverse proxy
  -> 127.0.0.1:8765 on your machine
  -> VS Code-launched local-shell-mcp process
```

Set:

```text
local-shell-mcp.publicBaseUrl = https://your-public-host.example.com
local-shell-mcp.authMode = oauth
local-shell-mcp.oauthAdminPin = <strong pin>
```

The URL copied for ChatGPT should end in `/mcp`:

```text
https://your-public-host.example.com/mcp
```

## Host-runtime safety

The extension usually runs commands as your host user. That is materially different from a disposable Docker container.

Recommended rules:

- Open only the repository you want the model to control.
- Keep `allowFullContainer` disabled.
- Do not set the workspace root to your home directory.
- Do not keep unrelated secrets in the workspace.
- Use `secret_scan` before commits and pushes.
- Prefer Docker for unfamiliar repositories or package-install-heavy tasks.

## Common prompt

After copying the setup prompt, start with a read-only task:

```text
Use local-shell-mcp. First call environment_info and tree_view on the workspace. Do not modify files yet.
```

Then move to a bounded edit:

```text
Fix the failing test in this workspace. Read the relevant files first, make the smallest patch, run the targeted test, and show git diff. Do not commit until I approve.
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Extension cannot start server | Confirm `local-shell-mcp.executablePath` exists and runs `--help` in a terminal |
| ChatGPT cannot reach it | A local `127.0.0.1` URL is not public; configure a tunnel/proxy and `publicBaseUrl` |
| Tools expose the wrong folder | Set `local-shell-mcp.workspaceRoot` explicitly |
| Auth fails after restart | Set a stable OAuth admin PIN and JWT secret through `extraEnv` or runtime configuration |
| Commands lack dependencies | Install dependencies on the host or switch to Docker runtime |
