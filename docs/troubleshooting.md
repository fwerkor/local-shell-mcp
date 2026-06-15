# Troubleshooting

Check service health:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Check logs:

```bash
docker compose logs --tail=100 local-shell-mcp
```

If ChatGPT cannot connect, verify that `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` is the exact public HTTPS origin and that `/mcp`, OAuth metadata, and `/healthz` are reachable through the tunnel or reverse proxy.

If remote workers do not appear, confirm that remote mode is enabled, the invite has not expired, and the remote machine can make outbound HTTPS requests to the control server.
