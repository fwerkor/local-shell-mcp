<!-- i18n-source-sha256: b98a6f03c96ab99dc4f9605caa7688dfef95651433e0d2c9377caafd62a2c98d -->
# Automatyzacja GUI pulpitu

`local-shell-mcp` can observe and control native desktop applications on Linux, Windows, and macOS. The public surface stays intentionally small:

| Narzędzie | Cel |
|---|---|
| `gui_list` | List visible application windows and report the active native backend/capabilities. |
| `gui_state` | Observe one window. Returns a short-lived `state_id`, accessibility elements, window geometry, and optionally a native MCP screenshot. |
| `gui_action` | Execute semantic or coordinate actions against that exact observation. |

All three tools accept optional `machine`, so the same workflow can target a connected desktop worker.

## Obserwuj, potem działaj

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

## Sterowanie ręczne w Native WebUI

The Native WebUI has a **Desktop** page for direct human control of the same native GUI backends. Choose a machine and a window, then interact with the live window image using click, double-click, right-click, drag, wheel, keyboard shortcuts, or the text field for IME/CJK input.

This path is intentionally separate from model `state_id` semantics. Each displayed frame carries the observed window geometry; every human input request validates that the window still has exactly that geometry before injecting input. If the window moved, resized, or disappeared, the action is rejected and the WebUI refreshes the observation. Raw coordinates remain bounded to the selected window.

Keyboard and text actions explicitly focus the selected native window before injection. The WebUI uses lightweight screenshot polling rather than VNC/WebRTC video streaming, and the remote-only `gui_human_action` RPC is an internal controller-to-worker operation rather than an MCP tool exposed to models.

## Natywne backendy

| Platform | Accessibility / semantic control | Capture and raw input |
|---|---|---|
| Windows | Microsoft UI Automation | UIA/window capture plus native Windows mouse and keyboard input |
| macOS | Accessibility (`AXUIElement`) | `screencapture` for the selected window plus Quartz `CGEvent` input |
| Linux | AT-SPI | X11 native input/capture; Wayland uses native desktop capture and XDG Desktop Portal RemoteDesktop/ScreenCast for raw input |

Semantic actions are attempted first where possible. A button with a native invoke/press action can therefore be activated without guessing a pixel coordinate. Visual coordinates remain the fallback for inaccessible or custom-drawn content.

## Konfiguracja platformy

### Windows

Run LSM in the same interactive desktop session as the applications it should control. A normal `pipx install local-shell-mcp` or Python package installation installs the Windows UI Automation dependency automatically.

### macOS

Grant the LSM host process:

- **Accessibility** permission for semantic control and input.
- **Screen Recording** permission for screenshots.

The Python package installs the required PyObjC frameworks automatically on macOS.

### Linux

The desktop session must expose AT-SPI. Debian/Ubuntu systems normally provide the required system bindings with:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

The Python package installs the pure-Python X11 and D-Bus client dependencies. On Wayland, raw pointer/keyboard fallback uses the XDG Desktop Portal RemoteDesktop API, so the desktop may show a one-time permission/session picker. KDE and GNOME portal implementations are supported. Window screenshots use the available native desktop capture path and fall back to the Screenshot portal when needed.

LSM workers commonly start outside the graphical login environment. The Linux backend recovers `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE`, and related variables from the user systemd environment when they are not inherited directly.

## Pulpity zdalne

GUI tools run on the selected machine, not on the controller. The remote worker must belong to the user/session that owns the target desktop and must have the platform-native GUI dependencies available. A headless worker can still use shell/files/browser tools, but `gui_list` will report that no usable graphical session is available.

Screenshots returned by a remote `gui_state` are transferred through LSM's file-transfer path and exposed to the model as native MCP image content; they are not embedded in the worker JSON response.
