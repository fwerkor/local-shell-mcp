# Human interface

`local-shell-mcp` provides two compatible human interfaces on top of the same service API, workspace, persistent terminal registry, remote-worker registry, todo store, and MCP audit log:

- **Web UI** is a native browser dashboard optimized for fast operational inspection.
- **OpenTUI** is the full terminal-oriented application and remains available both inside the browser and as a native terminal command.

Neither mode creates a separate control plane. Switching interfaces does not change the connected machines, sessions, jobs, todos, permissions, or audit data.

## Start the service

Start `local-shell-mcp` normally:

```bash
local-shell-mcp --mode mcp
```

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
/ui/#/todos
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
- Open todo counts.

### Machines

Machines lists the local controller and connected remote workers with status, platform, version, work directory, capabilities, and last-seen information.

### Workloads

Workloads combines active tracked jobs and standalone persistent shell sessions. The Web UI remains read-only for these records; use OpenTUI for interactive session management.

### Activity

Activity combines current alerts with recent MCP audit activity. Human-entered commands and file operations remain excluded from the MCP audit log.

### Todos

Todos displays the persistent todo store shared with MCP. Full create, edit, status, priority, and deletion controls remain available in OpenTUI.

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

The native TUI does not ask the human operator to log in. The launcher supplies a generated local credential to the loopback API transparently. This credential is stored under the configured state directory with owner-only permissions; a reverse proxy connecting from loopback does not receive the bypass.

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

### Todos

Todos provides persistent create, edit, delete, filtering, status changes, and priority changes through the same todo store exposed to MCP.

### Audit

Audit reads the bounded JSONL audit log and supports node, operation, event, session, search, time-range, and sort filters together with record-detail inspection.

### Remotes

Remotes displays online and offline remote workers, capabilities, work directories, and system metadata. It can create a one-time join invite, rename a node, or revoke its persistent identity.

## OpenTUI navigation

The top category bar and contextual footer actions can be clicked with a mouse in both native terminals and the browser console.

| Keys | Action |
|---|---|
| `Alt+1` … `Alt+6` | Open Dashboard, Files, Terminals, Remotes, Audit, or Todos. |
| `F2` … `F7` | Alternative category shortcuts. |
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
