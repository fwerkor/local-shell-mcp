# Standalone binary runtime

Release binaries run `local-shell-mcp` without Docker and without a Python environment. Use this runtime when Docker is unavailable or when a dedicated VM, container host, lab server, or restricted user account already provides the safety boundary.

This is a runtime choice. ChatGPT access is configured separately through an HTTPS `/mcp` endpoint.

## Release artifacts

GitHub Releases build self-contained executables for common platforms:

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

Each archive contains the executable, README, license, and a short quickstart file.

## Install

1. Download the archive for your platform from GitHub Releases.
2. Extract it.
3. Put the executable on `PATH` or record its absolute path.
4. Run `local-shell-mcp --help` to verify that the binary starts.

Linux and macOS usually require the executable bit:

```bash
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Windows users should run `local-shell-mcp.exe` from PowerShell or configure the containing directory in `PATH`.

## Minimal local run

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

In another terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Public HTTP MCP run

For ChatGPT or a public HTTP MCP client, set these categories of configuration:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | Directory controlled by tools |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | Local bind address and port |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Public HTTPS origin, without `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Use `oauth` for public deployments |
| OAuth PIN and JWT secret settings | Required for public OAuth authorization |

Expose the local HTTP port through a reverse proxy or tunnel. The public endpoint is:

```text
https://your-public-host.example.com/mcp
```

## YAML config

A YAML config can hold non-secret runtime defaults:

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

Run:

```bash
local-shell-mcp --config /path/to/config.yaml
```

Environment variables with the `LOCAL_SHELL_MCP_` prefix override YAML values.

## Host toolchain responsibility

The binary packages the Python application, not every developer tool. MCP tools call programs available on the host.

Install what your tasks need:

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; Linux releases already include a static tmux helper |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

If you do not want to maintain this host toolchain, use Docker Compose.

## Long-running service

For a persistent public deployment, run the binary under your operating system's process supervisor. Keep these practices:

- Use a dedicated low-privilege OS account.
- Use a dedicated workspace directory.
- Store sensitive values outside world-readable files.
- Restart automatically on failure.
- Check `/healthz` after each restart.
- Keep logs available for troubleshooting.

## Updates

1. Download the new release archive for your platform.
2. Verify checksums if desired.
3. Replace the executable.
4. Restart the process manager.
5. Check `/healthz`.
6. Ask the client to run `environment_info` before continuing work.

## Safety notes

The binary runs with the privileges of its operating-system user. For public deployments, use a dedicated low-privilege user, a dedicated workspace, and a VM/container boundary when possible.

Do not set `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` for a binary running directly on your personal host. That setting is intended for disposable containers or VMs.
