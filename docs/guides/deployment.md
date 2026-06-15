# Deployment and installation methods

This page compares the supported ways to run `local-shell-mcp`. The choice is mainly about isolation, how ChatGPT reaches the server, and how much tooling is preinstalled.

## Choose a method

| Method | Best for | Isolation | Public ChatGPT access | Toolchain responsibility |
|---|---|---|---|---|
| Docker Compose | Most users, coding agents, repeatable workspaces | Container boundary | Add HTTPS reverse proxy or tunnel | Image includes the broadest default toolchain |
| Docker Compose + tunnel sidecar | Quick public deployment with Cloudflare Tunnel | Container boundary | Built in through the `tunnel` profile | Image includes the broadest default toolchain |
| VS Code extension | Starting a server from an open editor workspace | Usually host process | Requires an external HTTPS tunnel or proxy | Host provides tools unless you point it at a container |
| Standalone binary | Hosts where Docker is unavailable | Host or VM boundary | Requires HTTPS reverse proxy or tunnel | Host must provide Git, shells, compilers, Playwright, document tools |
| `pipx` / source install | Development, debugging, local experiments | Host or virtualenv boundary | Requires HTTPS reverse proxy or tunnel | Python package plus host tools |
| Stdio mode | Local MCP clients that spawn the server directly | Client-dependent | Not for ChatGPT web access | Host tools |

For public ChatGPT usage, the endpoint must be HTTPS and normally ends with `/mcp`:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` must be the origin only:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Do not include `/mcp` in `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Docker Compose

Use Docker Compose when you want the normal project defaults: controlled `/workspace`, persistent workspace volume, credential volume, audit log, browser/document tooling, and a consistent runtime.

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Minimum public configuration:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Recommended when the AI will edit code, install packages, run tests, build artifacts, or use Playwright.

Avoid mounting host-control resources such as the Docker socket or the host root filesystem.

## Docker Compose with Cloudflare Tunnel sidecar

Use the tunnel profile when Cloudflare Tunnel should run beside the server.

```bash
cp .env.example .env
# Set CLOUDFLARE_TUNNEL_TOKEN and LOCAL_SHELL_MCP_PUBLIC_BASE_URL in .env
docker compose --profile tunnel up -d
```

In Cloudflare Zero Trust, point the public hostname to:

```text
http://local-shell-mcp:8765
```

Use this when you want a single Compose stack to provide both the MCP server and public HTTPS routing. If you already operate Nginx, Caddy, Traefik, or another ingress layer, a normal Docker Compose deployment behind that proxy is usually cleaner.

## VS Code extension

Release assets include `local-shell-mcp-vscode-<version>.vsix`. The extension starts and stops a local server for the current VS Code workspace, checks `/healthz`, copies the MCP URL, and copies a ChatGPT setup prompt.

Basic flow:

```text
Install local-shell-mcp executable
-> install the VSIX asset
-> open a project folder
-> run "local-shell-mcp: Start Server"
-> copy the MCP URL or setup prompt
```

The VS Code extension is convenient for editor-driven work, but a local server is not directly reachable by ChatGPT on the web. For ChatGPT access, expose it through HTTPS and set:

```text
local-shell-mcp.publicBaseUrl = https://your-public-host.example.com
```

Keep `local-shell-mcp.allowFullContainer` disabled for direct host usage. Enable full-container behavior only inside a disposable container or VM.

## Standalone binary

Use release binaries when Docker is not available or when a VM already provides the safety boundary.

```bash
mkdir -p /srv/local-shell-mcp/workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=/srv/local-shell-mcp/workspace
export LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
export LOCAL_SHELL_MCP_AUTH_MODE=oauth
export LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
export LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
./local-shell-mcp --mode mcp
```

Binary deployments rely on the host. Install the tools you expect the model to use: Git, `rg`, `tmux`, compilers, Python/Node/Go/Rust/Java as needed, Playwright browsers, LibreOffice, and package managers.

Use a systemd unit or another process supervisor for long-running public deployments.

## `pipx` or source install

Use `pipx` for a user-level install:

```bash
pipx install local-shell-mcp
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Use an editable install for development:

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,docs]'
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/tmp/local-shell-mcp-workspace local-shell-mcp --mode mcp
```

## Stdio mode

Stdio mode is for local MCP clients that start the server process themselves. It is not suitable for ChatGPT web/app access because ChatGPT cannot spawn local processes from the web.

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode stdio
```

## Reverse proxy requirements

Any HTTPS reverse proxy can forward to the local service:

```text
https://mcp.example.com -> http://127.0.0.1:8765
```

The proxy should preserve request bodies and streaming responses, forward OAuth routes, avoid small body-size limits, and keep timeouts long enough for tool discovery and long responses.

Common public routes:

| Route | Purpose |
|---|---|
| `/mcp` | Streamable HTTP MCP endpoint |
| `/healthz` | Health check |
| `/.well-known/oauth-protected-resource` | OAuth protected-resource metadata |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata |
| `/oauth/register` | Dynamic client registration |
| `/oauth/authorize` | Authorization page |
| `/oauth/token` | Token exchange |
| `/downloads/<token>` | Optional generated file links |
| `/join/<token>` and `/remote/*` | Optional remote-worker bootstrap and polling |

## Upgrade checklist

Docker:

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Docker with tunnel profile:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Binary or `pipx`:

1. Replace the executable or upgrade the Python package.
2. Restart the process manager.
3. Check `/healthz`.
4. Ask the model to run a read-only check such as `environment_info` and `list_files` before continuing a task.

## Production posture

Recommended defaults for public deployments:

- OAuth enabled.
- Dedicated subdomain.
- Disposable container or VM boundary.
- No Docker socket mount.
- No host root mount.
- Minimal credentials.
- Audit log retention appropriate for your risk.
- Remote worker mode disabled if you do not use it.
- File links disabled if you do not need downloadable artifacts.
