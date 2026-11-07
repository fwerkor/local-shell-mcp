# Docker Compose runtime

Docker Compose is an alternative for disposable or isolated deployments. **Direct source-checkout deployment is recommended for most users**; see the [Python/source runtime guide](python.md). Docker provides a controlled Linux workspace and convenient rebuilds, but its image is deliberately lightweight and task-specific tools must be installed separately.

This is a runtime choice. It can be connected to ChatGPT, a generic HTTP MCP client, or kept local for testing.

## What the Docker image includes

The image uses python:3.12-slim and includes only essential runtime utilities. Full development toolchains, Playwright/browser binaries, and office suites are not preinstalled.

Availability by category:

| Category | Examples |
|---|---|
| Shell and inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git and credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | Not included by default; install when needed |
| Python | Python 3.12, pip, virtualenv |
| JavaScript/TypeScript | Not included by default; install when needed |
| Other languages | Not included by default; install when needed |
| Browser automation | Not included by default; install when needed |
| Document tooling | Not included by default; install when needed |

The exact image content should be treated as a convenience layer, not a stable API. Project-specific dependencies still belong in the workspace or project build scripts.

## Basic local run

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

The raw CLI token stays only in the host-owned `.env` (mode `0600`). Compose passes only its SHA-256 verifier into the container. This lets `lsm call` authenticate across the Docker published-port bridge without exposing a reusable privileged token to managed shell processes inside the container.

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

**Not recommended for file transfers:** Cloudflare Tunnel can have very slow client-side upload throughput, which can make LSM's file upload and transfer features impractical. **Prefer deploying directly on a public server or forwarding through one with an HTTPS reverse proxy**, as described in [network connectivity](../clients/connectivity.md). Use the sidecar only as a fallback.

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
The Compose service trusts forwarded headers because its published port is restricted to localhost; this preserves the public caller address for OAuth PIN rate limiting. If you expose the container port directly, replace `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` with the explicit addresses of your trusted reverse proxies.

## Reverse proxy without tunnel sidecar

**Recommended for public access.** Deploy the Controller on a public server, or use a public server to forward traffic to a private Controller. Terminate HTTPS at a trusted reverse proxy and preserve request bodies and streaming responses for file transfers.
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
Use local-shell-mcp. Call environment_get and file_list on the workspace root. Do not modify files.
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `/healthz` fails locally | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT cannot discover tools | Public URL must end in `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` must not include `/mcp` |
| OAuth page fails | Admin PIN and JWT secret must be set for public OAuth deployments |
| Tools cannot see files | Confirm the intended host directory is mounted to `/workspace` |
| Browser tools fail | Confirm Playwright image is current; try `run_shell` for the target browser |
| Git auth disappeared | Check the credential volume and whether the container was recreated with the same volume |
