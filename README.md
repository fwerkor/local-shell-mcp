# local-shell-mcp

`local-shell-mcp` is an OAuth-enabled MCP server for giving ChatGPT Developer Mode,
Codex-like agents, or other MCP clients controlled access to a dedicated local
container.

The container exposes shell, filesystem, Git, todo, and diagnostic
tools inside `/workspace`. The intended safety boundary is the container, not the
host.

```text
ChatGPT / MCP client
  -> public HTTPS endpoint, commonly Cloudflare Tunnel
  -> local-shell-mcp container
  -> /workspace mounted volume
```

## Features

- Built-in OAuth 2.1 flow for ChatGPT custom connectors.
- Streamable HTTP MCP endpoint at `/mcp`.
- Read-only `search` and `fetch` tools for regular ChatGPT connectors.
- Full coding-agent tools for ChatGPT Developer Mode / Full MCP clients.
- Remote worker mode is enabled by default: create a one-time invite, paste one command on a remote HPC/NPU/server machine, and use that machine through `remote_*` tools without SSH.
- Docker image with Python, common data/document/file-processing packages
  including PDF, Word, PowerPoint, Excel, and LibreOffice conversion support,
  Node.js, Go, Rust, Java, Ruby, PHP, Perl, Lua, R, C/C++ build tools, Git,
  tmux, and ripgrep.
- Audit log at `/workspace/.local-shell-mcp/audit.jsonl`.


## VS Code extension

`local-shell-mcp` also ships a VS Code extension package, `local-shell-mcp-vscode-<version>.vsix`, attached to GitHub Releases. The extension is a thin wrapper around the server: it starts `local-shell-mcp` for the current VS Code workspace, shows an output channel, checks `/healthz`, copies the MCP URL, and copies a ready-to-paste ChatGPT setup prompt.

Basic usage:

1. Install the `local-shell-mcp` executable from GitHub Releases or with `pipx install local-shell-mcp`.
2. Install the `.vsix` file from the same release in VS Code.
3. Open a project folder and run **local-shell-mcp: Start Server** from the command palette.
4. Run **local-shell-mcp: Copy MCP URL** and paste the URL into ChatGPT's MCP connector setup.
5. Run **local-shell-mcp: Copy ChatGPT Setup Prompt** when starting a coding session.

For public ChatGPT access, expose the local server through an HTTPS tunnel and set `local-shell-mcp.publicBaseUrl` in VS Code settings. Keep `local-shell-mcp.allowFullContainer` disabled for direct host usage; enable it only inside a disposable container.

## Tools

Read-only connector tools:

- `search`
- `fetch`

Shell:

- `run_shell_tool`
- `run_python_tool`
- `shell_start`
- `shell_send`
- `shell_read`
- `shell_kill`
- `shell_list`

Filesystem:

- `list_files`
- `tree_view`
- `glob_search`
- `grep_search`
- `read_file`
- `read_many_files`
- `write_file`
- `edit_file`
- `multi_edit_file`
- `delete_file_or_dir`
- `apply_patch`

Git:

- `git_clone_tool`
- `git_status_tool`
- `git_diff_tool`
- `git_log_tool`
- `git_checkout_tool`
- `git_fetch_tool`
- `git_pull_tool`
- `git_add_tool`
- `git_commit_tool`
- `git_push_tool`
- `git_show_tool`
- `git_reset_tool`
- `secret_scan`

Remote worker control and near-parity tools:

- `remote_invite`
- `remote_list_machines`
- `remote_revoke_machine`
- `remote_rename_machine`
- `remote_environment_info`
- `remote_run_shell_tool`
- `remote_run_python_tool`
- `remote_shell_start` / `remote_shell_send` / `remote_shell_read` / `remote_shell_kill` / `remote_shell_list`
- `remote_list_files` / `remote_tree_view` / `remote_glob_search` / `remote_grep_search`
- `remote_read_file` / `remote_read_many_files` / `remote_write_file` / `remote_edit_file` / `remote_multi_edit_file` / `remote_delete_file_or_dir` / `remote_apply_patch`
- `remote_git_clone_tool` / `remote_git_status_tool` / `remote_git_diff_tool` / `remote_git_log_tool` / `remote_git_checkout_tool` / `remote_git_fetch_tool` / `remote_git_pull_tool` / `remote_git_add_tool` / `remote_git_commit_tool` / `remote_git_push_tool` / `remote_git_show_tool` / `remote_git_reset_tool`

