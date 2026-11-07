# Quickstart

This guide starts an LSM Controller and opens its browser interface. The [unified web workspace](web-workspace.md) is the recommended daily experience; it is a separately deployed, optional chat stack. ChatGPT, Gemini and other external MCP clients can connect to the same Controller. See [runtime choices and deployment model](../guides/deployment.md).

## Requirements

- Docker Engine with Compose v2.
- A public HTTPS endpoint if remote users or external MCP clients must connect.
- A dedicated workspace directory.
- A long random OAuth admin PIN and JWT secret.

!!! warning
    The connected model can operate the configured workspace. Run the service in a disposable container or VM and avoid mounting host-control resources.

## 1. Clone and configure

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

Edit `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
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

A healthy response returns HTTP `200`.

## 3. Expose HTTPS

For Cloudflare Tunnel sidecar:

```bash
docker compose --profile tunnel up -d
```

In Cloudflare Zero Trust, point the public hostname to:

```text
http://local-shell-mcp:8765
```

For Caddy, Nginx, Traefik, Nginx Proxy Manager, or another reverse proxy, forward HTTPS traffic to `127.0.0.1:8765` or the container network address.

## 4. Open the browser workspace

Open the Controller login:

```text
https://your-public-host.example.com/ui
```

For chat, projects and integrated control pages, follow the [unified web workspace guide](web-workspace.md). The original lightweight WebUI is available when chat is not installed.

## 5. Confirm tool access safely

Ask the model:

```text
Use local-shell-mcp. First call environment_get, then list the workspace root. Do not modify files yet.
```

Expected read-only tools:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Start with a bounded coding task

A good first task:

```text
Inspect this repository, summarize the project layout, run the existing test suite if one is obvious, and do not change files.
```

After connectivity is confirmed, give more specific instructions:

```text
Fix the failing test. Read the relevant files first, make the smallest patch, run the targeted test, then show git diff. Do not commit until I approve.
```

## Updating

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

If you use the tunnel profile:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

## Next pages

| Need | Page |
|---|---|
| Understand runtime vs client choices | [Runtime choices and deployment model](../guides/deployment.md) |
| Run with Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Run from VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Run with a release binary | [Standalone binary runtime](../installation/binary.md) |
| Run with Python or source checkout | [Python runtimes](../installation/python.md) |
| Use the unified chat and control interface | [Unified web workspace](web-workspace.md) |
| Add Gemini Spark as a client | [Gemini Custom Apps](gemini-spark.md) |
| Add ChatGPT as a client | [ChatGPT connector](chatgpt-connector.md) |
| Choose tools and write better prompts | [Usage patterns](../guides/usage-patterns.md) |
| Attach an HPC, NPU/GPU, or NAT machine | [Remote workers](../guides/remote-workers.md) |
| Understand every MCP tool | [Tools reference](../reference/tools.md) |
