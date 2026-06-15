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

Use it when the AI needs to inspect a repository, run tests, edit files, operate Git, collect browser evidence, produce downloadable artifacts, or control a remote machine that can only connect outbound to the control server.

## Architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint, usually Cloudflare Tunnel, Nginx, Caddy, or another reverse proxy
  -> local-shell-mcp server
  -> controlled workspace at /workspace
  -> optional remote workers connected through outbound polling
```

The intended isolation boundary is the container or VM running the service. Do not mount host-control primitives such as the Docker socket unless the whole environment is disposable.

## Main paths

| Need | Start here |
|---|---|
| First deployment | [Quickstart](getting-started/quickstart.md) |
| Add ChatGPT | [ChatGPT connector](getting-started/chatgpt-connector.md) |
| Public HTTPS deployment | [Deployment](guides/deployment.md) |
| Connect an HPC/NPU/server node | [Remote workers](guides/remote-workers.md) |
| Share generated files | [File links](guides/file-links.md) |
| Understand every tool | [Tools reference](reference/tools.md) |
| Harden a deployment | [Security](security.md) |

## Typical workflows

### Coding with ChatGPT

1. Start `local-shell-mcp` in a dedicated workspace.
2. Add the public `/mcp` endpoint to ChatGPT.
3. Ask ChatGPT to inspect the repository, run tests, patch code, commit changes, and push.
4. Review the audit log when the task involves credentials or remote systems.

### Remote HPC or accelerator host

1. Create a one-time remote worker invite.
2. Paste the generated command on the remote host.
3. Use `remote_run_shell_tool`, `remote_read_file`, `remote_push_file`, and remote Git tools from ChatGPT.
4. Revoke the worker after the task.

### Artifact generation

1. Let the AI generate a file under `/workspace`.
2. Create a tokenized file link with TTL/download limits.
3. Share the link in chat.
4. Revoke it when done.

## Language

This site includes English documentation and a Chinese section under [中文](zh/index.md). The top-right language selector points to the main language landing pages.
