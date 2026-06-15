# Support

Use the documentation first:

- Documentation: https://fwerkor.github.io/local-shell-mcp/
- Quickstart: https://fwerkor.github.io/local-shell-mcp/getting-started/quickstart/
- ChatGPT connector: https://fwerkor.github.io/local-shell-mcp/getting-started/chatgpt-connector/
- Remote workers: https://fwerkor.github.io/local-shell-mcp/guides/remote-workers/
- Troubleshooting: https://fwerkor.github.io/local-shell-mcp/troubleshooting/

## Where to ask

- Use GitHub Issues for reproducible bugs, documentation problems, and feature requests.
- Use GitHub Discussions if enabled for open-ended usage questions.
- Do not post secrets, OAuth pins, tunnel tokens, private keys, or bearer file-link URLs.

## Useful diagnostics

When reporting a problem, include:

```bash
docker compose ps
docker compose logs --tail=200 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Also include the deployment mode, version, operating system, browser or MCP client, and whether OAuth, Cloudflare Tunnel, remote workers, or full-container mode are involved.
