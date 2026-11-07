<!-- i18n-source-sha256: a9820f08198cf8e823f59550928c07346f9669f2dbec46d3b8cd523c34034e01 -->
# 快速開始

本指南啟動 LSM 控制器並開啟其瀏覽器介面。 [unified web workspace](web-workspace.md)為推薦日常體驗；它是一個單獨部署的、可選的聊天堆疊。 ChatGPT、Gemini 和其他外部 MCP 用戶端可以連接到相同控制器。請參閱 [runtime choices and deployment model](../guides/deployment.md)。

## 要求

- Docker Engine 與 Compose v2。
- 如果遠端使用者或外部 MCP 用戶端必須連接，則為公共 HTTPS 端點。
- 一個專用工作區目錄。
- 較長的隨機 OAuth 管理 PIN 和 JWT 密鑰。

!!! warning
    接入的模型可以操作配置的工作區。建議在一次性容器或虛擬機中運行服務，並避免掛載宿主機控制資源。

## 1. 克隆並配置

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

編輯 `.env`：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. 啓動服務

```bash
mkdir -p workspaces/default
docker compose up -d
```

檢查狀態：

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

健康響應會返回 HTTP `200`。

## 3. 暴露 HTTPS

**推薦：** 有條件時，應直接部署到具有公網位址的伺服器，或透過公網伺服器搭配 HTTPS 反向代理轉發流量。

**不推薦：** Cloudflare Tunnel 用戶端的上傳速度可能非常慢，導致檔案上傳與傳輸功能難以正常使用。僅在無法進行公網部署或透過公網伺服器轉發時，才考慮作為備選方案。 只有选择可选的 Tunnel sidecar 时，才需要在 `.env` 配置 `CLOUDFLARE_TUNNEL_TOKEN`。

如果使用 Cloudflare Tunnel sidecar：

```bash
docker compose --profile tunnel up -d
```

在 Cloudflare Zero Trust 中，把公開 hostname 指向：

```text
http://local-shell-mcp:8765
```

如果使用 Caddy、Nginx、Traefik、Nginx Proxy Manager 或其它反向代理，把 HTTPS 流量轉發到 `127.0.0.1:8765` 或容器網絡地址。

## 4.開啟瀏覽器工作區

開啟控制器登入：

```text
https://your-public-host.example.com/ui
```

對於聊天、專案和整合控制頁面，請關注 [unified web workspace guide](web-workspace.md)。原始輕量級WebUI在未安裝聊天時可用。

## 5. 安全確認工具訪問

先讓模型執行：

```text
Use local-shell-mcp. First call environment_get, then list the workspace root. Do not modify files yet.
```

預期只讀工具包括：

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. 從有邊界的任務開始

適合作爲第一次任務的提示：

```text
Inspect this repository, summarize the project layout, run the existing test suite if one is obvious, and do not change files.
```

確認連接正常後，再給出更具體的修改任務：

```text
Fix the failing test. Read the relevant files first, make the smallest patch, run the targeted test, then show git diff. Do not commit until I approve.
```

## 更新

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

如果使用 tunnel profile：

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

## 下一步

| 需求 | 頁面 |
|---|---|
| 理解運行時與客戶端關係 | [運行時與客戶端模型](../guides/deployment.md) |
| 使用 Docker Compose 運行 | [Docker Compose 運行時](../installation/docker.md) |
| 從 VS Code 啓動運行時 | [VS Code 擴展運行時](../installation/vscode-extension.md) |
| 使用獨立二進制運行 | [獨立二進制運行時](../installation/binary.md) |
| 使用 Python、pipx 或源碼運行 | [Python 運行時](../installation/python.md) |
| 使用統一的聊天和控制介面 | [Unified web workspace](web-workspace.md) |
| 新增 Gemini Spark 作為客戶端 | [Gemini Custom Apps](gemini-spark.md) |
| 添加 ChatGPT 客戶端 | [ChatGPT 連接器](chatgpt-connector.md) |
| 選擇工具並寫更好的提示詞 | [使用模式](../guides/usage-patterns.md) |
| 連接 HPC、NPU/GPU 或 NAT 機器 | [遠程節點](../guides/remote-workers.md) |
| 理解每一個 MCP 工具 | [工具參考](../reference/tools.md) |
