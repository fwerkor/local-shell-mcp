# Development

This guide is for contributors working on `local-shell-mcp` itself.

## Local environment

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
uv run pre-commit install
```

Run checks:

```bash
uv run pre-commit run --all-files
uv run ruff check .
uv run pytest -q
```

Run a local MCP server without OAuth for development:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode mcp
```

Run the REST debug API:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode http
```

## Project layout

| Path | Purpose |
|---|---|
| `src/local_shell_mcp/main.py` | CLI parsing and server entrypoints. |
| `src/local_shell_mcp/tools.py` | MCP tool registration and public tool wrappers. |
| `src/local_shell_mcp/http_app.py` | REST debug API and HTTP routes. |
| `src/local_shell_mcp/settings.py` | Pydantic settings, environment variables, YAML config, safe settings dump. |
| `src/local_shell_mcp/auth.py` | Request auth middleware and ChatGPT-compatible MCP discovery handling. |
| `src/local_shell_mcp/oauth.py` | OAuth metadata, dynamic client registration, authorization, token issue/validation. |
| `src/local_shell_mcp/shell_ops.py` | Bounded shell execution and tmux-backed persistent sessions. |
| `src/local_shell_mcp/fs_ops.py` | Workspace path resolution and file operations. |
| `src/local_shell_mcp/search_ops.py` | Ripgrep search and compact tree views. |
| `src/local_shell_mcp/git_ops.py` | Git command wrappers. |
| `src/local_shell_mcp/remote.py` | Remote invite, worker bundle, long-poll protocol, and remote tool execution. |
| `src/local_shell_mcp/agent_bridge.py` | Agent bridge manifest loading, skill scanning, MCP probing, redaction. |
| `src/local_shell_mcp/agent_bridge_tools.py` | Agent bridge MCP tool registration and dynamic tool reloads. |
| `src/local_shell_mcp/agent_mcp.py` | External MCP client manager and tool/result normalization. |
| `src/local_shell_mcp/audit.py` | Audit log writer and trimming. |
| `src/local_shell_mcp/todo_ops.py` | Todo state persistence. |
| `tests/` | Unit and compatibility tests. |
| `scripts/` | Development, probing, generated-config, entrypoint, and release helper scripts. |
| `vscode-extension/` | VS Code extension source and packaging metadata. |

## Implementation notes

- The server can run as streamable HTTP MCP, REST debug API, or stdio MCP.
- The FastMCP app installs watchdogs so tool calls return bounded timeout payloads instead of hanging indefinitely.
- ChatGPT compatibility relies on unauthenticated MCP discovery by default; protected tool calls still use OAuth in public deployments.
- Tool results use a consistent `ok`, `message`, and `data` shape where possible.
- File tools avoid reading full binary files by default and enforce configured read/write limits.
- Remote workers run the same operation categories as local tools but execute on the worker machine and return results through the control server.
- Agent bridge config is treated as external input and redacts configured secrets from status and error payloads.

## Helper scripts

`scripts/` contains small entrypoints for development, generated examples, Docker startup, release packaging, and endpoint checks. Keep this section in sync whenever adding, renaming, or deleting a script.

| Script | Purpose | Typical usage |
|---|---|---|
| `scripts/dev-mcp.sh` | Start the MCP server in local development mode with auth disabled. | `uv run scripts/dev-mcp.sh` |
| `scripts/dev-http.sh` | Start the REST debug API in local development mode with auth disabled. | `uv run scripts/dev-http.sh` |
| `scripts/test-rest.sh` | Smoke-test the REST debug API. Requires a server from `scripts/dev-http.sh` or `local-shell-mcp --mode http`. | `BASE=http://127.0.0.1:8765 scripts/test-rest.sh` |
| `scripts/probe-mcp.py` | Probe a public streamable HTTP MCP endpoint. It checks unauthenticated discovery and, with `--pin`, an authenticated tool call. | `uv run python scripts/probe-mcp.py https://your-public-host.example.com --pin "$LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN"` |
| `scripts/generate-config-examples.py` | Generate `.env.example` and `config.example.yaml` from `src/local_shell_mcp/config_registry.py`. Use `--check` in tests/CI to detect drift. | `uv run python scripts/generate-config-examples.py --check` |
| `scripts/docker-entrypoint.sh` | Docker image entrypoint. It prepares workspace ownership, credential persistence, and final process user before launching the server. | Invoked by `Dockerfile`; do not run directly on the host. |
| `scripts/pyinstaller-entry.py` | Thin Python entrypoint for PyInstaller release assets. | Used by the release workflow. |

The old standalone Cloudflare tunnel launcher was removed. Use the Docker Compose `cloudflared` sidecar profile documented in [INSTALL.md](INSTALL.md) instead.

## MCP endpoint probe

You can verify a local MCP endpoint with a standard MCP client:

```python
import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client("http://127.0.0.1:8765/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])

anyio.run(main)
```

The repository also includes:

```bash
python scripts/probe-mcp.py https://your-public-host.example.com --pin "$LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN"
```

## Docker image and entrypoint

The Docker image is intended to be the safest default runtime because it keeps the model-controlled tools inside a container. The entrypoint prepares workspace permissions and, when enabled, persists common developer credential locations into `/persist/credentials`.

The Docker entrypoint normally runs the server as `agent` after preparing `/workspace` permissions, even when `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` disables built-in workspace and command restrictions. The `agent` user has passwordless sudo for commands that intentionally need root. Set `DOCKER_RUN_AS_ROOT=true` only when the MCP server process itself must run as root in a disposable container or VM.

## Release assets

The repository contains GitHub Actions workflows for CI and release builds. Release assets include Docker images, Python package artifacts, standalone executables, and the VS Code extension package.

Before cutting a release, run:

```bash
uv run pre-commit run --all-files
uv run pytest -q
```

Also test the Docker image and at least one MCP connection path before publishing.

## VS Code extension development

The extension source lives under `vscode-extension/`.

```bash
cd vscode-extension
npm install
npm run compile
```

See the extension README and guide in that directory for user-facing behavior.