Diagnostics and todo:

- `environment_info`
- `audit_tail`
- `todo_read_tool`
- `todo_write_tool`

## Security

This project intentionally exposes powerful tools. Treat the container as
controlled by the connected model.

Default protections:

- Paths are restricted to `/workspace` unless `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true`.
- Commands have timeout and output limits.
- Sensitive path fragments are denied by default.
- Host-control fragments such as `/var/run/docker.sock` are denied by default.
- Audit logs are written to `/workspace/.local-shell-mcp/audit.jsonl`.
- Docker deployments persist GitHub CLI, Git HTTPS, GitCode, SSH, `.netrc`, and GPG credentials in `/persist/credentials` by default.

When `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true`, the server intentionally gives
the AI full control of the container: path and command denylists are disabled,
the Docker entrypoint runs the server as root, and the `agent` user can use
passwordless `sudo`. Use this only for disposable containers or VMs.

Hard rules:

1. Do not mount `/var/run/docker.sock`.
2. Do not mount the host root filesystem.
3. Do not expose the service with `LOCAL_SHELL_MCP_AUTH_MODE=none`.
4. Do not put long-lived GitHub PATs in environment variables visible to the model.
5. Prefer a single-repository deploy key or short-lived GitHub App token.
6. Run this in a disposable container or VM.
7. Treat the `local-shell-mcp-credentials` Docker volume as sensitive. It may contain access tokens and private keys.

## Quick Start

Copy the example environment file and edit it:

```bash
cp .env.example .env
```

Important values:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

Run the published Docker image:

```bash
mkdir -p workspaces/default
docker compose up -d
```

The Compose file persists `/workspace` and also creates a separate
`local-shell-mcp-credentials` volume for developer login state. Docker
deployments link common Git, GitHub CLI, SSH, `.netrc`, and GPG paths into
`/persist/credentials` on startup, so GitHub and GitCode authentication survives
image updates and container recreation. Set
`LOCAL_SHELL_MCP_PERSISTENT_CREDENTIALS=false` for a fully disposable
authentication state.

Download a Docker-free all-in-one executable from the GitHub release page when you do not want to run Docker. Release assets are built for Linux, macOS, and Windows on x86_64 and ARM64/aarch64. Start it directly:

```bash
./local-shell-mcp --mode mcp
```

On Windows PowerShell:

```powershell
.\local-shell-mcp.exe --mode mcp
```

For binary deployments, set `LOCAL_SHELL_MCP_WORKSPACE_ROOT` to the directory you want the tool to control. The binary includes the Python server and default OAuth dependencies, but not system tools such as Git, tmux, shells, compilers, or LibreOffice; those are taken from the host system.

## CLI Usage

The executable uses an `argparse` CLI. Running `local-shell-mcp` without a
subcommand starts the server:

```text
local-shell-mcp [--mode {mcp,http,stdio}] [--config PATH] [--remote | --no-remote]
```

Server options:

- `--mode {mcp,http,stdio}` overrides `LOCAL_SHELL_MCP_MODE`.
- `--config PATH` sets `LOCAL_SHELL_MCP_CONFIG` before loading settings.
- `--remote` enables remote worker routes and tools.
- `--no-remote` disables remote worker routes and tools.

Remote workers use the `worker` subcommand:

```text
local-shell-mcp worker --server URL --invite TOKEN [--name NAME] [--workdir PATH] [--persist]
```

Use `local-shell-mcp --help` or `local-shell-mcp worker --help` to print the
current parser help.

