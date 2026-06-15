# Browser automation

Cette page est une version localisée qui garde la même structure Runtime/Client.

## Vue d’ensemble

Runtime defines how the server process runs and which workspace it controls. Client defines how ChatGPT or another MCP client connects. Docker, the VS Code extension, standalone binaries, Python/pipx/source installs, and stdio are Runtime choices; ChatGPT connector, generic HTTP MCP client, and stdio MCP client are Client connections.

## Quand l’utiliser

- Use this page when the selected Runtime or Client path matches the title.
- Keep the workspace root, public base URL, MCP endpoint, authentication mode, and available host tools consistent.
- For ChatGPT web/app, expose an HTTPS MCP endpoint ending in `/mcp`.
- For local MCP clients, use HTTP localhost or `local-shell-mcp --mode stdio` depending on client support.

## Étapes

1. Choose the Runtime installation page first.
2. Start the Runtime and verify `/healthz` when HTTP mode is used.
3. Choose the Client connection page second.
4. Register the MCP endpoint or stdio command in the Client.
5. Call `environment_info` to verify the effective workspace and settings.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Vérification

- `environment_info` confirms runtime settings and workspace.
- `tree_view` confirms visible files.
- `git_status_tool` confirms repository context.
- `run_shell_tool` confirms the command environment.

## Notes

Prefer small, verifiable steps: inspect, edit, diff, test, scan, commit. Large tasks should still be decomposed into tool calls that can be audited.
