# Generic MCP clients

`local-shell-mcp` can be used by ChatGPT and by other MCP clients. The client decides whether it connects over HTTP or launches the server through stdio.

## HTTP MCP clients

Use HTTP mode when the server is already running:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode mcp
```

Local endpoint:

```text
http://127.0.0.1:8765/mcp
```

Network endpoint:

```text
https://your-public-host.example.com/mcp
```

Use OAuth for any endpoint that is reachable beyond trusted localhost.

## Stdio MCP clients

Use stdio mode when the client starts the server process itself:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode stdio
```

Typical client configuration shape:

```json
{
  "mcpServers": {
    "local-shell-mcp": {
      "command": "local-shell-mcp",
      "args": ["--mode", "stdio"],
      "env": {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": "/path/to/workspace"
      }
    }
  }
}
```

Client schemas vary. Some call this section `mcpServers`; others use a different name.

## Connector-style search/fetch

The server also exposes read-only connector-style `search` and `fetch` tools. They are useful for basic file discovery but are not a replacement for the full MCP tool surface.

Use `/mcp` for the full shell, filesystem, Git, browser, file-link, and remote-worker tools.

## First safe check

For a newly connected client, start with:

```text
Call environment_info, then tree_view on the workspace root. Do not modify files yet.
```

Then run a bounded task with explicit edit, test, and Git rules.
