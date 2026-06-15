<div align="center">

# local-shell-mcp

**A ChatGPT-ready MCP control plane for shell, files, Git, browser automation, file links, and remote machines.**

[![Docs](https://img.shields.io/badge/docs-fwerkor.github.io%2Flocal--shell--mcp-7c3aed?logo=materialformkdocs&logoColor=white)](https://fwerkor.github.io/local-shell-mcp/)
[![CI](https://github.com/fwerkor/local-shell-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/fwerkor/local-shell-mcp/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/fwerkor/local-shell-mcp?sort=semver)](https://github.com/fwerkor/local-shell-mcp/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776ab?logo=python&logoColor=white)](https://github.com/fwerkor/local-shell-mcp)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed?logo=docker&logoColor=white)](https://github.com/fwerkor/local-shell-mcp/pkgs/container/local-shell-mcp)
[![License](https://img.shields.io/github/license/fwerkor/local-shell-mcp)](LICENSE)

[Documentation](https://fwerkor.github.io/local-shell-mcp/) · [Quickstart](https://fwerkor.github.io/local-shell-mcp/getting-started/quickstart/) · [Runtime choices](https://fwerkor.github.io/local-shell-mcp/guides/deployment/) · [ChatGPT connector](https://fwerkor.github.io/local-shell-mcp/getting-started/chatgpt-connector/) · [Tools](https://fwerkor.github.io/local-shell-mcp/reference/tools/) · [Releases](https://github.com/fwerkor/local-shell-mcp/releases)

</div>

---

`local-shell-mcp` gives ChatGPT Developer Mode and other MCP clients controlled access to a real execution environment. It exposes a dedicated workspace with shell, persistent shell, filesystem, search, patch, Git, Playwright, audit, todo, public file links, and outbound remote-worker tools.

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
| Git workflow support | Clone, diff, commit, push, and inspect history from inside the AI-assisted environment. |
| Browser automation | Capture screenshots, extract page text, evaluate JavaScript, and save PDFs with Playwright. |
| Remote workers | Control NAT, firewall, HPC, NPU, or lab machines that can only connect outward. |
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

## ChatGPT setup

For full shell, filesystem, Git, and Playwright tools, use ChatGPT Developer Mode or another full MCP client. ChatGPT is a client connection; choose and start a runtime first.

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

Remote worker mode is enabled by default. Create a one-time invite on the control server, paste the generated command on a remote machine, and use `remote_*` tools without opening SSH ports.

This is intended for:

- HPC login nodes or compute nodes behind firewalls.
- NPU/GPU servers without inbound connectivity.
- Lab machines that can make outbound HTTPS requests.
- Temporary build hosts or remote test environments.

See the [remote workers guide](https://fwerkor.github.io/local-shell-mcp/guides/remote-workers/).

## Tool surface

The public MCP surface includes:

- Shell: `run_shell_tool`, `run_python_tool`, `shell_start`, `shell_send`, `shell_read`, `shell_kill`, `shell_list`.
- Filesystem: `list_files`, `tree_view`, `glob_search`, `grep_search`, `read_file`, `read_many_files`, `write_file`, `edit_file`, `multi_edit_file`, `delete_file_or_dir`, `apply_patch`.
- Git: `git_clone_tool`, `git_status_tool`, `git_diff_tool`, `git_log_tool`, `git_checkout_tool`, `git_fetch_tool`, `git_pull_tool`, `git_add_tool`, `git_commit_tool`, `git_push_tool`, `git_show_tool`, `git_reset_tool`, `secret_scan`.
- Browser: `playwright_install_tool`, `browser_screenshot_tool`, `browser_get_text_tool`, `browser_eval_tool`, `browser_pdf_tool`, `playwright_run_script_tool`.
- File links: `create_file_link`, `list_file_links`, `revoke_file_link`.
- Remote workers: `remote_invite`, `remote_list_machines`, `remote_run_shell_tool`, `remote_*` filesystem/Git/browser/transfer tools.
- Diagnostics: `environment_info`, `audit_tail`, `todo_read_tool`, `todo_write_tool`.

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

Common settings are documented in [`config.example.yaml`](config.example.yaml), [`.env.example`](.env.example), and the [configuration reference](https://fwerkor.github.io/local-shell-mcp/reference/configuration/).

Important options:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Public HTTPS origin used by OAuth and ChatGPT. |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Use `oauth` for public deployments. |
| `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | Disable workspace restrictions only in disposable containers/VMs. |
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | Enable or disable remote worker control tools. |
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
