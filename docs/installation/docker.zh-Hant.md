# Docker Compose 運行時

Docker Compose 是大多數用戶的推薦運行時。它爲模型提供受控 Linux 工作區、可重複工具鏈、持久憑據、瀏覽器自動化支持，以及簡單的升級路徑。

這是運行時選擇。它可以接入 ChatGPT、通用 HTTP MCP 客戶端，也可以只在本地測試。

## Docker 鏡像包含什麼

鏡像基於 Playwright Python 鏡像，並安裝較完整的開發工具鏈。目標是讓 AI 編程代理能夠處理許多倉庫，而不必爲每個項目重新構建運行時。

包含的類別：

| 類別 | 示例 |
|---|---|
| Shell 與檢查 | Bash、curl、wget、jq、ripgrep、tree、tmux、patch、file |
| Git 與憑據 | Git、GitHub CLI、OpenSSH client、憑據持久化卷 |
| C/C++ 構建 | build-essential、clang、cmake、ninja、autoconf、automake、gdb、lldb |
| Python | Python、pip、venv、pipx、包開發依賴 |
| JavaScript/TypeScript | Node.js、npm、yarn、pnpm、TypeScript、ts-node |
| 其它語言 | Go、Rust、Java、Ruby、PHP、Perl、Lua、R |
| 瀏覽器自動化 | Playwright 瀏覽器和瀏覽器依賴 |
| 文檔工具 | LibreOffice、Pandoc、Poppler 工具、OCR 工具 |

鏡像內容應視爲便利層，而不是穩定 API。項目特定依賴仍應放在工作區或項目構建腳本中。

## 基礎本地運行

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

默認 Compose 文件把服務綁定到 localhost：

```text
127.0.0.1:8765 -> container:8765
```

這適合本地測試，也適合同一主機上的反向代理。

## 工作區佈局

默認 Compose 運行時掛載：

| 宿主機路徑或卷 | 容器路徑 | 用途 |
|---|---|---|
| `./workspaces/default` | `/workspace` | 工具可見的受控工作區 |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | 持久 Git / GitHub / SSH / GPG 風格憑據狀態 |

每個信任邊界使用一個工作區目錄。不要只爲圖方便就把整個 home 目錄作爲工作區。

## 公開訪問所需設置

對於 ChatGPT 或其它公開 HTTP MCP 客戶端，在 `.env` 中配置：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

可以用下面的命令生成 JWT secret：

```bash
openssl rand -hex 32
```

公開 MCP URL 是：

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose 文件包含一個可選的 `cloudflared` 服務，放在 `tunnel` profile 後面。它會把隧道與 MCP 服務放在同一套 Compose 中運行。

配置 `.env`：

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

啓動兩個服務：

```bash
docker compose --profile tunnel up -d
```

在 Cloudflare Zero Trust 中，把公開 hostname 路由到：

```text
http://local-shell-mcp:8765
```

這是 Cloudflare Tunnel，不是 Cloudflare Access。`local-shell-mcp` 仍然自己處理 ChatGPT 的 OAuth。

## 不使用 tunnel sidecar 的反向代理

如果你已經運行 Caddy、Nginx、Traefik 或 Nginx Proxy Manager，保留普通 Compose 服務，並把 HTTPS 轉發到：

```text
http://127.0.0.1:8765
```

代理必須原樣轉發這些路徑，不能剝離路徑前綴：

| 路由 | 用途 |
|---|---|
| `/mcp` | MCP streamable HTTP 端點 |
| `/healthz`, `/readyz` | 健康檢查 |
| `/.well-known/oauth-protected-resource` | OAuth resource 元數據 |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server 元數據 |
| `/oauth/register` | 動態客戶端註冊 |
| `/oauth/authorize` | 瀏覽器授權頁面 |
| `/oauth/token` | token 交換 |
| `/downloads/<token>` | 可選的生成文件下載 |
| `/join/<token>`, `/remote/*` | 可選的遠程 worker 引導和輪詢 |

代理行爲要求見 [網絡連通性](../clients/connectivity.md)。

## Full-container 模式

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` 會把文件系統操作限制在工作區內。這是更安全的默認行爲。

只有當容器是有意設計爲一次性環境，且模型需要操作整個容器文件系統時，才設置爲 `true`。啓用後，內置命令和路徑 denylist 限制會被移除。

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

不要在 VS Code 擴展或直接運行在筆記本上的二進制這類宿主機運行時中啓用 full-container 模式。

## 憑據

Docker 運行時可以在專用 volume 中持久化常見開發者憑據。這對 GitHub CLI 登錄、Git HTTPS credential helper、`.netrc`、SSH 配置和 GPG 狀態很有用。

把憑據 volume 視爲敏感資源。優先使用倉庫級 deploy key、細粒度 token 或短期憑據。不要把權限過大的個人憑據放進模型可自由讀取的工作區。

也可以通過掛載 SSH agent socket 來轉發 SSH agent，但這會把容器信任擴展到當前活動 agent。只在理解暴露面時使用。

## 更新

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

使用 tunnel sidecar 時：

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

升級後，先讓客戶端執行只讀檢查：

```text
使用 local-shell-mcp。調用 environment_info，並對工作區根目錄調用 list_files。不要修改文件。
```

## 故障排查

| 現象 | 檢查 |
|---|---|
| 本地 `/healthz` 失敗 | `docker compose ps`、`docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT 無法發現工具 | 公開 URL 必須以 `/mcp` 結尾；`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 不能包含 `/mcp` |
| OAuth 頁面失敗 | 公開 OAuth 部署必須設置 admin PIN 和 JWT secret |
| 工具看不到文件 | 確認目標宿主機目錄已掛載到 `/workspace` |
| 瀏覽器工具失敗 | 確認 Playwright 鏡像是最新的；可對目標瀏覽器嘗試 `run_shell_tool` |
| Git 認證消失 | 檢查憑據 volume，以及重建容器時是否使用了同一個 volume |
