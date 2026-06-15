# Quickstart

This guide starts a Docker Compose deployment suitable for ChatGPT Developer Mode and full MCP clients.

## Requirements

- Docker Engine with Compose v2.
- A public HTTPS endpoint if ChatGPT must connect from the web.
- A dedicated workspace directory.
- A long random OAuth admin PIN and JWT secret.

!!! warning
    The connected model can operate the configured workspace. Run the service in a disposable container or VM and avoid mounting host-control resources.

## 1. Clone and configure

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
```

Edit `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

Generate secrets with any trusted password manager, or use:

```bash
python3 - <<'PY'
import secrets
print('PIN:', secrets.token_urlsafe(24))
print('JWT:', secrets.token_hex(64))
PY
```

## 2. Start the server

```bash
mkdir -p workspaces/default
docker compose up -d
```

Check status:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

A healthy response returns HTTP `200` and a small JSON payload.

## 3. Expose HTTPS

For Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

In Cloudflare Zero Trust, point the public hostname to:

```text
http://local-shell-mcp:8765
```

For a reverse proxy such as Caddy or Nginx, forward HTTPS traffic to `127.0.0.1:8765` or the container network address.

## 4. Connect ChatGPT

Use the endpoint:

```text
https://your-public-host.example.com/mcp
```

Follow the [ChatGPT connector guide](chatgpt-connector.md) to finish OAuth and tool discovery.

## 5. Confirm tool access

Ask the model to run a safe command such as:

```text
Use local-shell-mcp to show the current workspace path and list the top-level files.
```

Expected tools:

- `environment_info`
- `list_files`
- `run_shell_tool`
- `read_file`

## Updating

```bash
docker compose pull
docker compose up -d
```

If you use the tunnel profile:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
```

## Binary deployment

Release assets include standalone binaries. Set a workspace root before starting:

```bash
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace
export LOCAL_SHELL_MCP_AUTH_MODE=oauth
./local-shell-mcp --mode mcp
```

Binary deployments use host tools for Git, shells, compilers, tmux, LibreOffice, and Playwright browsers. Docker images include a broader toolchain by default.
