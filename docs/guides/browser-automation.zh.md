# 浏览器自动化

浏览器工具基于 Playwright，用于检查页面、保存证据和执行可复现的交互流程。公开工具面刻意保持精简。

## 工具

| 工具 | 用途 |
|---|---|
| `browser_get_text_tool` | 从指定 selector 提取可见文本。 |
| `browser_capture_tool` | 保存 PNG 截图或 Chromium PDF。 |
| `playwright_run_script_tool` | 运行完整 Python Playwright 脚本，处理点击、表单、控制台检查或多页面流程。 |

三个工具都接受可选的 `machine` 参数。控制端或目标 worker 必须已经安装浏览器依赖；安装工作通过普通 shell 命令完成，例如 `python -m playwright install chromium`。

## 常见流程

进行视觉验证时，先用 `shell_start` 或 `job_start` 启动站点，等服务就绪后调用 `browser_capture_tool(capture_format="png")`，最后停止进程。需要可打印输出时使用 `capture_format="pdf"`，并选择 Chromium。

只关心渲染文本时使用 `browser_get_text_tool`。需要交互、JavaScript 求值或复杂导航时使用 `playwright_run_script_tool`。

脚本应设置明确超时，把产物保存到工作区，并避免在非专用环境中输入凭据。
