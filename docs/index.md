<div class="hero-shell" markdown>
<span class="hero-eyebrow">ChatGPT-compatible MCP control plane</span>

# local-shell-mcp

Give your AI assistant a controlled shell, a real workspace, Git, browser automation, file sharing, and remote-worker access without leaving the chat.

<div class="hero-actions" markdown>
[Get started](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Compare deployments](guides/deployment.md){ .hero-action .hero-action--secondary }
[Tools reference](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Real coding environment
Run tests, inspect repositories, patch files, operate Git, and keep an audit trail from one MCP endpoint.
</div>

<div class="feature-card" markdown>
### Multiple deployment paths
Run it with Docker Compose, a tunnel sidecar, the VS Code extension, a standalone binary, `pipx`, source install, or stdio mode.
</div>

<div class="feature-card" markdown>
### Remote machine control
Attach NAT, firewall, or HPC machines through outbound worker connections without opening SSH ports.
</div>
</div>

## What it provides

`local-shell-mcp` exposes a controlled local or container workspace to ChatGPT and other MCP clients. It provides shell, persistent shell, filesystem, search, patch, Git, Playwright, audit, todo, tokenized file-link, and remote-worker tools through a ChatGPT-compatible MCP server with OAuth support.

Use it when the AI needs to inspect a repository, run tests, edit files, operate Git, collect browser evidence, produce downloadable artifacts, or control a remote machine that can only connect outbound to the control server.

## Architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint, usually a tunnel or reverse proxy
  -> local-shell-mcp server
  -> controlled workspace at /workspace
  -> optional remote workers connected through outbound polling
```

The intended isolation boundary is the container or VM running the service.

## Start by scenario

| Scenario | Start here | Why |
|---|---|---|
| First public ChatGPT deployment | [Quickstart](getting-started/quickstart.md) | Docker Compose path with OAuth and `/mcp` setup |
| Choosing between Docker, VS Code, binary, source, or stdio | [Deployment and installation methods](guides/deployment.md) | Side-by-side method comparison and proxy requirements |
| Adding ChatGPT | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, first safe prompt, tool discovery |
| Running from VS Code | [VS Code extension](guides/vscode.md) | Extension install, settings, public URL behavior |
| Learning how to operate the toolset | [Usage patterns](guides/usage-patterns.md) | Prompt templates and tool-choice guidance |
| Understanding every tool | [Tools reference](reference/tools.md) | Complete catalog of local and remote MCP tools |
| Connecting an HPC, NPU/GPU, or server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow and remote tool usage |
| Sharing generated files | [File links](guides/file-links.md) | Tokenized download URLs with TTL and revocation |
| Hardening a deployment | [Security](security.md) | Isolation, OAuth, workspace scope, and audit logs |

## Main tool families

| Family | Examples | Use for |
|---|---|---|
| Shell and Python | `run_shell_tool`, `run_python_tool`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `tree_view`, `grep_search`, `read_file`, `apply_patch` | Repository inspection and precise edits |
| Git | `git_status_tool`, `git_diff_tool`, `git_commit_tool`, `git_push_tool` | Reviewable source-control workflows |
| Browser | `browser_screenshot_tool`, `browser_get_text_tool`, `browser_eval_tool` | UI checks, screenshots, rendered docs, page text |
| File links | `create_file_link`, `revoke_file_link` | Downloading generated artifacts from chat |
| Remote workers | `remote_invite`, `remote_run_shell_tool`, `remote_push_file` | Machines behind NAT, firewalls, or cluster login flows |

## Typical workflows

### Coding with ChatGPT

1. Start `local-shell-mcp` in a dedicated workspace.
2. Add the public `/mcp` endpoint to ChatGPT.
3. Ask ChatGPT to inspect the repository and run read-only checks first.
4. Let it patch files, run tests, review diffs, commit, and push when approved.
5. Review the audit log when the task involves file links or remote systems.

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

This site is built with the native MkDocs i18n plugin. Use the language selector in the header to switch between English and translated pages. Pages without a translated version fall back to English.