Start the Cloudflare Tunnel sidecar too:

```bash
docker compose --profile tunnel up -d
```

Check the service:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

If the container cannot write `/workspace/.local-shell-mcp`, fix the host
workspace ownership:

```bash
sudo mkdir -p workspaces/default/.local-shell-mcp
sudo chown -R 10001:10001 workspaces/default
docker compose --profile tunnel restart local-shell-mcp
```

## Cloudflare Tunnel

The bundled Compose file has a `cloudflared` sidecar profile:

```yaml
cloudflared:
  image: cloudflare/cloudflared:latest
  command: tunnel --no-autoupdate run --token ${CLOUDFLARE_TUNNEL_TOKEN}
```

Create a tunnel in Cloudflare Zero Trust, add a Public Hostname, and point it to:

```text
http://local-shell-mcp:8765
```

Put the tunnel token in `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=...
```

Then run:

```bash
docker compose --profile tunnel up -d
```

The public MCP endpoint should be:

```text
https://your-public-host.example.com/mcp
```

## ChatGPT Setup

For full shell, filesystem, and Git tools, enable ChatGPT Developer
Mode:

1. Open ChatGPT settings.
2. Go to Connectors.
3. Enable Developer Mode under Advanced.
4. Add a custom MCP connector.
5. Use `https://your-public-host.example.com/mcp`.
6. Complete the OAuth flow using `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`.
7. Refresh the connector tool list if you have changed the server.

Regular ChatGPT connectors and Deep Research expect read-only `search` and
`fetch` tools. This project exposes those too, but write/execute actions require
Developer Mode / Full MCP.

After connecting, test with:

```text
Use local-shell-mcp to run pwd and tell me the output.
```

Watch server-side activity:

```bash
docker compose exec local-shell-mcp tail -f /workspace/.local-shell-mcp/audit.jsonl
```

A successful tool call should produce audit events such as `run_shell_start` and
`run_shell_end`.

## Remote Worker Mode

Remote worker mode is enabled by default. It lets machines behind NAT, firewalls,
or restricted HPC login environments connect back to the public control server
using outbound HTTP(S). The remote machine does not need an inbound port or SSH
access from the MCP client.

The normal local tools keep their original behavior. Remote tools use the same
shape and add a required `machine` argument, for example:

```text
run_shell_tool(command="pwd")
remote_run_shell_tool(machine="npu-4card", command="pwd")
```

Create a one-time invite from ChatGPT or any MCP client:

```text
Use local-shell-mcp remote_invite with name=npu-4card and workdir=/home/cyh/FrameDiff.
```

The tool returns a pasteable command like:

```bash
curl -fsSL https://your-public-host.example.com/join | bash -s -- \
  --invite lsmcp_inv_xxxxx \
  --name npu-4card \
  --workdir /home/cyh/FrameDiff
```

Paste that command on the remote machine. The join script downloads a worker
bundle from the control server at `/remote/worker-bundle.tgz`, so the remote side
uses the same code snapshot as the control server and does not need GitHub or
PyPI access. The worker registers once, exchanges the invite for a worker token,
and then long-polls the control server for jobs. The default mode is foreground
and temporary; press `Ctrl-C` on the remote machine to disconnect. Add
`--background` to the generated command for a simple `nohup` background worker.
`--persist` is accepted for future user-service installation support.

If `local-shell-mcp` is already installed on the remote machine, the equivalent
foreground worker command is:

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --invite lsmcp_inv_xxxxx \
  --name npu-4card \
  --workdir /home/cyh/FrameDiff
