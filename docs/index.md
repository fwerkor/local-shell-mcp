<div class="hero-shell" markdown>
<span class="hero-eyebrow">ChatGPT-compatible MCP control plane</span>

# local-shell-mcp

Give your AI assistant a controlled shell, a real workspace, Git, browser automation, file sharing, and remote-worker access without leaving the chat.

<div class="hero-actions" markdown>
[Get started](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Connect ChatGPT](getting-started/chatgpt-connector.md){ .hero-action .hero-action--secondary }
[Remote workers](guides/remote-workers.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Real coding environment
Run tests, inspect repositories, patch files, operate Git, and keep an audit trail from one MCP endpoint.
</div>

<div class="feature-card" markdown>
### Remote machine control
Attach NAT, firewall, or HPC machines through outbound worker connections without opening SSH ports.
</div>

<div class="feature-card" markdown>
### ChatGPT-ready security
OAuth, workspace scoping, configurable shell environment filtering, secret scanning, and tokenized file links.
</div>
</div>

## What it provides

`local-shell-mcp` exposes a controlled local or container workspace to ChatGPT and other MCP clients. It provides shell, persistent shell, filesystem, search, patch, git-through-shell, Playwright, audit, tokenized file-link, and remote-worker tools through a ChatGPT-compatible MCP server with OAuth support.

Use it when the AI needs to inspect a repository, run tests, edit files, operate Git, collect browser evidence, or control a remote machine that can only connect outbound to the control server.

## Main paths

- [Quickstart](getting-started/quickstart.md) for Docker Compose setup.
- [ChatGPT connector](getting-started/chatgpt-connector.md) for adding the MCP endpoint.
- [Remote workers](guides/remote-workers.md) for NAT/HPC-style machines.
- [Tools reference](reference/tools.md) for the public tool surface.
