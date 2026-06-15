# Stdio runtime

Stdio mode is for local MCP clients that start `local-shell-mcp` as a child process and communicate over standard input/output.

It is not a public HTTP deployment. It is not usable by ChatGPT web/app directly because ChatGPT cannot spawn a process on your machine.

## When to use stdio

Use stdio mode when:

- Your MCP client supports command-based server definitions.
- The client and the controlled workspace are on the same machine.
- You do not need OAuth, public HTTPS, reverse proxies, or tunnels.
- You want the client to manage the server lifecycle.

Do not use stdio mode when:

- The client is ChatGPT web/app.
- Multiple remote clients need the same server.
- You need tokenized file downloads over HTTP.
- You need remote-worker join routes served over HTTP.

## Command

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode stdio
```

A generic MCP client configuration usually contains:

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

Adapt the schema to your client. Some clients call this `servers`, `tools`, `mcpServers`, or `contextServers`.

## Behavior differences from HTTP mode

| Area | Stdio mode | HTTP MCP mode |
|---|---|---|
| Transport | stdin/stdout | HTTP streamable MCP endpoint |
| Endpoint | None | `/mcp` |
| OAuth | Not needed | Recommended for public use |
| Health endpoint | None | `/healthz`, `/readyz` |
| Public ChatGPT use | No | Yes, behind HTTPS |
| Server lifecycle | Client launches process | You manage process/runtime |

The tool surface is otherwise the same server-side implementation, subject to configuration and client support.

## Safety notes

Stdio mode often runs directly on the host as the same user as the MCP client. Use a narrow workspace root and avoid broad filesystem access. Keep full-container mode disabled unless stdio is itself running inside a disposable container or VM.
