# Deployment guide

This page compares common ways to run `local-shell-mcp`.

## Docker Compose

Recommended for most users. It provides predictable isolation and the broadest built-in toolchain.

```bash
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
```

Advantages:

- Container boundary around the AI-controlled environment.
- Persistent `/workspace` volume.
- Optional persistent credential volume.
- Built-in Python, Node.js, Go, Rust, Java, Git, tmux, ripgrep, Playwright, LibreOffice, and document tools.

## Docker with tunnel sidecar

Use the `tunnel` profile when Cloudflare Tunnel should run next to the server:

```bash
docker compose --profile tunnel up -d
```

Set `CLOUDFLARE_TUNNEL_TOKEN` in `.env` and configure a Cloudflare public hostname that forwards to `http://local-shell-mcp:8765`.

## Standalone binary

Use a release binary when Docker is unavailable:

```bash
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace
./local-shell-mcp --mode mcp
```

Binary deployments rely on host tools. Install Git, tmux, shells, compilers, Playwright browsers, and document tools yourself.

## Reverse proxy

Any HTTPS reverse proxy can forward to the local service:

```text
https://mcp.example.com -> http://127.0.0.1:8765
```

Make sure the proxy supports streaming request/response bodies and does not strip OAuth-related headers.

## Recommended production posture

- OAuth enabled.
- Dedicated subdomain.
- Disposable container or VM.
- No host root mount.
- No Docker socket mount.
- Minimal credentials.
- Regular image updates.
- Audit log retention according to your risk tolerance.

## Upgrade checklist

1. Read release notes.
2. Pull the new image or binary.
3. Restart the server.
4. Check `/healthz`.
5. Reconnect ChatGPT if OAuth settings changed.
6. Run a safe read-only tool call before continuing a coding task.
