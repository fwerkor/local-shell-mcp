# 浏览器自动化

浏览器工具使用 Playwright 检查网页、采集证据、评估页面状态并生成 PDF。它们适合文档站、UI smoke test、视觉回归排查，以及收集可复现截图。

## 工具

| 工具 | 用途 |
|---|---|
| `playwright_install_tool` | 缺少浏览器二进制时安装它们。 |
| `browser_screenshot_tool` | 在工作区内保存页面截图。 |
| `browser_get_text_tool` | 从选择器中提取可见文本。 |
| `browser_eval_tool` | 在页面上下文中执行 JavaScript。 |
| `browser_pdf_tool` | 保存页面的 Chromium PDF。 |
| `playwright_run_script_tool` | 运行完整 Python Playwright 脚本。 |
| `remote_browser_*` | 在已连接远程 worker 上运行等价操作。 |

## 常见流程

### 截取本本文档站

1. 在持久 shell session 中启动站点。
2. 等待服务器输出本地 URL。
3. 对该 URL 调用 `browser_screenshot_tool`。
4. 如果需要从聊天中下载截图，使用 `create_file_link`。
5. 关闭持久 shell session。

### 提取文本做快速验证

当主要问题是页面是否渲染了预期内容时，使用 `browser_get_text_tool`。

示例任务表述：

```text
启动文档预览，对首页使用 browser_get_text_tool，确认导航中出现 deployment、tools 和 usage-patterns 页面。
```

### 运行自定义 Playwright 脚本

当内置截图、文本、PDF 工具不够时，使用 `playwright_run_script_tool`。例如需要点击流程、检查 console error，或采集多个页面。

脚本应有明确边界：

- 设置显式超时。
- 把产物保存到工作区。
- 除非环境专用于该任务，否则避免输入凭据。
- 对公开站点优先使用只读检查。

## 故障排查

如果浏览器启动失败：

- 对所需浏览器运行 `playwright_install_tool`。
- 确认容器或宿主机具备所需系统依赖。
- Docker 中优先使用项目官方镜像，因为它包含预期的浏览器和文档工具。
- 对远程 worker，在远程机器上安装依赖，或改用控制服务上的浏览器工具。
