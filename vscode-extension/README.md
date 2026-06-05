# local-shell-mcp for VS Code

This extension starts and manages `local-shell-mcp` from VS Code, exposing the current workspace through MCP so ChatGPT can collaborate on code with shell, filesystem, Git, search, todo, Playwright, and remote-worker tools.

## Prerequisites

Install `local-shell-mcp` first, either from the GitHub Release binary or from Python:

```bash
pipx install local-shell-mcp
# or: pip install local-shell-mcp
```

Then configure `local-shell-mcp.executablePath` if the executable is not on `PATH`.

## Basic flow

1. Open the project folder in VS Code.
2. Run **local-shell-mcp: Start Server**.
3. Run **local-shell-mcp: Copy MCP URL** and paste it into ChatGPT's MCP connector setup.
4. Run **local-shell-mcp: Copy ChatGPT Setup Prompt** and paste it into ChatGPT when starting a coding session.

For remote ChatGPT access, set `local-shell-mcp.publicBaseUrl` to a public HTTPS origin that forwards to this local server.
