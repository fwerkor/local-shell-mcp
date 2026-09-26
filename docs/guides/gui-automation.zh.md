<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# 桌面 GUI 自动化

`local-shell-mcp` can observe and control native desktop applications on Linux, Windows, and macOS. The public surface stays intentionally small:

| 工具 | 用途 |
|---|---|
| `gui_list` | List visible application windows and report the active native backend/capabilities. |
| `gui_state` | Observe one window. Returns a short-lived `state_id`, accessibility elements, window geometry, and optionally a native MCP screenshot. |
| `gui_action` | Execute semantic or coordinate actions against that exact observation. |

All three tools accept optional `machine`, so the same workflow can target a connected desktop worker.

## 观察后操作

Start with `gui_list`, select a `window_id`, then call `gui_state`. Prefer the returned accessibility `element_id` whenever one represents the target control:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Use window-relative `x`/`y` coordinates only when the UI has no useful accessibility element, such as a canvas or custom-drawn control. Returned element bounds and screenshots use the same window-relative logical pixel space, including HiDPI/Retina desktops. Raw coordinates outside the selected window are rejected.

A `state_id` expires after 30 seconds and is single-use. Coordinate actions also verify that the target window has not moved or resized since observation. If either check fails, call `gui_state` again instead of reusing stale coordinates.

Supported actions are `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus`, and `wait`.

## Native WebUI 人工控制

The Native WebUI has a **Desktop** page for direct human control of the same native GUI backends. Choose a machine and a window, then interact with the live window image using click, double-click, right-click, drag, wheel, keyboard shortcuts, or the text field for IME/CJK input.

This path is intentionally separate from model `state_id` semantics. Each displayed frame carries the observed window geometry; every human input request validates that the window still has exactly that geometry before injecting input. If the window moved, resized, or disappeared, the action is rejected and the WebUI refreshes the observation. Raw coordinates remain bounded to the selected window.

Keyboard and text actions explicitly focus the selected native window before injection. The WebUI uses lightweight screenshot polling rather than VNC/WebRTC video streaming, and the remote-only `gui_human_action` RPC is an internal controller-to-worker operation rather than an MCP tool exposed to models.

## 原生后端

| Platform | Accessibility / semantic control | Capture and raw input |
|---|---|---|
| Windows | Microsoft UI Automation | UIA/window capture plus native Windows mouse and keyboard input |
| macOS | Accessibility (`AXUIElement`) | `screencapture` for the selected window plus Quartz `CGEvent` input |
| Linux | AT-SPI | X11 native input/capture; Wayland uses native desktop capture and XDG Desktop Portal RemoteDesktop/ScreenCast for raw input |

Semantic actions are attempted first where possible. A button with a native invoke/press action can therefore be activated without guessing a pixel coordinate. Visual coordinates remain the fallback for inaccessible or custom-drawn content.

## 平台设置

### Windows

Run LSM in the same interactive desktop session as the applications it should control. The base `local-shell-mcp` install stays headless-safe and does not require the Windows UI Automation adapter; install the optional `local-shell-mcp[gui]` extra when local Windows GUI control is needed.

### macOS

Grant the LSM host process:

- **Accessibility** permission for semantic control and input.
- **Screen Recording** permission for screenshots.

The base package does not require PyObjC. Install the optional `local-shell-mcp[gui]` extra when local macOS GUI control is needed; machines that never use GUI tools do not need these frameworks.

### Linux

The desktop session must expose AT-SPI. Debian/Ubuntu systems normally provide the required system bindings with:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

The base package does not require the Python X11 or D-Bus adapters. The optional `local-shell-mcp[gui]` extra installs them for local GUI use. Remote workers detect the active Linux session before any GUI dependency bootstrap: X11 only needs the X11 adapter, Wayland only needs the D-Bus adapter, and headless workers install neither. On Wayland, raw pointer/keyboard fallback uses the XDG Desktop Portal RemoteDesktop API, so the desktop may show a one-time permission/session picker. KDE and GNOME portal implementations are supported. Window screenshots use the available native desktop capture path and fall back to the Screenshot portal when needed.

LSM workers commonly start outside the graphical login environment. The Linux backend recovers `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE`, and related variables from the user systemd environment when they are not inherited directly.

## 远程桌面

GUI tools run on the selected machine, not on the controller. The remote worker must belong to the user/session that owns the target desktop. GUI adapters are lazy and scoped to GUI calls: normal worker startup and shell/files/browser use do not install or import them. On Linux, a headless worker returns GUI unavailable before any GUI pip bootstrap; a graphical worker only checks or installs the adapter required by its active X11 or Wayland session.

Screenshots returned by a remote `gui_state` are transferred through LSM's file-transfer path and exposed to the model as native MCP image content; they are not embedded in the worker JSON response.
