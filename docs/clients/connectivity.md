# Network connectivity

HTTP MCP clients outside the machine need a reachable HTTPS origin. This page is about network routing, not about which runtime you choose.

The client endpoint normally ends with `/mcp`:

```text
https://your-public-host.example.com/mcp
```

The server's public base URL setting is the origin only:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Do not include `/mcp` in that base URL.

## Connectivity options

**Recommended:** Deploy directly to a public server, or forward traffic from a private Controller through a public server. Terminate HTTPS with a reverse proxy and ensure it can handle file-upload request bodies and streaming transfers.

**Cloudflare Tunnel is not recommended** for file-transfer workflows: its client-side upload throughput can be very slow, making file uploads or transfers impractical. Use it only as a fallback when direct deployment or public-server forwarding is unavailable.

| Option | Use when |
|---|---|
| Caddy | Public-server deployment with simple automatic TLS |
| Nginx or Nginx Proxy Manager | Public server or forwarding host with Nginx infrastructure |
| Traefik | Container-native routing on a public server or forwarding host |
| Public-server forwarding | The Controller is private but traffic can be relayed through a public server |
| Cloudflare Tunnel sidecar (not recommended) | Fallback with the optional Compose `tunnel` profile; file uploads may be slow |

## Paths

Forward the whole origin to the running server. Important paths include:

| Path | Purpose |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/...` | Client discovery metadata |
| `/oauth/...` | Client authorization flow |
| `/downloads/...` | Optional generated file links |
| `/join/...`, `/remote/...` | Optional remote-worker flow |

## Proxy behavior

The proxy should preserve paths, forward request bodies, support long responses, and avoid very short timeouts.

## Checks

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Common mistakes

| Mistake | Fix |
|---|---|
| Using `https://host` instead of `https://host/mcp` in ChatGPT | Add `/mcp` only in the client endpoint |
| Setting `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Set the origin only |
| Routing only `/mcp` | Route the full origin so discovery and authorization paths also work |
| Running a host runtime with a broad workspace | Use a narrow workspace or Docker |

## Suggested pairing

| Runtime | Network pattern |
|---|---|
| Docker Compose on a public server | HTTPS reverse proxy |
| Docker Compose on a home machine | Forward through a public server if available; Cloudflare Tunnel only as a fallback |
| VS Code extension on a laptop | Public-server forwarding if remote access is needed |
| Binary on a VM | Reverse proxy on the VM or network edge |
| Python/source dev server | Usually localhost only |
| Stdio mode | No HTTP network path; use a local MCP client |
