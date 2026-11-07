# Quickstart

This guide starts an LSM Controller and opens its browser interface. The [unified web workspace](web-workspace.md) is the recommended daily experience; it is a separately deployed, optional chat stack. ChatGPT, Gemini and other external MCP clients can connect to the same Controller. See [runtime choices and deployment model](../guides/deployment.md).

The recommended Controller deployment is a **direct source checkout** in a dedicated environment. Docker Compose is an optional alternative.

## Requirements

- Git, Python 3.11+ and a working `venv` / `pip` installation.
- A public HTTPS origin only if remote users or external MCP clients need access.
- A dedicated, narrowly scoped workspace.
- A strong OAuth admin PIN and randomly generated JWT secret.

!!! warning
    The connected model can operate the configured workspace. Run the service in a disposable container or VM and avoid mounting host-control resources.

## 1. Clone and configure

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Edit `.env` and replace the sample PIN and JWT secret (use the output of `openssl rand -hex 32`). The source runtime does not read `.env` automatically.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Start the server

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Check status from a second terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

A healthy response returns HTTP `200`. The first terminal must stay running; use your service manager for a long-lived deployment.

## 3. Expose HTTPS

For remote access, deploy on a publicly reachable server or forward port 8765 through an HTTPS reverse proxy (Caddy, Nginx, Traefik or equivalent). Forward the entire origin, including uploads and downloads, to:

```text
http://127.0.0.1:8765
```

After configuring HTTPS, verify the endpoint:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel is not recommended** for deployments that transfer files: its client-side upload path can be slow. Prefer direct public-server deployment or a conventional reverse proxy/port forwarding where possible. Keep OAuth enabled on public endpoints. Docker Compose instructions remain in the [Docker runtime guide](../installation/docker.md).

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

Update the checkout, reinstall the editable package, and restart the Controller process or service:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

For deployments that explicitly chose Docker Compose, update the container instead:

```bash
docker compose pull
docker compose up -d
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
