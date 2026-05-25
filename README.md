# local-shell-mcp

A ChatGPT-compatible OAuth MCP server that gives AI coding agents controlled shell, filesystem, git, and Playwright access inside a local container.

Version 0.2 uses built-in OAuth 2.1 for ChatGPT custom connectors. Cloudflare Tunnel can still expose the service, but Cloudflare Access is no longer required. See [OAUTH_SETUP.md](OAUTH_SETUP.md).

# local-shell-mcp

`local-shell-mcp` is a Cloudflare Access protected MCP server that lets ChatGPT, Claude, Codex-like agents, or other MCP clients control a **dedicated local container** with shell, filesystem, Git, todo, and Playwright tools.

The intended deployment pattern is:

```text
ChatGPT / MCP client
  -> Cloudflare Access protected HTTPS endpoint
  -> local-shell-mcp running inside a disposable container
  -> /workspace mounted volume
  -> git / python / node / playwright / tmux / ripgrep
```

It is designed for the use case: “give an AI coding assistant full control over a container, but not the host.”

## Tool coverage

The tool set is deliberately close to Codex / Claude Code style workflows:

### Shell

- `run_shell_tool` — one-shot shell command
- `run_python_tool` — write and run temporary Python
- `shell_start` — start persistent tmux shell
- `shell_send` — send input to a persistent shell
- `shell_read` — read persistent shell output
- `shell_kill` — kill persistent shell
- `shell_list` — list shell sessions

### Filesystem

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

### Git

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

### Task state

- `todo_read_tool`
- `todo_write_tool`

### Playwright

- `playwright_install_tool`
- `browser_screenshot_tool`
- `browser_get_text_tool`
- `browser_eval_tool`
- `browser_pdf_tool`
- `playwright_run_script_tool`

### Diagnostics

- `environment_info`
- `audit_tail`

## Security model

This project intentionally exposes powerful tools. Treat the container as controlled by the connected model.

Default protections:

- All paths are restricted to `/workspace` unless `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true`.
- Cloudflare Access JWT verification is supported at the origin.
- Commands have timeout and output limits.
- Sensitive path fragments are denied by default.
- Dangerous host-control fragments such as `/var/run/docker.sock` are denied by default.
- Audit logs are written to `/workspace/.local-shell-mcp/audit.jsonl`.

Hard rules for safe deployment:

1. Do not mount `/var/run/docker.sock`.
2. Do not mount the host root filesystem.
3. Do not put long-lived GitHub PATs into environment variables visible to the model.
4. Prefer a single-repository GitHub deploy key or GitHub App installation token.
5. Run this in a disposable container or VM.
6. Protect the endpoint with Cloudflare Access or equivalent authentication.
7. Keep `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` unless the whole container is disposable.

## Quick start with Docker Compose

```bash
cp .env.example .env
# Edit .env with your Cloudflare Access team domain and AUD tag.
docker compose up -d --build
```

Local health check:

```bash
curl http://127.0.0.1:8765/healthz
```

Or pull the published Docker image:

```bash
docker pull fwerkor/local-shell-mcp:latest
docker run --rm -p 8765:8765 -v "$PWD/workspace:/workspace" fwerkor/local-shell-mcp:latest
```

To run the published image with Docker Compose:

```bash
cp .env.example .env
# Edit .env, then:
docker compose up -d
```

To also start the Cloudflare Tunnel sidecar, set `CLOUDFLARE_TUNNEL_TOKEN` in `.env` and run:

```bash
docker compose --profile tunnel up -d
```

If the container restarts with `Permission denied: '/workspace/.local-shell-mcp'`, fix the host workspace ownership:

```bash
sudo mkdir -p workspaces/default/.local-shell-mcp
sudo chown -R 10001:10001 workspaces/default
docker compose --profile tunnel up -d
```

The MCP endpoint is served by the process on port `8765`. For ChatGPT custom connectors, expose it as HTTPS, commonly:

```text
https://mcp.example.com/mcp
```

Actual path depends on the installed MCP Python SDK transport. This project attempts to use the SDK's streamable HTTP app when available, otherwise falls back to FastMCP's built-in streamable HTTP/SSE transport.

## Cloudflare Access setup

1. Create a Cloudflare Tunnel to the container:

```bash
cloudflared tunnel create local-shell-mcp
cloudflared tunnel route dns local-shell-mcp mcp.example.com
cloudflared tunnel run local-shell-mcp
```

Tunnel ingress should point to:

```text
http://localhost:8765
```

2. Create a Cloudflare Access self-hosted application:

```text
Application domain: mcp.example.com
Policy: allow your email or identity group
```

3. Copy the Application Audience (AUD) tag into `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_CF_ACCESS_AUDIENCE=<AUD tag>
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
```

