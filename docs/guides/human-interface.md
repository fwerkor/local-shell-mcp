# Human interface

`local-shell-mcp` includes one OpenTUI application for human operators. It can run directly in a terminal or inside the browser. The browser does not implement a separate dashboard: it authenticates, opens a PTY over WebSocket, and renders the same OpenTUI application with xterm.js.

## Start the service

Start `local-shell-mcp` normally:

```bash
local-shell-mcp --mode mcp
```

The human interface shares the same service, workspace, persistent terminal registry, remote-worker registry, todo store, and MCP audit log.

## WebUI

Open:

```text
http://127.0.0.1:8765/ui
```

For a public deployment, use the configured HTTPS origin:

```text
https://your-public-host.example.com/ui
```

The WebUI uses the same OAuth server as MCP. The page shell and static assets are public so the login screen can load, while `/api/ui/*` and the terminal WebSocket remain protected. After authorization, the browser stores the access token in session storage and starts the OpenTUI process through an authenticated PTY.

The WebUI includes:

- A responsive glass terminal frame that fills desktop and mobile viewports.
- A cached Bing daily background when `ui_wallpaper=bing` is enabled.
- A lightweight animated aurora fallback when the wallpaper cannot be fetched.
- Binary terminal transport, automatic PTY resize, reconnect backoff, and fullscreen mode.
- Mouse support on the actual OpenTUI controls, including the top category bar.
- A mobile shortcut row whose `KB` button explicitly opens the soft keyboard; ordinary taps remain pointer actions and do not summon it.

## Native TUI

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

## Shared screens

### Files

Files is an LSM-native three-pane file manager:

- The left sidebar selects `local` or any connected remote machine.
- The parent pane shows the current directory in context.
- The current pane lists directories before files and supports mouse selection.
- The preview pane displays directory contents, text, or a bounded binary preview.
- File operations include create, edit, rename, copy, move, paste, delete, hidden-file toggle, and refresh.

The same service API powers file operations on local and remote machines, so the interaction model and conflict handling remain consistent across both targets.

### Terminals

Terminals manages the existing persistent terminal sessions:

- The left sidebar selects a local or remote machine.
- The bottom bar selects a session on that machine by keyboard or mouse.
- The main panel displays recent terminal output.
- The command field sends complete commands.
- Raw input mode forwards terminal control keys for interactive programs.
- The right audit rail can be collapsed and shows MCP activity associated with the selected session.

Commands and file operations entered manually through the TUI or WebUI are intentionally excluded from MCP audit records. The audit rail therefore represents model-originated MCP operations rather than a keylogger for human activity.

### Todos

Todos provides persistent create, edit, delete, filtering, status changes, and priority changes using the same todo store exposed to MCP. Todo rows and summary filters are mouse-selectable.

### Audit

Audit reads the bounded JSONL audit log and supports:

- Node filtering.
- Operation-type filtering.
- Event and session filtering.
- Free-text search.
- Time ranges.
- Ascending or descending time order.
- Record detail inspection.
- Mouse selection for filter cards and audit rows.

### Remotes

Remotes displays online and offline remote workers, capabilities, work directories, and system metadata. It can create a one-time join invite, rename a node, or revoke its persistent identity.

## Navigation

The top category bar and contextual footer actions can be clicked with a mouse in both native terminals and the WebUI. Keyboard navigation is also available:

| Keys | Action |
|---|---|
| `Alt+1` … `Alt+5` | Open Files, Terminals, Todos, Audit, or Remotes. |
| `F2` … `F6` | Alternative category shortcuts. |
| `F1` | Open the keyboard guide. |
| `F7` | Refresh the machine list. |
| `Ctrl+Q` | Exit the native OpenTUI process. |

Terminals uses `Alt+N` for a new session, `Alt+W` to kill the selected session, `Alt+A` to toggle its audit rail, `Alt+R` to refresh, and `Alt+Left/Right` to switch sessions. The WebUI intercepts these chords before browser-level navigation or menu handling.

Each screen displays its contextual shortcuts in the footer. Available actions are clickable, while unavailable actions are dimmed and ignore mouse input.

## Configuration

| YAML key | Environment variable | Default | Purpose |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Mount or disable the human interface. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | WebUI mount path on the MCP service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Override native OpenTUI executable resolution. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Use `bing`, `aurora`, or `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Close an inactive browser PTY after this many seconds; `0` disables the timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maximum concurrent browser PTY sessions. |

## Packaging notes

- Docker images include the WebUI assets and native OpenTUI runtime, and configure the service to use the bundled runtime directly.
- Standalone release executables contain the WebUI assets and a compressed platform OpenTUI runtime; neither WebUI nor native TUI requires a neighboring sidecar.
- Release archives contain one standalone executable; the OpenTUI runtime is compressed inside it and extracted into PyInstaller's temporary runtime directory when needed.
- Python wheels include the WebUI assets. A native TUI requires a release executable or a source checkout with Bun and the UI dependencies installed.
- The WebUI is served from the same process and port as MCP; no additional web service is required.
