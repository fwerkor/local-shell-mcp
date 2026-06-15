# Dépannage

Check server health:

```bash
docker compose ps
docker compose logs --tail=200 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Common checks:

- Public HTTPS URL is reachable.
- MCP endpoint ends with `/mcp`.
- OAuth values match the current deployment.
- Reverse proxy supports streaming requests.
- Remote worker invite has not expired.
- Workspace permissions allow writes to `/workspace/.local-shell-mcp`.
