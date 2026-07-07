# 快速開始

本頁把 Docker Compose 作爲第一個運行時，把 ChatGPT 作爲第一個客戶端。兩者是獨立選擇：Docker、VS Code 擴展、二進制、Python 和 stdio 是運行時；ChatGPT 和通用 MCP 客戶端是接入方式。完整關係見 [運行時與客戶端模型](../guides/deployment.md)。

## 要求

- Docker Engine 與 Compose v2。
- 如果 ChatGPT 需要從公網訪問，需要一個公開 HTTPS 端點。
- 一個專用工作區目錄。
- 較長的隨機 OAuth 管理 PIN 和 JWT 密鑰。

!!! warning
    接入的模型可以操作配置的工作區。建議在一次性容器或虛擬機中運行服務，並避免掛載宿主機控制資源。

## 1. 克隆並配置

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
```

編輯 `.env`：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
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

如果使用 Cloudflare Tunnel sidecar：

```bash
docker compose --profile tunnel up -d
```

在 Cloudflare Zero Trust 中，把公開 hostname 指向：

```text
http://local-shell-mcp:8765
```

如果使用 Caddy、Nginx、Traefik、Nginx Proxy Manager 或其它反向代理，把 HTTPS 流量轉發到 `127.0.0.1:8765` 或容器網絡地址。

## 4. 連接 ChatGPT

MCP 端點爲：

```text
https://your-public-host.example.com/mcp
```

按照 [ChatGPT 連接器](chatgpt-connector.md) 完成 OAuth 和工具授權。

## 5. 安全確認工具訪問

先讓模型執行：

```text
Use local-shell-mcp. First call environment_info, then list the workspace root. Do not modify files yet.
```

預期只讀工具包括：

- `environment_info`
- `list_files`
- `tree_view`
- `read_file`

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
| 添加 ChatGPT 客戶端 | [ChatGPT 連接器](chatgpt-connector.md) |
| 選擇工具並寫更好的提示詞 | [使用模式](../guides/usage-patterns.md) |
| 連接 HPC、NPU/GPU 或 NAT 機器 | [遠程節點](../guides/remote-workers.md) |
| 理解每一個 MCP 工具 | [工具參考](../reference/tools.md) |
