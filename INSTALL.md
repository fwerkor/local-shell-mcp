# Installation

This guide covers ways to run `local-shell-mcp` as a ChatGPT-compatible MCP server.

## Prerequisites

You need one of these deployment paths:

- Docker and Docker Compose, recommended for most users.
- A release binary for Linux, macOS, or Windows.
- A Python environment if installing from source.
- Optional: `cloudflared` or another HTTPS tunnel when connecting from ChatGPT over the public internet.

ChatGPT custom connectors require a public HTTPS origin for OAuth and MCP access. Local-only MCP clients can connect directly to localhost.

## Docker Compose

Create the required Compose environment file:

```bash
cp .env.example .env
```

Edit `.env`; Docker Compose passes this file to the `local-shell-mcp` container with `env_file:`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false
CLOUDFLARE_TUNNEL_TOKEN=
```

Generate a stable JWT secret with:

```bash
openssl rand -hex 32
```

Create the default workspace and start the service:

```bash
mkdir -p workspaces/default
docker compose up -d
```

Check it:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

The Compose file mounts:

- `./workspaces/default/agent/workspace` as `/workspace`, the controlled project workspace.
- `./workspaces/default` as `/home`, the container home tree.
- `local-shell-mcp-credentials` as `/persist/credentials`, used for persistent GitHub CLI, Git HTTPS, GitCode, SSH, `.netrc`, and GPG state when credential persistence is enabled.

Set `DOCKER_PERSISTENT_CREDENTIALS=false` in `.env` for a more disposable authentication state. Docker-only startup knobs use `DOCKER_*`; application settings continue to use `LOCAL_SHELL_MCP_*`.

If the container cannot write `/workspace/.local-shell-mcp`, fix host ownership:

```bash
sudo mkdir -p workspaces/default/.local-shell-mcp
sudo chown -R 10001:10001 workspaces/default
docker compose restart local-shell-mcp
```

## Cloudflare Tunnel sidecar

The bundled Compose file includes an optional `cloudflared` sidecar profile. Create a tunnel in Cloudflare Zero Trust, add a public hostname, and point it to:

```text
http://local-shell-mcp:8765
```

Put the tunnel token in `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=...
```

Start both services:

```bash
docker compose --profile tunnel up -d
```

Your public MCP endpoint should be:

```text
https://your-public-host.example.com/mcp
```

This sidecar uses Cloudflare Tunnel only. It does not configure Cloudflare Access.

## Docker without Compose

```bash
docker pull rijuyuezhu/local-shell-mcp:latest
mkdir -p workspace
docker run -d   --name local-shell-mcp   --restart unless-stopped   --env-file .env   -p 127.0.0.1:8765:8765   -v "$PWD/workspace:/workspace"   rijuyuezhu/local-shell-mcp:latest
```

Check the restart policy:

```bash
docker inspect local-shell-mcp --format '{{.HostConfig.RestartPolicy.Name}}'
```

It should be `unless-stopped`.

## Release binary

Download a Docker-free executable from GitHub Releases when you do not want to run Docker. Release assets are built for Linux, macOS, and Windows on x86_64 and ARM64/aarch64.

Start it directly:

```bash
./local-shell-mcp --mode mcp
```

On Windows PowerShell:

```powershell
.\local-shell-mcp.exe --mode mcp
```

For binary deployments, set `LOCAL_SHELL_MCP_WORKSPACE_ROOT` to the directory you want the tools to control:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/project ./local-shell-mcp --mode mcp
```

The binary includes the Python server and default OAuth dependencies. It does not bundle host tools such as Git, tmux, shells, compilers, or LibreOffice; those are taken from the host system.

## VS Code extension

`local-shell-mcp` ships a VS Code extension package named like `local-shell-mcp-vscode-<version>.vsix` in GitHub Releases.

Basic flow:

1. Install the `local-shell-mcp` executable from a release or with `pipx install local-shell-mcp`.
2. Install the `.vsix` file in VS Code.
3. Open a project folder.
4. Run **local-shell-mcp: Start Server** from the command palette.
5. Run **local-shell-mcp: Copy MCP URL** and add it to your MCP client.
6. Run **local-shell-mcp: Copy ChatGPT Setup Prompt** when starting a coding session.

For public ChatGPT access, expose the local server through HTTPS and set `local-shell-mcp.publicBaseUrl` in VS Code settings. Keep `local-shell-mcp.allowFullContainer` disabled for direct host usage.

See [vscode-extension/README.md](vscode-extension/README.md) and [vscode-extension/GUIDE.md](vscode-extension/GUIDE.md).

## Install from source

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode mcp
```

For source development details, see [DEVELOPMENT.md](DEVELOPMENT.md).
