<div align="center">

# local-shell-mcp

**A ChatGPT-ready MCP control plane for shell, files, browser automation, file links, and remote machines.**

[![Docs](https://img.shields.io/badge/docs-fwerkor.github.io%2Flocal--shell--mcp-7c3aed?logo=materialformkdocs&logoColor=white)](https://fwerkor.github.io/local-shell-mcp/)
[![CI](https://github.com/fwerkor/local-shell-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/fwerkor/local-shell-mcp/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/fwerkor/local-shell-mcp?sort=semver)](https://github.com/fwerkor/local-shell-mcp/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776ab?logo=python&logoColor=white)](https://github.com/fwerkor/local-shell-mcp)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed?logo=docker&logoColor=white)](https://github.com/fwerkor/local-shell-mcp/pkgs/container/local-shell-mcp)
[![License](https://img.shields.io/github/license/fwerkor/local-shell-mcp)](LICENSE)

[Documentation](https://fwerkor.github.io/local-shell-mcp/) · [Quickstart](https://fwerkor.github.io/local-shell-mcp/getting-started/quickstart/) · [Runtime choices](https://fwerkor.github.io/local-shell-mcp/guides/deployment/) · [ChatGPT connector](https://fwerkor.github.io/local-shell-mcp/getting-started/chatgpt-connector/) · [Tools](https://fwerkor.github.io/local-shell-mcp/reference/tools/) · [Releases](https://github.com/fwerkor/local-shell-mcp/releases)

</div>

---

`local-shell-mcp` gives ChatGPT Developer Mode and other MCP clients controlled access to a real execution environment. It exposes a dedicated workspace with shell, persistent shell, filesystem, search, patch, Playwright, audit, todo, public file links, and outbound remote-worker access. Git is handled through ordinary shell commands instead of a parallel wrapper API.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
  -> exposure: localhost, HTTPS proxy/tunnel, or stdio pipe
  -> client: ChatGPT or another MCP client
  -> controlled workspace at /workspace or configured root
  -> optional remote workers connected over outbound HTTP(S)
```

The intended safety boundary is the container or VM, not the host.

## Why use it

| Capability | What it enables |
|---|---|
| Real terminal access | Run tests, build projects, inspect logs, and debug with persistent shell sessions. |
| Workspace-aware file tools | Read, write, patch, search, and review files under a controlled root. |
| Git workflow support | Run the standard Git CLI through shell tools without a second, incomplete Git abstraction. |
| Browser automation | Extract page text, capture PNG/PDF evidence, or run a full Playwright script. |
| Remote workers | Control NAT, firewall, HPC, NPU, or lab machines that can only connect outward. |
| Agent Skills | Discover, load, and read reusable `SKILL.md` workflows through three fixed tools without changing the MCP tool list. |
| ChatGPT connector support | OAuth 2.1, `/mcp`, discovery controls, and ChatGPT-compatible tool schemas. |
| Safer operations | Workspace scoping, shell timeouts, output limits, environment filtering, audit logs, and secret scanning. |

## Quick start

Clone the repository and prepare configuration:

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
```

Set at least these values in `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

Start the server:

```bash
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Start the bundled Cloudflare Tunnel sidecar when you need public HTTPS access:

```bash
docker compose --profile tunnel up -d
```

The public MCP endpoint is:

```text
https://your-public-host.example.com/mcp
```

Full setup instructions are in the [documentation](https://fwerkor.github.io/local-shell-mcp/). Runtime choices are documented separately from client connections.

## Human interface

The same service now includes a human-facing OpenTUI with Files, Terminals, Todos, Audit, and Remotes screens. The browser interface is an authenticated xterm.js/PTY shell around that exact OpenTUI application rather than a separate dashboard.

Open the WebUI on the service origin:

```text
http://127.0.0.1:8765/ui
```

The WebUI uses the same OAuth flow as MCP. Its responsive terminal frame supports mouse interaction on the actual OpenTUI top bar and contextual footer actions, automatic PTY resizing, reconnects, fullscreen mode, and a cached Bing background with an animated fallback.

Standalone release executables embed the native OpenTUI runtime, while Docker images provide it inside the image. Start the service, then launch it without a human login prompt:

```bash
local-shell-mcp tui
```

Files is an LSM-native three-pane file manager for local and remote machines. It renders bounded PNG/JPEG/GIF/WebP thumbnails directly in OpenTUI and provides consistent file operations through the shared service API. Manual actions entered through either human interface are excluded from the MCP audit log; the Audit screen and terminal audit rail show model-originated MCP activity.

See the [human interface guide](https://fwerkor.github.io/local-shell-mcp/guides/human-interface/).

## ChatGPT setup

For full shell, filesystem, remote-worker, and Playwright tools, use ChatGPT Developer Mode or another full MCP client. ChatGPT is a client connection; choose and start a runtime first.

1. Expose the server through HTTPS.
2. Keep OAuth enabled.
3. Add the MCP endpoint: `https://your-public-host.example.com/mcp`.
4. Complete the OAuth authorization flow.
5. Start with a bounded task and inspect the audit log when needed.

Read the dedicated [ChatGPT connector guide](https://fwerkor.github.io/local-shell-mcp/getting-started/chatgpt-connector/).

## VS Code extension runtime

Release assets include `local-shell-mcp-vscode-<version>.vsix`. The extension is a runtime launcher for the current VS Code workspace. It starts the same server, checks `/healthz`, copies the MCP URL, and copies a ready-to-paste ChatGPT setup prompt.

Basic flow:

```text
Install executable -> install VSIX -> open a workspace -> Start Server -> copy MCP URL
```

For public ChatGPT access, expose the local server through an HTTPS tunnel and set `local-shell-mcp.publicBaseUrl` in VS Code settings. Keep `local-shell-mcp.allowFullContainer` disabled for direct host usage; enable it only inside disposable containers or VMs.

## Remote workers

Remote worker mode is enabled by default. Create a one-time invite on the control server, paste the generated command on a remote machine, then use the normal tools with their optional `machine` argument. Only worker administration retains `remote_*` names.

This is intended for:

- HPC login nodes or compute nodes behind firewalls.
- NPU/GPU servers without inbound connectivity.
- Lab machines that can make outbound HTTPS requests.
- Temporary build hosts or remote test environments.

See the [remote workers guide](https://fwerkor.github.io/local-shell-mcp/guides/remote-workers/).

## Agent Skills

Skills are discovered from three ordered sources: project-level `/workspace/.agents/skills`, the LSM-managed `/workspace/.local-shell-mcp/agent_config/skills`, and global `~/.config/agents/skills`. Higher-priority sources override lower-priority Skills with the same name, and symlinked Skill directories and files are supported.

This makes the universal Skills CLI layout work directly, for example `npx skills add owner/repo --agent universal -y`. Use `skills_list` to discover installed Skills, `skill_load` to load one instruction set, and `skill_read_file` to read a related file by the returned Skill-relative path. Changes are detected on the next call; no per-Skill MCP tools are registered and no client reconnect is required.

See the [Agent Skills guide](https://fwerkor.github.io/local-shell-mcp/guides/skills/).

## Tool surface

The public MCP surface includes:

- Shell and jobs: `run_shell_tool`, `run_python_tool`, persistent `shell_*`, and tracked `job_*` tools. Use `run_shell_tool` for Git CLI operations.
- Filesystem: `list_files`, `tree_view`, `glob_search`, `grep_search`, unified `read_file`, native-vision `view_image`, `write_file`, unified `edit_file`, `delete_file_or_dir`, and `apply_patch`.
- Transfer: `transfer_path` for files or directories across controller and worker endpoints.
- Browser: `browser_get_text_tool`, unified `browser_capture_tool`, and `playwright_run_script_tool`.
- File links: `create_file_link`, `list_file_links`, `revoke_file_link`.
- Remote workers: `remote_invite`, `remote_list_machines`, `remote_rename_machine`, and `remote_revoke_machine`; normal execution tools accept optional `machine`.
- Agent Skills: `skills_list`, `skill_load`, `skill_read_file`.
- Diagnostics: `environment_info` (including version information), `secret_scan`, `audit_tail`, `todo_read_tool`, and `todo_write_tool`.

The detailed tool reference, including purpose, inputs, returns, combinations, and notes for every tool, is available in the [docs](https://fwerkor.github.io/local-shell-mcp/reference/tools/).

## Security model

This project intentionally exposes powerful tools. Treat the connected model as having control of the container or VM.

Default protections include:

- Workspace scoping to `/workspace` unless full-container mode is explicitly enabled.
- Command timeouts, output limits, and concurrency limits.
- Default command/path denylists for host-control fragments.
- Shell subprocess environment filtering for service-side secrets.
- Audit logs at `/workspace/.local-shell-mcp/audit.jsonl`.
- Secret scanning helpers before commits and pushes.
- Tokenized file links with TTL/download limits and revocation.

Hard rules:

1. Do not mount `/var/run/docker.sock`.
2. Do not mount the host root filesystem.
3. Do not expose the service with `LOCAL_SHELL_MCP_AUTH_MODE=none` on a public network.
4. Do not put long-lived credentials in environment variables visible to the model.
5. Prefer single-repository deploy keys or short-lived tokens.
6. Run the service in a disposable container or VM.
7. Treat the `local-shell-mcp-credentials` Docker volume as sensitive.

For vulnerability reporting, read [SECURITY.md](SECURITY.md).

## Configuration

Copy [`.env.example`](.env.example) for the standard setup. The [configuration reference](https://fwerkor.github.io/local-shell-mcp/reference/configuration/) documents every environment variable and the optional YAML format for advanced deployments.

Important options:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Public HTTPS origin used by OAuth and ChatGPT. |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Use `oauth` for public deployments. |
| `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | Disable workspace restrictions only in disposable containers/VMs. |
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | Enable or disable remote worker control tools. |
| `LOCAL_SHELL_MCP_UI_ENABLED` | Mount or disable the shared OpenTUI/WebUI human interface. |
| `LOCAL_SHELL_MCP_UI_PATH` | WebUI mount path on the same service; default `/ui`. |
| `LOCAL_SHELL_MCP_UI_WALLPAPER` | Select `bing`, `aurora`, or `none` for the browser shell. |
| `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | Environment variables removed from spawned shell processes. |
| `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | Enable tokenized file download links. |

## Development

Install development dependencies and run checks:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

Build the VS Code extension:

```bash
npm --prefix vscode-extension install
npm --prefix vscode-extension run compile
```

Contribution workflow is documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## Project documents

- [Documentation site](https://fwerkor.github.io/local-shell-mcp/)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Support guide](SUPPORT.md)
- [OAuth setup](OAUTH_SETUP.md)
- [License](LICENSE)
