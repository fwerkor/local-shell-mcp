# VS Code extension

Release assets include a VS Code extension package named `local-shell-mcp-vscode-<version>.vsix`.

The extension is a thin launcher around the server. It is designed to make ChatGPT collaboration feel closer to a coding-agent workflow while still using the ChatGPT web/app UI.

## Features

- Start and stop `local-shell-mcp` for the current workspace.
- Show server output in a VS Code output channel.
- Check `/healthz`.
- Copy the local MCP URL.
- Copy a ChatGPT setup prompt.
- Configure public base URL and full-container behavior.

## Setup

1. Install the `local-shell-mcp` executable from a GitHub Release or with `pipx install local-shell-mcp`.
2. Install the `.vsix` asset from the same release.
3. Open a project folder.
4. Run **local-shell-mcp: Start Server**.
5. Copy the MCP URL or setup prompt from the command palette.

## Public ChatGPT access

For ChatGPT to access a local VS Code-launched server, expose it through HTTPS and configure the extension setting:

```text
local-shell-mcp.publicBaseUrl
```

Keep full-container mode disabled for direct host usage. Enable it only inside a disposable environment.
