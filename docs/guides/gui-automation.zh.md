<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# 桌面 GUI 自动化

`local-shell-mcp` 可以观察和控制 Linux、Windows 与 macOS 上的原生桌面应用。公开接口刻意保持精简：

| 工具 | 用途 |
|---|---|
| `gui_list` | 列出可见的应用窗口，并返回当前原生后端及其能力。 |
| `gui_state` | 观察一个窗口。返回短期有效的 `state_id`、无障碍元素、窗口几何信息，以及可选的原生 MCP 截图。 |
| `gui_action` | 针对这一次精确观察执行语义动作或坐标动作。 |

三个工具都接受可选的 `machine` 参数，因此同一套流程也可以操作已连接的桌面 worker。

## 先观察，再操作

先调用 `gui_list`，选择一个 `window_id`，然后调用 `gui_state`。如果返回的无障碍 `element_id` 能代表目标控件，应优先使用它：

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

只有当界面没有可用的无障碍元素（例如画布或自绘控件）时，才使用窗口相对的 `x`/`y` 坐标。返回的元素边界与截图使用同一套窗口相对逻辑像素坐标，包括 HiDPI/Retina 桌面。超出所选窗口的原始坐标会被拒绝。

`state_id` 在 30 秒后过期，并且只能使用一次。坐标动作还会验证目标窗口自观察后没有移动或改变大小。如果任一检查失败，应重新调用 `gui_state`，不要复用过期坐标。

支持的动作包括 `click`、`double_click`、`right_click`、`move`、`scroll`、`drag`、`type`、`key`、`set_value`、`focus` 和 `wait`。

## Native WebUI 中的人工控制

Native WebUI 提供 **Desktop** 页面，可直接人工控制相同的原生 GUI 后端。选择机器和窗口后，可以在实时窗口图像上执行单击、双击、右击、拖动、滚轮、键盘快捷键，也可通过文本框进行 IME/CJK 输入。

这条路径与模型使用的 `state_id` 语义刻意分离。每个显示帧都携带观察到的窗口几何信息；每次人工输入请求在注入前都会验证窗口几何仍完全一致。如果窗口已经移动、缩放或消失，动作会被拒绝，WebUI 会刷新观察。原始坐标始终被限制在所选窗口内。

键盘和文本动作会在注入前显式聚焦所选原生窗口。WebUI 使用轻量截图轮询，而不是 VNC/WebRTC 视频流；仅远程使用的 `gui_human_action` RPC 是 controller 到 worker 的内部操作，并不是暴露给模型的 MCP 工具。

## 原生后端

| 平台 | 无障碍 / 语义控制 | 截图与原始输入 |
|---|---|---|
| Windows | Microsoft UI Automation | 窗口截图以及 Windows 原生鼠标和键盘输入 |
| macOS | Accessibility（`AXUIElement`） | 对所选窗口使用 `screencapture`，并通过 Quartz `CGEvent` 输入 |
| Linux | AT-SPI | X11 原生输入/截图；Wayland 使用原生桌面截图，并通过 XDG Desktop Portal RemoteDesktop/ScreenCast 实现原始输入 |

在可行时会优先尝试语义动作。因此，具有原生 invoke/press 动作的按钮可以直接激活，无需猜测像素坐标。对于无法访问或自绘内容，视觉坐标仍作为回退方案。

## 平台配置

### Windows

LSM 应运行在与目标应用相同的交互式桌面会话中。基础 `local-shell-mcp` 安装保持 headless 安全，不强制依赖 Windows UI Automation adapter；只有需要本地 Windows GUI 控制时才安装可选的 `local-shell-mcp[gui]` extra。

### macOS

向 LSM 宿主进程授予：

- 用于语义控制和输入的 **辅助功能** 权限。
- 用于截图的 **屏幕录制** 权限。

基础包不强制依赖 PyObjC。只有需要本地 macOS GUI 控制时才安装可选的 `local-shell-mcp[gui]` extra；从不使用 GUI 工具的机器无需这些 framework。

### Linux

桌面会话必须提供 AT-SPI。Debian/Ubuntu 系统一般可通过以下命令安装所需的系统 binding：

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

基础包不强制依赖 Python X11 或 D-Bus adapter。可选的 `local-shell-mcp[gui]` extra 会为本地 GUI 使用安装它们。远程 worker 在任何 GUI 依赖 bootstrap 之前先检测当前 Linux 会话：X11 只需要 X11 adapter，Wayland 只需要 D-Bus adapter，headless worker 两者都不会安装。在 Wayland 上，原始指针/键盘回退使用 XDG Desktop Portal RemoteDesktop API，因此桌面可能首次显示权限/会话选择器。支持 KDE 和 GNOME 的 portal 实现。窗口截图优先使用可用的原生桌面截图路径，必要时回退到 Screenshot portal。

LSM worker 经常在图形登录环境之外启动。若相关变量没有被直接继承，Linux backend 会从用户 systemd 环境恢复 `DISPLAY`、`WAYLAND_DISPLAY`、`XDG_SESSION_TYPE` 等变量。

## 远程桌面

GUI 工具实际运行在所选机器上，而不是 controller 上。远程 worker 必须属于拥有目标桌面的用户/会话。GUI adapter 采用惰性加载且只作用于 GUI 调用：正常 worker 启动以及 shell/files/browser 使用不会安装或导入它们。在 Linux 上，headless worker 会在任何 GUI pip bootstrap 之前返回 GUI 不可用；图形 worker 只检查或安装当前 X11/Wayland 会话所需的 adapter。

远程 `gui_state` 返回的截图通过 LSM 文件传输路径传输，并以原生 MCP 图像内容暴露给模型；它们不会嵌入 worker 的 JSON 响应。
