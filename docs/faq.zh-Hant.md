# 常見問題

本頁整理一些反覆出現的 Client 與反向代理問題。這些問題看起來像 LSM 服務故障，但服務端本身通常正常。

## 為什麼升級 LSM 後，ChatGPT 中有些工具無法使用？

### 現象

- ChatGPT 中看不到新增工具。
- ChatGPT 仍嘗試呼叫已刪除、重新命名或合併的舊工具。
- 工具仍存在，但 ChatGPT 使用舊參數結構，導致呼叫驗證失敗。
- 重新啟動 LSM 或建立新對話後問題仍存在。

### 原因

ChatGPT 可能會保存 MCP App 在掃描、核准或發佈時的工具與輸入參數凍結快照。LSM 新版本修改 `tools/list` 後，這份已保存的快照不保證自動重新整理。這不是一個有明確到期時間的短期快取。

### 解決方法

=== "開發者模式或個人連線"

    1. 開啟 **ChatGPT 設定 → Apps**。
    2. 進入 LSM App，使用 **Refresh** 重新掃描工具。
    3. 如果沒有 Refresh，刪除舊 App，再使用同一個 MCP 位址重新加入。
    4. 接受新工具清單後，建立新對話再使用 LSM。

=== "ChatGPT Business 已發佈 App"

    目前已發佈的自訂 App 無法原地更新工具或中繼資料。工作區管理員需要建立新 App、掃描目前的 LSM 位址、發佈替代版本，然後停用舊 App。

=== "ChatGPT Enterprise 或 Edu"

    工作區管理員可以進入 **Workspace Settings → Apps → LSM App → … → Action control → Refresh**，審查差異，並視需要啟用新發現的 action。

請參閱 [Issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) 與 [OpenAI MCP App 文件](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)。

## 為什麼透過 Nginx 反向代理 LSM 後，WebUI 一直重新連線？

### 現象

- WebUI 頁面與 OAuth 登入都能正常開啟。
- TUI 始終不顯示。
- 連線狀態不斷在 `Connecting`、`Connection error` 與 `Reconnecting` 之間變化。
- 直接連線 `8765` 連接埠時一切正常。

### 原因

瀏覽器介面透過 PTY WebSocket 呈現原生 TUI。預設端點是 `/ui/ws`；若自訂 `ui_path`，端點就是 `${ui_path}/ws`。一般的 Nginx `proxy_pass` 不會自動轉送 WebSocket 協定升級所需的 hop-by-hop 標頭。

### 解決方法

啟用 HTTP/1.1，並轉送 `Upgrade` 與 `Connection` 標頭：

```nginx
# 將 map 放在 http 區塊中。
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

修改設定後，檢查並重新載入 Nginx：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

若使用 Nginx Proxy Manager，請在對應的 Proxy Host 啟用 **Websockets Support**。若仍不斷重新連線，請在 Advanced 設定中加入等效的協定升級標頭。

### 驗證

開啟瀏覽器開發者工具，重新載入 WebUI，並檢查 `/ui/ws` 請求。正常連線應回傳：

```text
101 Switching Protocols
```

請參閱 [Issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71)。
