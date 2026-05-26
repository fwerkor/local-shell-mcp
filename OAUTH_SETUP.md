# ChatGPT OAuth setup

`local-shell-mcp` v0.2 removes Cloudflare Access as the default authentication layer and includes a small OAuth 2.1 authorization server for ChatGPT custom connectors.

## Environment

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://local-shell-mcp.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=replace-with-a-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=replace-with-output-of-openssl-rand-hex-32
```

Generate the secret:

```bash
openssl rand -hex 32
```

## Start

```bash
cp .env.example .env
# edit .env
docker compose up -d --build
```

With Cloudflare Tunnel only:

```bash
docker compose --profile tunnel up -d --build
```

## ChatGPT connector

Connector URL:

```text
https://your-public-host.example.com/mcp
```

On first connection, ChatGPT will open `/oauth/authorize`. Enter `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` to approve the connector. ChatGPT will then exchange the authorization code for a bearer token and call `/mcp` with `Authorization: Bearer ...`.

Bearer tokens do not expire by default. Set `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` to a positive number of seconds if you want expiring tokens.

## Important

Do not use `LOCAL_SHELL_MCP_AUTH_MODE=none` on a public hostname. This server can execute shell commands in the container.
