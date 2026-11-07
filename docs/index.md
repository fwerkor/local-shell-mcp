<div class="hero-shell" markdown>
<span class="hero-eyebrow">Self-hosted AI workspace · MCP control plane</span>

# local-shell-mcp

Chat, projects, files, terminals, remote machines and AI tools in one self-hosted interface. Connect external MCP clients when you need them.

<div class="hero-actions" markdown>
[Get started](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Tools reference](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Real coding environment
Run tests, inspect repositories, patch files, operate Git, and keep an audit trail from one MCP endpoint.
</div>

<div class="feature-card" markdown>
### Unified web workspace
Use the built-in chat and project history alongside Controller files, terminals, desktop, sessions, remotes and audit. External MCP clients stay optional.
</div>

<div class="feature-card" markdown>
### Remote machine control
Attach NAT, firewall, or HPC machines through outbound worker connections without opening SSH ports.
</div>
</div>

## What it provides

`local-shell-mcp` provides a unified self-hosted AI workspace and an MCP server for external clients. It provides shell, persistent shell, filesystem, search, patch, Git, Playwright, audit, durable logical sessions with optional Goal plans, tokenized file-link, and remote-worker tools through authenticated MCP endpoints.

Use it when the AI needs to inspect a repository, run tests, edit files, operate Git, collect browser evidence, produce downloadable artifacts, or control a remote machine that can only connect outbound to the control server.

## Architecture

```text
Runtime layer: Docker / VS Code extension / binary / Python / stdio
Exposure layer: localhost / HTTPS proxy / tunnel / stdio pipe
Client layer: unified WebUI / Gemini / ChatGPT / generic MCP client
Controlled workspace: /workspace or configured workspace root
Optional remote workers: outbound machine connections
```

The intended isolation boundary is the container or VM running the service.

## Start by scenario

| Scenario | Start here | Why |
|---|---|---|
| Primary browser workspace | [Unified web workspace](getting-started/web-workspace.md) | Chat, projects and LSM control pages with a shared login |
| First Controller deployment | [Quickstart](getting-started/quickstart.md) | Recommended source checkout, OAuth and the first browser session |
| Choosing the runtime layer | [Runtime choices](guides/deployment.md) | Explains Docker, VS Code, binary, Python, and stdio as separate runtime options |
| Connecting Gemini Spark | [Gemini Custom Apps](getting-started/gemini-spark.md) | Eligibility, HTTPS MCP URL, OAuth and testing |
| Adding ChatGPT as a client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, first safe prompt, tool discovery |
| Adding LSM to DeepSeek Harness | [DeepSeek Harness plugin](clients/deepseek-harness.md) | Install this repository as a DSH bundle while keeping the complete LSM tool and remote-worker surface |
| Running from VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime and host-safety notes |
| Learning how to operate the toolset | [Usage patterns](guides/usage-patterns.md) | Prompt templates and tool-choice guidance |
| Understanding every tool | [Tools reference](reference/tools.md) | Detailed purpose, inputs, returns, combinations, and notes for every tool |
| Connecting an HPC, NPU/GPU, or server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow and remote tool usage |
| Sharing generated files | [File links](guides/file-links.md) | Tokenized download URLs with TTL and revocation |
| Hardening a deployment | [Security](security.md) | Isolation, OAuth, workspace scope, and audit logs |

## Main tool families

| Family | Examples | Use for |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection and precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Reviewable source-control workflows |
| Sessions and goals | `session_manage`, `plan_manage` | Durable task handoff, progress reports, optional Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI checks, screenshots, rendered docs, page text |
| File links | `link_create`, `link_revoke` | Downloading generated artifacts from chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Machines behind NAT, firewalls, or cluster login flows |

## Typical workflows

### Coding in the web workspace

1. Start an LSM Controller and the optional [unified web workspace](getting-started/web-workspace.md).
2. Open `/ui` and sign in using the LSM identity.
3. Configure a model endpoint and open a new conversation.
4. Ask the model to inspect the repository and run read-only checks first.
5. Let it patch files, run tests, review diffs, commit, and push when approved.
6. Review the audit log when the task involves file links or remote systems.

### Remote HPC or accelerator host

1. Create a one-time remote worker invite.
2. Paste the generated command on the remote host.
3. Use normal tools with `machine`; run Git through `run_shell` and transfer paths with `remote_transfer`.
4. Revoke the worker after the task.

### Artifact generation

1. Let the AI generate a file under `/workspace`.
2. Create a tokenized file link with TTL/download limits.
3. Share the link in chat.
4. Revoke it when done.

## Language

This site is built with the native MkDocs i18n plugin. Use the language selector in the header to switch between English and translated pages. Pages without a translated version fall back to English.
