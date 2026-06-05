# local-shell-mcp VS Code guide

## What this extension does

The extension is a thin VS Code wrapper around the `local-shell-mcp` server. It does not replace the server. It starts the server with the current VS Code workspace as `LOCAL_SHELL_MCP_WORKSPACE_ROOT`, keeps a local output channel open, and gives you commands to copy the MCP URL and a ready-to-paste ChatGPT setup prompt.

## Commands

- `local-shell-mcp: Start Server`
- `local-shell-mcp: Stop Server`
- `local-shell-mcp: Restart Server`
- `local-shell-mcp: Show Server Status`
- `local-shell-mcp: Copy MCP URL`
- `local-shell-mcp: Copy ChatGPT Setup Prompt`
- `local-shell-mcp: Open Guide`

## Recommended settings

For direct host usage, keep `local-shell-mcp.allowFullContainer` disabled so tools stay scoped to the selected workspace root.

Use `local-shell-mcp.authMode = oauth` when connecting ChatGPT. Use `none` only for trusted localhost testing.

If ChatGPT cannot reach your local machine directly, expose `127.0.0.1:8765` through an HTTPS tunnel and set `local-shell-mcp.publicBaseUrl` to that origin. The MCP endpoint is then:

```text
https://your-public-origin.example.com/mcp
```

## Typical ChatGPT prompt

After starting the server, run `local-shell-mcp: Copy ChatGPT Setup Prompt`. It includes the workspace path, MCP URL, and instruction to use local-shell-mcp tools for code inspection, edits, tests, Git operations, and release checks.
