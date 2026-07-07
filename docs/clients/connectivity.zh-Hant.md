# 網絡連通性

機器外部的 HTTP MCP 客戶端需要可訪問的 HTTPS origin。本頁討論網絡路由，不討論選擇哪種運行時。

客戶端端點通常以 `/mcp` 結尾：

```text
https://your-public-host.example.com/mcp
```

服務端的 public base URL 設置只填寫 origin：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

不要在這個 base URL 中包含 `/mcp`。

## 連通性選項

| 選項 | 適用場景 |
|---|---|
| Compose tunnel sidecar | 使用內置 `tunnel` profile 的 Docker Compose |
| 外部隧道 | 任意需要從局域網外訪問的運行時 |
| Caddy | 簡單自動 TLS |
| Nginx 或 Nginx Proxy Manager | 已有 Nginx 基礎設施 |
| Traefik | 已有容器原生路由 |

## 路徑

把整個 origin 轉發到正在運行的服務。重要路徑包括：

| 路徑 | 用途 |
|---|---|
| `/mcp` | MCP streamable HTTP 端點 |
| `/healthz`, `/readyz` | 健康檢查 |
| `/.well-known/...` | 客戶端發現元數據 |
| `/oauth/...` | 客戶端授權流程 |
| `/downloads/...` | 可選的生成文件鏈接 |
| `/join/...`, `/remote/...` | 可選的遠程 worker 流程 |

## 代理行爲

代理應保留路徑、轉發請求體、支持長響應，並避免過短超時。

## 檢查

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## 常見錯誤

| 錯誤 | 修正 |
|---|---|
| 在 ChatGPT 中使用 `https://host` 而不是 `https://host/mcp` | 只在客戶端端點中添加 `/mcp` |
| 設置 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | 只設置 origin |
| 只路由 `/mcp` | 路由整個 origin，確保發現和授權路徑也可用 |
| 在宿主機運行時中使用過寬工作區 | 使用較窄工作區或 Docker |

## 推薦搭配

| 運行時 | 網絡模式 |
|---|---|
| 服務器上的 Docker Compose | 現有反向代理或 Compose tunnel profile |
| 家用機器上的 Docker Compose | 出站隧道 |
| 筆記本上的 VS Code 擴展 | 當前會話臨時隧道 |
| VM 上的二進制 | VM 或網絡邊緣上的反向代理 |
| Python / 源碼開發服務 | 通常只用 localhost |
| stdio 模式 | 無 HTTP 網絡路徑；使用本地 MCP 客戶端 |
