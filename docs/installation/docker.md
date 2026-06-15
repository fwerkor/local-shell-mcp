# Docker Compose runtime

Docker Compose is the recommended runtime for most users. It gives the model a controlled Linux workspace, a repeatable toolchain, persistent credentials, browser automation support, and an easy upgrade path.

This is a runtime choice. It can be connected to ChatGPT, a generic HTTP MCP client, or kept local for testing.

## What the Docker image includes

The image is based on the Playwright Python image and installs a broad development toolchain. The intent is to let an AI coding agent operate many repositories without asking you to rebuild the runtime for every project.

Included categories:

| Category | Examples |
|---|---|
| Shell and inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git and credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Other languages | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

The exact image content should be treated as a convenience layer, not a stable API. Project-specific dependencies still belong in the workspace or project build scripts.

## Basic local run

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

The default Compose file binds the service to localhost:

```text
127.0.0.1:8765 -> container:8765
```

That is appropriate for local testing and for a reverse proxy running on the same host.

## Workspace layout

The default Compose runtime mounts:

| Host path or volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Controlled workspace visible to tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Use one workspace directory per trust boundary. Do not mount your whole home directory just because it is convenient.

## Required public settings

For ChatGPT or another public HTTP MCP client, configure `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Generate a JWT secret with a command such as:

```bash
openssl rand -hex 32
```

The public MCP URL is:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

The Compose file includes an optional `cloudflared` service behind the `tunnel` profile. This runs the tunnel next to the MCP server.

Configure `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Start both services:

```bash
docker compose --profile tunnel up -d
```

In Cloudflare Zero Trust, route the public hostname to:

```text
http://local-shell-mcp:8765
```

This is Cloudflare Tunnel, not Cloudflare Access. `local-shell-mcp` still handles its own OAuth for ChatGPT.

## Reverse proxy without tunnel sidecar

If you already run Caddy, Nginx, Traefik, or Nginx Proxy Manager, keep the normal Compose service and forward HTTPS to:

```text
http://127.0.0.1:8765
```

The proxy must forward these routes without stripping paths:

| Route | Purpose |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | OAuth resource metadata |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata |
| `/oauth/register` | Dynamic client registration |
| `/oauth/authorize` | Browser authorization page |
| `/oauth/token` | Token exchange |
| `/downloads/<token>` | Optional generated file downloads |
| `/join/<token>`, `/remote/*` | Optional remote-worker bootstrap and polling |

See [network connectivity](../clients/connectivity.md) for proxy behavior requirements.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` keeps filesystem operations scoped to the workspace. This is the safer default.

Set it to `true` only when the container is intentionally disposable and the model is expected to operate the whole container filesystem. When enabled, built-in command and path denylist restrictions are removed.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Do not enable full-container mode on a host-launched runtime such as the VS Code extension or a binary running directly on your laptop.

## Credentials

The Docker runtime can persist common developer credentials in a dedicated volume. This is useful for GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config, and GPG state.

Treat the credential volume as sensitive. Prefer repository-scoped deploy keys, fine-grained tokens, or short-lived credentials. Do not put broad personal credentials in a workspace that the model can freely read.

Optional SSH-agent forwarding is possible by mounting the SSH agent socket, but this extends trust from the container to your active agent. Use it only when you understand the exposure.

## Updates

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

With tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

After upgrading, ask the client to run a read-only check first:

```text
Use local-shell-mcp. Call environment_info and list_files on the workspace root. Do not modify files.
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `/healthz` fails locally | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT cannot discover tools | Public URL must end in `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` must not include `/mcp` |
| OAuth page fails | Admin PIN and JWT secret must be set for public OAuth deployments |
| Tools cannot see files | Confirm the intended host directory is mounted to `/workspace` |
| Browser tools fail | Confirm Playwright image is current; try `playwright_install_tool` for the target browser |
| Git auth disappeared | Check the credential volume and whether the container was recreated with the same volume |