```

After it connects, ask ChatGPT to list machines:

```text
Use local-shell-mcp remote_list_machines.
```

Then use the near-parity remote tool set, such as `remote_run_shell_tool`,
`remote_read_file`, `remote_write_file`, `remote_grep_search`,
`remote_git_pull_tool`, or `remote_shell_start`.

Remote mode settings:

| Variable | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | Enable remote worker routes and MCP tools |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | One-time invite lifetime |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | Long-poll heartbeat timeout |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | Control-side remote job result timeout |

To disable remote worker mode explicitly, run with `--no-remote` or set
`LOCAL_SHELL_MCP_REMOTE_ENABLED=false`.

## Docker Commands

Pull and run without Compose:

```bash
docker pull rijuyuezhu/local-shell-mcp:latest
mkdir -p workspace
docker run -d \
  --name local-shell-mcp \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD/workspace:/workspace" \
  rijuyuezhu/local-shell-mcp:latest
```

Check restart policy:

```bash
docker inspect local-shell-mcp --format '{{.HostConfig.RestartPolicy.Name}}'
```

It should be `unless-stopped`.

## Configuration

Environment variables use the `LOCAL_SHELL_MCP_` prefix.

| Variable | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `/workspace` | Root for file and command operations |
| `LOCAL_SHELL_MCP_AUTH_MODE` | `oauth` | `oauth` or `none` |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | unset | Public HTTPS origin used for OAuth metadata |
| `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | unset | PIN required to approve OAuth authorization |
| `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | `dev-change-me` | Secret used to sign bearer tokens |
| `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | OAuth bearer token lifetime in seconds; `0` means never expires |
| `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `false` | Give the AI unrestricted control of the container, including paths outside workspace and root access |
| `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | `3600` | Max command timeout |
| `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | `200000` | Output truncation limit |
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | Enable remote worker invite, join, polling, and `remote_*` tools |

You can also pass YAML:

```bash
local-shell-mcp --config config.example.yaml --mode mcp
```

## Git Access

Preferred options:

### Deploy Key

Create a deploy key restricted to one repository:

```bash
ssh-keygen -t ed25519 -f ./deploy_key_project -C local-shell-mcp-project
```

Add the public key to the GitHub repository deploy keys with the minimum required
permissions. Mount the private key only if you accept that the model-controlled
container can use it:

```yaml
volumes:
  - ./deploy_key_project:/home/agent/.ssh/id_ed25519:ro
```

### SSH Agent Socket

This avoids copying a private key into the container, but the container can still
ask the agent to sign Git operations:

```yaml
volumes:
  - ${SSH_AUTH_SOCK}:${SSH_AUTH_SOCK}
environment:
  SSH_AUTH_SOCK: ${SSH_AUTH_SOCK}
```

Use a key that only has access to repositories you are willing to expose.

## REST Debug API

The normal MCP server runs with:

```bash
local-shell-mcp --mode mcp
```

For local-only debugging, you can start the REST API:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none local-shell-mcp --mode http
```

Example:

```bash
curl -s http://127.0.0.1:8765/tools/run_shell \
  -H 'content-type: application/json' \
  -d '{"command":"pwd && ls -la","cwd":"."}' | jq
```

Do not expose HTTP debug mode publicly.

## Development

```bash
uv sync --group dev
uv run pre-commit install
uv run pre-commit run --all-files
uv run ruff check .
uv run pytest -q
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode mcp
```

The pre-commit hooks run Ruff linting with auto-fix and Ruff formatting before
commits.

You can verify the MCP endpoint with a standard MCP client:

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

## Troubleshooting

If ChatGPT says it connected but no tools are available:

1. Confirm Developer Mode is enabled for full MCP tools.
2. Delete and re-add the connector after server changes.
3. Check `/mcp` with the standard MCP client snippet above.
4. Watch `/workspace/.local-shell-mcp/audit.jsonl`.
5. Confirm `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` exactly matches the public HTTPS origin.

If OAuth succeeds but tool listing fails, check container logs:

```bash
docker compose logs --tail=200 local-shell-mcp
```

If you see `Task group is not initialized`, update to a newer image that includes
the MCP lifespan fix.

You can also probe the public endpoint from a machine with the project installed:

```bash
python scripts/probe-mcp.py https://your-public-host.example.com --pin "$LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN"
```

The probe should report successful unauthenticated `initialize/list_tools` and a
successful authenticated `environment_info` call.