Cloudflare Access forwards a `Cf-Access-Jwt-Assertion` header to your origin. `local-shell-mcp` validates this token using Cloudflare's JWKS endpoint as defense in depth. Cloudflare Access should still be configured to block unauthenticated requests before they reach the origin.

## Connecting to ChatGPT

In ChatGPT development mode / custom connector UI:

1. Add a new connector.
2. Use the public HTTPS MCP endpoint.
3. If Cloudflare Access prompts for login, authenticate with your allowed account.
4. Inspect the listed tools before enabling.

## Using GitHub safely

Preferred options:

### Option A: deploy key for one repository

On the host, create a deploy key restricted to one repo:

```bash
ssh-keygen -t ed25519 -f ./deploy_key_framediff -C local-shell-mcp-framediff
```

Add the public key to GitHub repository deploy keys with write access.

Mount it into the container as a read-only file only if you accept that the model-controlled container can use it:

```yaml
volumes:
  - ./deploy_key_framediff:/home/agent/.ssh/id_ed25519:ro
```

Inside the container:

```bash
chmod 600 ~/.ssh/id_ed25519
git clone git@github.com:fwerkor/FrameDiff.git
```

### Option B: ssh-agent socket

This avoids copying the private key into the container, but the container can still ask the agent to sign Git operations.

```yaml
volumes:
  - ${SSH_AUTH_SOCK}:${SSH_AUTH_SOCK}
environment:
  SSH_AUTH_SOCK: ${SSH_AUTH_SOCK}
```

Use a key that only has access to the repositories you are willing to expose.

## Playwright

The Dockerfile uses Microsoft's Playwright Python base image, so Chromium dependencies are included. If you install outside Docker:

```bash
pip install -e .
python -m playwright install --with-deps chromium
```

Example tool usage:

```text
browser_screenshot_tool(url="https://example.com", output_path="screenshots/example.png")
browser_get_text_tool(url="https://example.com")
browser_eval_tool(url="https://example.com", javascript="() => document.title")
```

## REST debug API

You can run an HTTP-only debug API:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none local-shell-mcp --mode http
```

Example:

```bash
curl -s http://127.0.0.1:8765/tools/run_shell \
  -H 'content-type: application/json' \
  -d '{"command":"pwd && ls -la","cwd":"."}' | jq
```

Do not expose HTTP debug mode without authentication.

## Configuration

Environment variables use the `LOCAL_SHELL_MCP_` prefix. You can also pass YAML:

```bash
local-shell-mcp --config config.example.yaml --mode mcp
```

Important options:

| Variable | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `/workspace` | Root for file and command operations |
| `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `false` | Allow absolute paths outside workspace |
| `LOCAL_SHELL_MCP_AUTH_MODE` | `cloudflare_access` | `cloudflare_access` or `none` |
| `LOCAL_SHELL_MCP_CF_ACCESS_TEAM_DOMAIN` | unset | Cloudflare Access team domain |
| `LOCAL_SHELL_MCP_CF_ACCESS_AUDIENCE` | unset | Access application AUD tag |
| `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | `3600` | Max command timeout |
| `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | `200000` | Output truncation limit |

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
LOCAL_SHELL_MCP_AUTH_MODE=none local-shell-mcp --mode http
pytest
```

## Release workflow

The repository includes a manual GitHub Actions workflow at `.github/workflows/release.yml`.
It builds the Python wheel/source distribution, publishes a GitHub Release, and pushes a multi-platform Docker image to Docker Hub as `fwerkor/local-shell-mcp`.

Before running it, add these repository secrets in GitHub:

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Your Docker Hub username, for example `fwerkor` |
| `DOCKERHUB_TOKEN` | A Docker Hub access token with permission to push `fwerkor/local-shell-mcp` |

To publish a release:

1. Open GitHub Actions.
2. Select the `Release` workflow.
3. Click `Run workflow`.
4. Enter a tag such as `v0.2.0`.
5. Keep the default platforms `linux/amd64,linux/arm64` unless you need a narrower build.

For a tag like `v0.2.0`, the workflow publishes these Docker tags:

```text
fwerkor/local-shell-mcp:v0.2.0
fwerkor/local-shell-mcp:0.2.0
fwerkor/local-shell-mcp:latest
```

`latest` is optional and can be disabled when running the workflow.

## Limitations

- MCP HTTP transport APIs have changed over time. This project tries `streamable_http_app`, then `sse_app`, then FastMCP's built-in transport. If your installed `mcp` package changes names again, use HTTP debug mode to validate the core tools and adjust `main.py` transport wiring.
- This is intentionally powerful. Do not run it against host-mounted secrets or privileged Docker sockets.
- It does not implement OpenAI-managed OAuth itself. Cloudflare Access is the intended auth layer.
