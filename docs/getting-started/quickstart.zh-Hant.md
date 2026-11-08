<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# 快速開始

本指南啟動 LSM 控制器並開啟其瀏覽器介面。 [unified web workspace](web-workspace.md)為推薦日常體驗；它是一個單獨部署的、可選的聊天堆疊。 ChatGPT、Gemini 和其他外部 MCP 用戶端可以連接到相同控制器。請參閱 [runtime choices and deployment model](../guides/deployment.md)。

推薦從 [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) 下載 **Controller 單檔可執行程式**直接部署。Controller 不需預裝 Python、Docker 或複製原始碼。以下為 **Linux x86_64** 指令；Windows、macOS 或 ARM64 請參閱 [二進位安裝指南](../installation/binary.md)。

## 要求

- 適用平台的可執行檔及 `curl`（範例為 Linux x86_64）。
- 只有遠端使用者或外部 MCP 用戶端需要連線時才需公開 HTTPS。
- 獨立且受限的工作區。
- 強隨機 OAuth 管理 PIN 和 JWT 金鑰。

!!! warning
    接入的模型可以操作配置的工作區。建議在一次性容器或虛擬機中運行服務，並避免掛載宿主機控制資源。

## 1. 下載單檔程式並設定

下載單檔執行程式並產生 JWT 金鑰妥善保存：

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

建立 `.env` 檔案並替換範例 PIN 和 JWT 金鑰（使用 `openssl rand -hex 32` 的輸出）。單檔程式**不會自動載入** `.env`，啟動前需自行匯入。

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. 啓動服務

直接啟動下載的可執行程式：

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

在另一個終端機檢查狀態：

```bash
curl -i http://127.0.0.1:8765/healthz
```

正常回應為 HTTP `200`。長期執行應使用服務管理程式及受限帳號。

## 3. 暴露 HTTPS

遠端存取建議直接部署在公網伺服器，或以 Caddy、Nginx、Traefik 等 HTTPS 反向代理／連接埠轉送，將完整站點（含上傳與下載）轉送到：

```text
http://127.0.0.1:8765
```

設定 HTTPS 後檢查：

```bash
curl -i https://your-public-host.example.com/healthz
```

**不推薦 Cloudflare Tunnel** 用於大量檔案傳輸：其用戶端上傳可能非常緩慢。條件允許時，優先使用公網伺服器或一般反向代理／轉送。公開端點須啟用 OAuth。Docker 方式見 [Docker 指南](../installation/docker.md)。

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

替換發布的可執行檔後重新啟動 Controller：

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

使用 Docker Compose 則更新容器。原始碼安裝見 [Python/原始碼指南](../installation/python.md)。

```bash
docker compose pull
docker compose up -d
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
