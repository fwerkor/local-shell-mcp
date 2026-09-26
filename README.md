<div align="center">

<img src="docs/assets/logo.svg" alt="local-shell-mcp logo" width="152">

# local-shell-mcp

**A ChatGPT-ready MCP control plane for shell, files, browser automation, file links, and remote machines.**

[![Docs](https://img.shields.io/badge/docs-fwerkor.github.io%2Flocal--shell--mcp-7c3aed?logo=materialformkdocs&logoColor=white)](https://fwerkor.github.io/local-shell-mcp/)
[![CI](https://github.com/fwerkor/local-shell-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/fwerkor/local-shell-mcp/actions/workflows/ci.yml)
[![dsh.so security](https://www.dsh.so/badge/local-shell-mcp.svg)](https://www.dsh.so/artifact/local-shell-mcp)
[![Release](https://img.shields.io/github/v/release/fwerkor/local-shell-mcp?sort=semver)](https://github.com/fwerkor/local-shell-mcp/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white)](https://github.com/fwerkor/local-shell-mcp)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed?logo=docker&logoColor=white)](https://github.com/fwerkor/local-shell-mcp/pkgs/container/local-shell-mcp)
[![License](https://img.shields.io/github/license/fwerkor/local-shell-mcp)](LICENSE)

[Documentation](https://fwerkor.github.io/local-shell-mcp/) · [Quickstart](https://fwerkor.github.io/local-shell-mcp/getting-started/quickstart/) · [Runtime choices](https://fwerkor.github.io/local-shell-mcp/guides/deployment/) · [ChatGPT connector](https://fwerkor.github.io/local-shell-mcp/getting-started/chatgpt-connector/) · [DSH plugin](https://fwerkor.github.io/local-shell-mcp/clients/deepseek-harness/) · [Tools](https://fwerkor.github.io/local-shell-mcp/reference/tools/) · [Releases](https://github.com/fwerkor/local-shell-mcp/releases)

</div>

---

`local-shell-mcp` gives ChatGPT Developer Mode and other MCP clients controlled access to a real execution environment. It exposes a dedicated workspace with shell, persistent shell, filesystem, search, patch, Playwright, audit, durable logical sessions with optional Goal plans, public file links, and outbound remote-worker access. Git is handled through ordinary shell commands instead of a parallel wrapper API.

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
| DeepSeek Harness plugin | Install this repository as a DSH bundle and expose the complete LSM tool surface, including remote workers. |
| ChatGPT Live Workspace | Render a native MCP App for real-time activity, terminal, files, diffs, jobs, remotes, audit, and direct human/agent collaboration inside ChatGPT. |
| Safer operations | Workspace scoping, shell timeouts, output limits, environment filtering, audit logs, and secret scanning. |

## Quick start

Install the official launcher or Python package when you want a host runtime:

```bash
npx local-shell-mcp --help
pipx install local-shell-mcp
lsm --help
```

The npm and Python distributions both expose `local-shell-mcp`; installed packages also expose `lsm` as the short command. The npm distribution is only a verified launcher for the matching standalone release binary, not a second server implementation.

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

The service includes two compatible human interfaces backed by the same authenticated API and state:

- **Web UI** is a native browser dashboard for system health, machines, workloads, recent MCP activity, and alerts.
- **OpenTUI** is the full terminal-oriented interface with Dashboard, Files, Terminals, Remotes, and Audit screens. It remains available in the browser as a selectable console and as the native `local-shell-mcp tui` command.

Open the browser interface on the service origin:

```text
http://127.0.0.1:8765/ui
```

The OAuth screen lets you choose Web UI or OpenTUI before authorization. After login, switch modes at any time from the interface selector. Native Web UI routes use URL hashes such as `#/overview` and `#/console`, so a selected mode or page can be bookmarked. The OpenTUI console retains the existing authenticated xterm.js/PTY transport, mouse interaction, automatic resizing, reconnects, fullscreen mode, and mobile shortcut row.

Standalone release executables embed the native OpenTUI runtime, while Docker images provide it inside the image. Start the service, then launch it without a human login prompt:

```bash
local-shell-mcp tui
```

Files remains an LSM-native three-pane file manager inside OpenTUI for local and remote machines. It renders bounded PNG/JPEG/GIF/WebP thumbnails and provides consistent file operations through the shared service API. Manual actions entered through either human interface are excluded from the MCP audit log; Activity, Audit, and the terminal audit rail show model-originated MCP activity.

See the [human interface guide](https://fwerkor.github.io/local-shell-mcp/guides/human-interface/).

## ChatGPT setup

For full shell, filesystem, remote-worker, and Playwright tools, use ChatGPT Developer Mode or another full MCP client. ChatGPT is a client connection; choose and start a runtime first.

`session_manage` provides one durable logical task context for agent work. A Session is deliberately independent of machine and working directory: it stores the task objective, semantic progress reports, recent execution Activity, and an optional Plan. `session_id` is the only durable task identity. To continue work in another ChatGPT conversation, the user explicitly passes the existing `session_id`, and the new agent calls `session_manage(action="resume", session_id=...)`. Agents do not list or auto-select Sessions from other conversations. They should report the active `session_id` after start/resume, at meaningful progress checkpoints, and before ending a turn, while using `session_manage(action="report", session_id=...)` for semantic progress rather than copying every tool result into the summary. Ordinary tools receive the same task identity as `logical_session_id`.

When the client supports MCP Apps, `workspace_open(session_id=...)` opens the execution view for the explicitly selected Session as a floating MCP App and can expand to fullscreen. The v3 name `open_live_workspace` remains a hidden, non-enumerated compatibility alias for ChatGPT clients with a cached recipient; new integrations see and use only `workspace_open`. The Live Workspace is a reconnectable viewer and collaboration surface, not the owner of task state: closing it or reconnecting MCP does not discard Session progress, Activity, or its Plan. Ordinary MCP tools remain the execution API, while the app adds live operational activity, persistent terminals, file/diff inspection, jobs, remotes, audit data, and the active Session id. Clients that do not render MCP Apps continue to use the normal tool surface unchanged.

`plan_manage(session_id=...)` optionally enables **Goal mode** on that explicit Session for substantial multi-step work. An active Plan is the goal: its steps can be revised as execution changes and, while a Live Workspace is attached, the app can request continuation after 15 minutes without agent tool activity. Automatic continuation is capped at 10 continuation attempts (accepted or rejected) and resumes the same Session before continuing. Blocked, completed, and cancelled Plan statuses are never nudged; an active Plan whose steps are all completed or skipped remains eligible for cleanup continuation so a resumed agent can call `plan_manage(action="finish")`. A Session does not require a Plan.

1. Expose the server through HTTPS.
2. Keep OAuth enabled.
3. Add the MCP endpoint: `https://your-public-host.example.com/mcp`.
4. Complete the OAuth authorization flow.
5. Start with a bounded task and inspect the audit log when needed.

Read the dedicated [ChatGPT connector guide](https://fwerkor.github.io/local-shell-mcp/getting-started/chatgpt-connector/).

## DeepSeek Harness plugin

[![dsh.so install](https://www.dsh.so/badge/install/local-shell-mcp.svg)](https://www.dsh.so/artifact/local-shell-mcp)

The repository root is also a DSH plugin bundle. With a normal LSM HTTP/MCP service running on the same host, install it directly into a DSH profile:

```bash
dsh plugin --profile web add 'github:fwerkor/local-shell-mcp#main'
```

The bundle uses an LSM-aware Streamable HTTP bridge and keeps the complete LSM tool surface, including `remote_manage`, `remote_transfer`, browser tools, and Dynamic MCP tools. Each DSH Session receives a stable v4 logical-session identity, so its Logical Session, active run, Activity, and native **Live Workspace** view stay isolated from other DSH conversations and survive DSH-side MCP transport recreation. DSH sees model tools under the normal `mcp__lsm__*` namespace. For production, pin the Git spec to a reviewed release or commit.

See the [DeepSeek Harness integration guide](https://fwerkor.github.io/local-shell-mcp/clients/deepseek-harness/).

## VS Code extension runtime

Release assets include `local-shell-mcp-<version>.vsix`. The extension is a runtime launcher for the current VS Code workspace. It starts the same server, checks `/healthz`, copies the MCP URL, and copies a ready-to-paste ChatGPT setup prompt.

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

This makes the universal Skills CLI layout work directly, for example `npx skills add owner/repo --agent universal -y`. Use `skill_list` to discover installed Skills, `skill_load` to load one instruction set, and `skill_read` to read a related file by the returned Skill-relative path. Changes are detected on the next call; no per-Skill MCP tools are registered and no client reconnect is required.

See the [Agent Skills guide](https://fwerkor.github.io/local-shell-mcp/guides/skills/).

## Tool surface

The public MCP surface includes:

- Live Workspace: `workspace_open` opens the reconnectable MCP App for the current logical Session.
- Shell and jobs: `run_shell`, `run_python`, persistent `shell_*`, and tracked `job_*` tools. Use `run_shell` for Git CLI operations.
- Filesystem: `file_list`, `file_tree`, `file_glob`, `file_grep`, unified `file_read`, native-vision `image_view`, `file_write`, unified `file_edit`, `file_delete`, and `file_patch`.
- Transfer: `remote_transfer` for files or directories across controller and worker endpoints.
- Dynamic MCP: `mcp_manage`, `mcp_tool_search`, `mcp_tool_inspect`, and `mcp_tool_call`. External tools are discovered progressively and never expand LSM's own `tools/list` surface.
- Browser: persistent high-level `browser_session`, `browser_snapshot`, and `browser_act`; `browser_run_script` is the low-level Playwright escape hatch.
- Optional ChatGPT Web dispatch: `chat_dispatch` durably queues idempotent prompts through a configured [LocalShell Web Supervisor](https://github.com/DongYaoZe/localshell-web-supervisor) checkout, supervises a bounded page pool, and never closes borrowed user pages.
- File links: `link_create`, `link_list`, `link_revoke`.
- Remote workers: `remote_manage` with `invite`, `list`, `rename`, and `revoke` actions; normal execution tools accept optional `machine`.
- Agent Skills: `skill_list`, `skill_load`, `skill_read`.
- Sessions: `session_manage` for durable task context, progress handoff, agent-run takeover, and cross-run inheritance.
- Planning: `plan_manage` for optional Session-owned Goal mode and automatic continuation.
- Diagnostics: `environment_get` (including version information), `secret_scan`, and `audit_tail`.

The detailed tool reference, including purpose, inputs, returns, combinations, and notes for every tool, is available in the [docs](https://fwerkor.github.io/local-shell-mcp/reference/tools/).

## Related projects

The following independently maintained projects explore adjacent session and orchestration models around LSM:

- [rijuyuezhu/local-shell-mcp](https://github.com/rijuyuezhu/local-shell-mcp) uses a different, execution-oriented session model that binds workspace context and related resources to explicit sessions. It has its own tool surface and release lifecycle.
- [DongYaoZe/localshell-web-supervisor](https://github.com/DongYaoZe/localshell-web-supervisor) is a local reliability and orchestration layer for browser-driven agents using Local Shell MCP. It supervises replaceable browser workers while reconciling durable LSM sessions, Goals/jobs, and actual workspace/Git state, with guarded lease, handoff, takeover, and recovery flows. It is not part of the LSM runtime or release lifecycle.

## Security model

This project intentionally exposes powerful tools. Treat the connected model as having control of the container or VM.

Default protections include:

- Workspace scoping to `/workspace` unless full-container mode is explicitly enabled.
- Command timeouts, output limits, and concurrency limits.
- Default command/path denylists for host-control fragments.
- Shell subprocess environment filtering for service-side secrets.
- Dynamic stdio MCP servers inherit only a minimal OS environment plus explicitly configured per-server variables; configured environment/header values are stored in a mode-`0600` state file and redacted from tool results and Audit arguments.
- Chat dispatch prompts are redacted from Audit arguments but are stored in the configured LWS durable queue; protect that local state directory as sensitive.
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
| `LOCAL_SHELL_MCP_UI_WALLPAPER` | Select `bing`, `aurora`, or `none` for the OpenTUI browser console background. |
| `LOCAL_SHELL_MCP_CHAT_DISPATCH_LWS_REPO` | Optional local LWS checkout used by the open-world `chat_dispatch` tool. Enqueues require an idempotency key; new conversations also require a stable conversation key. |
| `LOCAL_SHELL_MCP_CHAT_DISPATCH_MAX_WINDOWS` | Maximum dispatcher-owned ChatGPT windows, from 1 to 16; default `4`. |
| `LOCAL_SHELL_MCP_CHAT_DISPATCH_IDLE_CLOSE_S` | Idle grace before an exact dispatcher-owned page is closed; default `90` seconds. |
| `LOCAL_SHELL_MCP_CHAT_DISPATCH_WATCHDOG_ENABLED` | Start a hidden detached recovery watchdog after an enqueue; default `true`. |
| `LOCAL_SHELL_MCP_CHAT_DISPATCH_WATCHDOG_INTERVAL_S` | Resident watchdog reconciliation interval; default `15` seconds. |
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
