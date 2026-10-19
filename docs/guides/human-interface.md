# Human interface

`local-shell-mcp` provides two compatible human interfaces on top of the same service API, workspace, persistent terminal registry, remote-worker registry, and MCP audit log:

- **Web UI** is a native browser dashboard optimized for fast operational inspection.
- **OpenTUI** is the full terminal-oriented application and remains available both inside the browser and as a native terminal command.

Neither mode creates a separate control plane. Switching interfaces does not change the connected machines, sessions, jobs, permissions, or audit data.

## Start the service

Start `local-shell-mcp` normally:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

When ChatGPT renders MCP Apps, `workspace_open(session_id=...)` opens a floating collaborative view of the explicitly selected Logical Session. The Session owns the durable task state—objective, progress, Plan, and Activity—while Live Workspace only presents that state, live activity, and human controls. It never infers task identity from the MCP transport.

A typical explicit handoff is:

```text
session_manage(action="start", objective=...)
        -> session_id
... tool work with logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
new ChatGPT conversation
user passes the previous session_id
session_manage(action="resume", session_id=...)
        -> existing progress, Plan, and recent Activity
workspace_open(session_id=...)
        -> view of that same Session
```

`session_id` is the only durable task identity. An agent must not list, infer, or automatically select a Session from another conversation. To continue work in a new conversation, the user explicitly passes the existing `session_id`. Agents should report the active `session_id` after start/resume, at meaningful progress checkpoints, and before ending a turn so it can be handed off. Sessions do not bind a machine or working directory; normal tool parameters continue to choose local/remote targets and paths.

An optional `plan_manage` Plan enables Goal mode for the Session. If the Plan is active and no agent activity occurs for 15 minutes, an attached Live Workspace can ask ChatGPT to continue. The continuation resumes the same explicit `session_id` and is limited to 10 continuation attempts (accepted or rejected). Blocked, completed, and cancelled Plan statuses are not auto-continued; an active Plan whose steps are all completed or skipped remains eligible for cleanup continuation so the resumed agent can finish the Plan. Human pause/resume/cancel controls update the Session-owned Plan rather than ephemeral Live Workspace state.

## Browser interface

Open:

```text
http://127.0.0.1:8765/ui
```

For a public deployment, use the configured HTTPS origin:

```text
https://your-public-host.example.com/ui
```

The browser interface uses the same OAuth server and scopes as MCP. The page shell and static assets are public so the login screen can load, while `/api/ui/*` and the OpenTUI terminal WebSocket remain protected. Access tokens are stored only in browser session storage.

### Choose an interface

The OAuth screen offers two entry points:

- **Open Web UI** authorizes and opens the native dashboard.
- **Continue to OpenTUI** authorizes and opens the terminal interface, preserving the previous browser behavior.

After authorization, the interface selector in the sidebar switches between Web UI and OpenTUI without a new login. The current native page is remembered when moving temporarily to OpenTUI.

Routes are bookmarkable:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` and `#/dashboard` are aliases for Overview. `#/tui` and `#/opentui` are aliases for Console.

## Native Web UI

The native Web UI polls the existing human-interface API every five seconds and renders browser-native controls instead of terminal cells. It does not start a PTY until OpenTUI is selected.

### Overview

Overview presents the highest-priority operational information first:

- Controller health and current LSM version.
- Online and offline machine counts.
- Active tracked jobs and persistent terminal sessions.
- CPU, memory, workspace disk, load, network throughput, and uptime.
- Alerts generated from worker state, resource thresholds, failed jobs, and failed MCP calls.
- Recent model-originated MCP activity.

### Machines

Machines lists the local controller and connected remote workers with status, platform, version, work directory, capabilities, and last-seen information.

### Workloads

Workloads combines active tracked jobs and standalone persistent shell sessions. The Web UI remains read-only for these records; use OpenTUI for interactive session management.

### Activity

Activity combines current alerts with recent MCP audit activity. Human-entered commands and file operations remain excluded from the MCP audit log.

## Browser OpenTUI

Selecting **OpenTUI** lazily starts the same OpenTUI application used by the native terminal launcher. The browser console retains:

- Authenticated binary PTY transport over WebSocket.
- Automatic terminal resizing and reconnect backoff.
- Mouse interaction with OpenTUI controls.
- Fullscreen mode and browser-safe keyboard shortcuts.
- Mobile shortcut keys and explicit soft-keyboard control.
- SIXEL and inline-image support through xterm.js.

The browser does not create an OpenTUI PTY while the user remains in native Web UI mode.

## Native OpenTUI

Standalone release executables embed the platform OpenTUI runtime. Keep only the main executable, start the service, then run:

```bash
local-shell-mcp tui
```

The native TUI does not ask the human operator to log in. In the documented Docker Compose setup, the launcher reuses the host-only dedicated CLI credential for the loopback Human UI API; use `--token-file` for other split-runtime layouts. Browser-spawned OpenTUI instances use a controller-process credential that is created lazily and never persisted to the state directory or state backend. A reverse proxy does not receive either local bypass merely by connecting over loopback.

A source checkout can also run the TUI after installing Bun dependencies:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Use `--api-base` only when the local service uses a non-default port:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## OpenTUI screens

### Dashboard

Dashboard is the OpenTUI operational overview. Wide terminals show separate node, workload, alert, activity, system-information, and trend regions; narrower terminals collapse them into compact summaries without horizontal scrolling.

### Files

Files is an LSM-native three-pane file manager for local and remote machines. It provides create, edit, rename, copy, move, paste, delete, hidden-file toggle, refresh, text preview, binary preview, and bounded image thumbnails.

### Terminals

Terminals manages persistent shell sessions on local and remote machines. It supports complete-command input, raw interactive input, session switching, session creation and termination, recent output, and a collapsible MCP audit rail.

### Audit

Audit reads the bounded JSONL audit log and supports node, operation, event, session, search, time-range, and sort filters together with record-detail inspection.

### Remotes

Remotes displays online and offline remote workers, capabilities, work directories, and system metadata. It can create a one-time join invite, rename a node, or revoke its persistent identity.

## OpenTUI navigation

The top category bar and contextual footer actions can be clicked with a mouse in both native terminals and the browser console.

| Keys | Action |
|---|---|
| `Alt+1` … `Alt+5` | Open Dashboard, Files, Terminals, Remotes, or Audit. |
| `F2` … `F6` | Alternative category shortcuts. |
| `F1` | Open the keyboard guide. |
| `F9` | Refresh the machine list. |
| `Alt+Q` | Exit the native OpenTUI process without invoking a browser-reserved Ctrl shortcut. |

Terminals uses `Alt+N` for a new session, `Alt+W` to kill the selected session, `Alt+A` to toggle its audit rail, `Alt+R` to refresh, and `Alt+Left/Right` to switch sessions. The browser console intercepts these chords before browser-level navigation or menu handling.

## Configuration

| YAML key | Environment variable | Default | Purpose |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Mount or disable the human interfaces. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Browser interface mount path on the MCP service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Override native OpenTUI executable resolution. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Wallpaper setting retained for OpenTUI browser-console deployments. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Close an inactive browser OpenTUI PTY after this many seconds; `0` disables the timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maximum concurrent browser OpenTUI PTY sessions. |

## Packaging notes

- Docker images include the Web UI assets and native OpenTUI runtime.
- Standalone executables embed the Web UI assets and a compressed platform OpenTUI runtime.
- Python wheels include the browser assets; native OpenTUI requires a release executable or a source checkout with Bun dependencies installed.
- Both interfaces are served from the same process and port as MCP; no additional web service is required.
