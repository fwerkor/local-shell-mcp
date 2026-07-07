# ChatGPT 連接器

本頁說明如何把 ChatGPT 作爲客戶端接入。它不負責選擇運行時。使用本頁前，先通過 Docker、VS Code 擴展、獨立二進制或 Python 安裝方式啓動 `local-shell-mcp` 服務。

`local-shell-mcp` 面向 ChatGPT Developer Mode 和完整 MCP 客戶端設計。同時，它也提供只讀的連接器式 `search` 和 `fetch` 工具，便於客戶端發現文件內容。

## 運行時前置條件

先選擇並啓動一個運行時：

| 運行時 | 頁面 |
|---|---|
| Docker Compose | [Docker Compose 運行時](../installation/docker.md) |
| VS Code 擴展 | [VS Code 擴展運行時](../installation/vscode-extension.md) |
| 獨立二進制 | [獨立二進制運行時](../installation/binary.md) |
| Python / pipx / 源碼 | [Python 運行時](../installation/python.md) |

然後通過 ChatGPT 可訪問的網絡路徑暴露這個運行時。網絡入口與反向代理要求見 [網絡連通性](../clients/connectivity.md)。

## 公共 URL

ChatGPT 必須通過 HTTPS 訪問服務。MCP 端點是：

```text
https://your-public-host.example.com/mcp
```

確保 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 只填寫公開源站地址：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

不要在 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 後面追加 `/mcp`。

## OAuth 設置

公開部署建議使用以下配置：

```env
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<long random value>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<long random value>
LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S=0
```

訪問令牌默認不會自動過期，因爲較長的編程會話可能超過短令牌壽命。需要撤銷訪問時，可以輪換 JWT secret，或使用全新的狀態重新部署。

## 添加連接器

1. 打開 ChatGPT 的連接器設置或 Developer Mode 的 MCP 設置。
2. 添加自定義 MCP 服務器。
3. 輸入 MCP URL：`https://your-public-host.example.com/mcp`。
4. 完成 OAuth 授權。
5. 審覈並批准工具列表。

## 第一次提示詞

```text
使用 local-shell-mcp。先調用 environment_info，然後列出工作區根目錄。暫時不要修改文件。
```

這個提示只驗證連通性，不會主動修改文件。

## 推薦操作規則

給模型明確邊界：

- 除非另有說明，只在 `/workspace` 內工作。
- 提交前先運行測試。
- 推送前使用 `secret_scan`。
- 只對可以分享的文件使用 `create_file_link`。
- 長時間進程優先使用持久 shell session。
- 彙總所有修改過文件的命令。

## 工具發現問題

如果 ChatGPT 能完成認證，但沒有顯示預期工具：

- 確認端點以 `/mcp` 結尾。
- 檢查 `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY`。
- 檢查反向代理請求頭與請求體大小限制。
- 查看 `docker compose logs --tail=200 local-shell-mcp`。
- 確認服務運行在 `mcp` 或 `both` 模式。

## 安全說明

公開部署應保持 OAuth 開啓。不要在公網暴露未認證的完整 MCP 工具。每個被批准的工具都應視爲已接入模型實際權限的一部分。
