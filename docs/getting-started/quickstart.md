# Quickstart

This path starts `local-shell-mcp` with Docker Compose and connects ChatGPT to the public `/mcp` endpoint.

## 1. Prepare configuration

```bash
cp .env.example .env
```

Set at least:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false
```

## 2. Start the service

```bash
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## 3. Expose HTTPS

ChatGPT custom connectors need a public HTTPS origin. The bundled Compose file includes an optional Cloudflare Tunnel sidecar profile; Cloudflare Access is not required.

## 4. Add the MCP connector

Use this URL in ChatGPT:

```text
https://your-public-host.example.com/mcp
```

Enable Developer Mode before adding the connector when you want shell, filesystem, Git, browser, and remote-worker tools.
