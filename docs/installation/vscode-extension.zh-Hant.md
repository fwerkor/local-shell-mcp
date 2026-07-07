# VS Code 擴展運行時

VS Code 擴展是同一個 `local-shell-mcp` 服務的啓動器和便捷 UI。它屬於運行時選擇，因爲它會爲當前編輯器工作區啓動服務進程。

它不是 ChatGPT 連接器本身。從 ChatGPT 網頁或 App 使用時，ChatGPT 仍然連接公開 HTTPS `/mcp` 端點。

## 擴展做什麼

擴展會：

- 爲當前 VS Code 工作區啓動 `local-shell-mcp`。
- 停止和重啓服務。
- 在 VS Code output channel 中顯示服務輸出。
- 檢查 `/healthz`。
- 複製 MCP URL。
- 複製包含工作區和端點信息的 ChatGPT 設置提示詞。

擴展不內置服務二進制。需要先單獨安裝 `local-shell-mcp`，如果它不在 `PATH` 中，再把擴展指向該可執行文件。

## 何時使用

適合使用這個運行時的情況：

- 你通常從 VS Code 文件夾開始工作。
- 你想使用按鈕或命令面板流程，而不是手動啓動終端命令。
- 項目依賴已經安裝在宿主機上。
- 你處理的是可信倉庫或範圍很窄的工作區。
- 你接受只把該工作區暴露給模型。

更適合使用 Docker 的情況：

- 倉庫不可信。
- 任務會安裝任意包。
- 任務需要較完整的預裝工具鏈。
- 你希望通過重建容器輕鬆重置環境。
- 你希望比宿主機賬號更清晰的邊界。

## 安裝可執行文件

選擇一種服務安裝方式：

```bash
pipx install local-shell-mcp
```

或者下載適合你係統的 release 二進制，並把它放到 `PATH`。

然後安裝 VSIX release 資產：

```bash
code --install-extension local-shell-mcp-vscode-<version>.vsix
```

也可以在命令面板中使用 **Extensions: Install from VSIX...**。

## 擴展設置

| 設置 | 用途 | 常見值 |
|---|---|---|
| `local-shell-mcp.executablePath` | 服務可執行文件路徑 | `local-shell-mcp` 或絕對二進制路徑 |
| `local-shell-mcp.host` | 本地服務綁定地址 | 本地使用 `127.0.0.1`；只在受控網絡或代理後使用 `0.0.0.0` |
| `local-shell-mcp.port` | 本地服務端口 | `8765` |
| `local-shell-mcp.workspaceRoot` | 暴露給 MCP 的工作區 | 留空表示第一個 VS Code 文件夾，或填寫明確路徑 |
| `local-shell-mcp.authMode` | 認證模式 | ChatGPT 使用 `oauth`；可信 localhost 測試才用 `none` |
| `local-shell-mcp.publicBaseUrl` | 複製到提示詞和 URL 中的公開 HTTPS origin | 例如 `https://mcp.example.com` |
| `local-shell-mcp.oauthAdminPin` | OAuth 授權 PIN | 公開使用時設置強隨機值 |
| `local-shell-mcp.allowFullContainer` | full-container 行爲開關 | 直接宿主機使用時保持 `false` |
| `local-shell-mcp.extraEnv` | 服務進程額外環境變量 | 只放項目所需且安全的值 |

## 基本流程

1. 在 VS Code 中打開項目文件夾。
2. 運行 **local-shell-mcp: Start Server**。
3. 運行 **local-shell-mcp: Show Server Status**，或在可用時運行 **Check Health**。
4. 對本地 MCP 客戶端運行 **local-shell-mcp: Copy MCP URL**；對 ChatGPT 運行 **Copy ChatGPT Setup Prompt**。
5. 把端點添加到客戶端。

本地端點通常類似：

```text
http://127.0.0.1:8765/mcp
```

這對本地客戶端有用，但 ChatGPT 網頁或 App 無法訪問。

## 與 ChatGPT 一起使用

如果要讓 ChatGPT 使用 VS Code 啓動的服務，需要在本地端口前面添加 HTTPS 隧道或反向代理。

示例結構：

```text
ChatGPT
  -> https://your-public-host.example.com/mcp
  -> 隧道或反向代理
  -> 你機器上的 127.0.0.1:8765
  -> VS Code 啓動的 local-shell-mcp 進程
```

設置：

```text
local-shell-mcp.publicBaseUrl = https://your-public-host.example.com
local-shell-mcp.authMode = oauth
local-shell-mcp.oauthAdminPin = <strong pin>
```

複製給 ChatGPT 的 URL 應以 `/mcp` 結尾：

```text
https://your-public-host.example.com/mcp
```

## 宿主機運行時安全

擴展通常以你的宿主機用戶身份運行命令。這和一次性 Docker 容器有實質區別。

推薦規則：

- 只打開你希望模型控制的倉庫。
- 保持 `allowFullContainer` 關閉。
- 不要把 workspace root 設爲 home 目錄。
- 不要在工作區中保留無關密鑰。
- 提交和推送前使用 `secret_scan`。
- 對陌生倉庫或需要大量安裝包的任務優先使用 Docker。

## 常用提示詞

複製設置提示詞後，先從只讀任務開始：

```text
使用 local-shell-mcp。先調用 environment_info，並對工作區調用 tree_view。暫時不要修改文件。
```

然後再進入有邊界的編輯任務：

```text
修復這個工作區中的失敗測試。先讀取相關文件，做最小補丁，運行定向測試，並展示 git diff。未經我批准不要提交。
```

## 故障排查

| 現象 | 檢查 |
|---|---|
| 擴展無法啓動服務 | 確認 `local-shell-mcp.executablePath` 存在，並能在終端中運行 `--help` |
| ChatGPT 無法訪問 | 本地 `127.0.0.1` URL 不是公網地址；配置隧道或代理並設置 `publicBaseUrl` |
| 工具暴露了錯誤文件夾 | 顯式設置 `local-shell-mcp.workspaceRoot` |
| 重啓後認證失敗 | 通過 `extraEnv` 或運行時配置設置穩定的 OAuth admin PIN 和 JWT secret |
| 命令缺少依賴 | 在宿主機安裝依賴，或切換到 Docker 運行時 |
