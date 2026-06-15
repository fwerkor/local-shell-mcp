# local-shell-mcp

`local-shell-mcp` exposes a controlled local or container workspace to ChatGPT and other MCP clients. It provides shell, persistent shell, filesystem, search, patch, git-through-shell, Playwright, audit, tokenized file-link, and remote-worker tools through a ChatGPT-compatible MCP server with OAuth support.

Use it when the AI needs to inspect a repository, run tests, edit files, operate Git, collect browser evidence, or control a remote machine that can only connect outbound to the control server.

## Main paths

- [Quickstart](getting-started/quickstart.md) for Docker Compose setup.
- [ChatGPT connector](getting-started/chatgpt-connector.md) for adding the MCP endpoint.
- [Remote workers](guides/remote-workers.md) for NAT/HPC-style machines.
- [Tools reference](reference/tools.md) for the public tool surface.
