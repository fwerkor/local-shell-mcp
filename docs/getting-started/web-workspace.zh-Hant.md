<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# 統一的網路工作空間

**統一的 LSM Web 工作區**是日常使用 local-shell-mcp 的建議方法。它將 AI 聊天、專案歷史記錄和 LSM 控制平面結合在一個響應式介面中，基於經過修改的供應商 LibreChat 前端。您仍然可以連接外部 MCP 用戶端，例如 [ChatGPT](chatgpt-connector.md) 或 [Gemini](gemini-spark.md)。

此工作區是**自架且可選安裝**：它是一個單獨的 Web 服務，不是最小控制器映像、獨立執行檔或遠端工作程式包的一部分。僅控制器部署保留原始瀏覽器 UI 和 OpenTUI。

## 工作區裡有什麼？

| 面積 | 你能做什麼 |
|---|---|
| 聊天和項目 | 選擇配置的模型、建立對話、組織專案、尋找過去的聊天記錄並存檔對話。歷史記錄保留在伺服器上。 |
| 控制器概述 | 查看運作狀況、最近的活動和連接的機器。 |
| 文件 | 瀏覽和管理本機或遠端文件。 |
| 終端 | 使用控制器或工作人員上的持久終端。 |
| 桌面 | 檢查和控制遠端 GUI 會話。 |
| 會議 | 檢查持久的 LSM 任務及其生命週期。 |
| 遙控器 | 連結和管理外派員工。 |
| 審計 | 檢查模型發起的工具活動。 |
| 嵌套MCP | 註冊、編輯、啟用、停用、刷新和刪除 LSM 後面的外部 MCP 伺服器。 |

控制器路由為 `/control/overview`、`/control/files`、`/control/terminals`、`/control/desktop`、`/control/sessions`、`/control/remotes` 和 `/control/audit`。聊天室地址為 `/c/new`。 LSM MCP 管理器控制 **LSM 的巢狀 MCP 登錄**；它不會在 LibreChat 中建立第二個登錄。

## 部署可選的聊天堆疊

1. 通过[快速入门](quickstart.md)安装 LSM Controller，默认启用 SQLite；原始状态会自动迁移，旧文件保留作为回滚来源。
2. 用户只需一个 HTTP/HTTPS 入口：`https://lsm.example.org`。聊天、终端、文件及远程控制都由同一个 Python Controller 提供。
3. 如需修改默认配置，可以在 Controller 服务环境中设置：

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. 使用源码部署或独立可执行文件启动 Controller：

```sh
local-shell-mcp --mode mcp
```

5. React 前端源码位于 `ui/workspace/`。仅在开发与打包时需要 Bun；参见[前端构建与安全说明](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md)。

Node.js、MongoDB、Meilisearch 和独立的 LibreChat Compose 服务都不再是运行时依赖。Worker 仍然是普通 Python 包。

**重构状态：** Python Agent 推理、SSE 恢复及工具协议仍在迁移，草稿 PR 暂不可替换生产部署。

## 登入並使用聊天功能

1. 打开 LSM Controller 的 `/ui` 入口，用原有 PIN 或 OAuth 完成认证；React 与控制面共享身份。
2. 在 LSM 中配置实际模型端点/API 凭证。Python Agent 后端仍在迁移中，草稿分支尚未完全支持生成。
3. 待 Python Agent 与 SSE 协议通过验收测试后即可正常新建对话；MCP、LSM 工具与文件上传继续沿用 Controller 权限。
4. 先进行只读请求：“检查 Controller 状态并列出工作区根目录，不修改文件。”
5. 通过文件、终端、桌面、会话、远程和审计页面直接查看与管理运行环境。

聊天上傳（最多 32 MiB）儲存在控制器工作區下，並且它們的絕對路徑提供給模型。瀏覽器上傳不會授予額外的檔案權限。模型導向的工具呼叫透過 LSM 授權、稽核和遠端工作路由器。

## 外部 MCP、安全性和數據

使用工作區 MCP 側邊欄管理嵌套的外部 MCP 伺服器。這支援本機 stdio 伺服器和 HTTP 伺服器，包括單獨的私人環境變數和請求標頭。秘密不會返回瀏覽器。 **外部 MCP** 聊天切換允許搜尋、檢查和呼叫嵌套工具；當本機 LSM 工具停用時，它不會授予模型 `mcp_manage`。 UI 管理受到正常控制器授權的保護。

聊天、项目、Agent、会话、审计及 Worker 状态统一使用 `.local-shell-mcp/lsm.sqlite3`，并使用 SQLite FTS5 搜索；文件产物仍在同目录下管理。

工作区是原生 React 页面，不使用 iframe 或独立 Web 服务；Worker 与外部 MCP 客户端保持兼容。

## 故障排除

- **WebUI 无法启动：** 查看 Python Controller 日志、SQLite 初始化和打包前端；紧急情况下可通过 `LOCAL_SHELL_MCP_STATE_BACKEND=file` 恢复文件存储。
- **登录失败：** 使用现有 Controller PIN/OAuth 认证，不再需要 LibreChat 独立账户或桥接密钥。
- **聊天界面可打开但无法应答：** 草稿分支的 Python Agent 与 SSE 迁移尚未完成，请勿部署到生产。
- **MCP 工具缺失：** 核对 Controller 权限与嵌套 MCP 注册表；仅外部 MCP 模式不暴露 `mcp_manage`。
- **文件或会话为空：** 检查 Controller 工作区、SQLite 数据迁移及认证身份。

有關實現詳細資訊和更新，請參閱 [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) 和 [human interface guide](../guides/human-interface.md)。
