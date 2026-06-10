# local-shell-mcp

`local-shell-mcp` lets ChatGPT and other MCP clients work inside a controlled local workspace. It exposes shell, filesystem, Git, search, todo, audit, and remote-worker tools through a ChatGPT-compatible MCP server with OAuth support.

Use it when you want an AI coding agent to inspect a project, edit files, run tests, operate Git, or delegate work to another machine without giving it direct access to your host.

## What you get

- A ChatGPT custom connector endpoint at `/mcp`, with built-in OAuth for public deployments.
- Read-only `search` and `fetch` tools for regular ChatGPT connectors and Deep Research-style use.
- Full coding-agent tools for ChatGPT Developer Mode and other full MCP clients.
- A Docker image with Python, Node.js, Go, Rust, Java, Ruby, PHP, Perl, Lua, R, C/C++ build tools, Git, tmux, ripgrep, LibreOffice, and common document/data-processing libraries.
- Optional remote worker mode: invite a machine behind NAT, a firewall, or an HPC login node to connect back over outbound HTTPS and expose matching `remote_*` tools.
- Optional agent capability bridge for externally synced MCP servers and skills.
- Audit logging under `/workspace/.local-shell-mcp/audit.jsonl`.
- A VS Code extension that starts the server for the current workspace and copies the connector setup details.

## Start here

For most users, the Docker Compose flow is the safest starting point:

```bash
cp .env.example .env
```

Edit `.env` and set the public URL, OAuth PIN, and JWT secret. Then start the service:

```bash
mkdir -p workspaces/default
docker compose up -d
```

Expose the server through HTTPS, then add this MCP endpoint in ChatGPT:

```text
https://your-public-host.example.com/mcp
```

For full shell, filesystem, and Git tools, enable ChatGPT Developer Mode before adding the custom MCP connector.

See [INSTALL.md](INSTALL.md) for Docker, binary, VS Code, and tunnel setup.

## Basic workflow

1. Start `local-shell-mcp` against a workspace you are willing to let the model control.
2. Connect ChatGPT or another MCP client to `/mcp`.
3. Ask the model to inspect the workspace, make edits, run tests, and show diffs.
4. Review changes before committing or pushing.
5. Watch the audit log when debugging tool calls.

Example prompt:

```text
Use local-shell-mcp to inspect this repository, run the tests, and summarize what you found before making any changes.
```

More examples are in [examples/chatgpt-prompts.md](examples/chatgpt-prompts.md).

## Documentation

- [INSTALL.md](INSTALL.md): installation, Docker Compose, Cloudflare Tunnel, VS Code, and binary deployments.
- [USAGE.md](USAGE.md): ChatGPT connector setup, CLI/configuration basics, remote workers, REST debug API, Git access, troubleshooting, and common workflows.
- [ENV.md](ENV.md): complete environment-variable reference for application, Docker entrypoint, and helper-script settings.
- [TOOLS.md](TOOLS.md): complete built-in MCP tool list and how tool groups behave.
- [DEVELOPMENT.md](DEVELOPMENT.md): local development, tests, release assets, project layout, and implementation notes.
- [OAUTH_SETUP.md](OAUTH_SETUP.md): compact OAuth setup checklist.
- [SECURITY.md](SECURITY.md): deployment safety guidance and threat model.
- [vscode-extension/README.md](vscode-extension/README.md): VS Code extension usage.

## Safety model

This project intentionally exposes powerful tools. Treat any connected model as able to read and modify the configured workspace, execute commands, use mounted credentials, and operate remote workers you invite.

Default safeguards include workspace path restrictions, timeout and output limits, default command/path denylists, audit logs, and OAuth for public connector use. `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` disables the built-in path and command denylists and should only be used in disposable containers or VMs.

Read [SECURITY.md](SECURITY.md) before exposing the service beyond localhost.

## License

MIT. See [LICENSE](LICENSE).
