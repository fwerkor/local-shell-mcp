# REST API

The primary interface is MCP at `/mcp`. A REST surface is also available for health checks, file links, connector-style search/fetch, and some tool calls.

## Health

```http
GET /healthz
```

Returns server health and basic status.

## MCP

```http
POST /mcp
```

Streamable HTTP MCP endpoint used by ChatGPT and other MCP clients.

## Connector discovery

Read-only connector-style operations:

```text
search
fetch
```

These are intended for regular ChatGPT connector behavior and do not expose the full coding-agent tool surface.

## Tool calls through REST

REST tool calls use consistent success/error envelopes. Validation errors return structured `ok: false` payloads instead of raw framework exceptions.

## File links

Tokenized file downloads are served by the built-in HTTP app. Links are bearer URLs with TTL, optional max-download limits, and revocation support.

## Authentication

Public deployments should use OAuth. Localhost bypass can be enabled for development, but unauthenticated public access is unsafe.
