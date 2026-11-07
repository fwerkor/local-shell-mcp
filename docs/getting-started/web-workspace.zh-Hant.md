<!-- i18n-source-sha256: e75cf6e4ffc3fe904983cd63b99b43c2877c4bdd99174b2d4a96393eff5d9e3f -->
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

1. [Install and start an LSM Controller](quickstart.md) 與 OAuth、適當隔離的工作區和持久性 `file` 或 `redis` 狀態儲存。安裝 Docker Compose 並將儲存庫複製到執行 Web 堆疊的主機。
2. 在同一網站上提供**兩個 HTTPS 來源**，例如用於控制器的 `https://lsm.example.org` 和用於工作區的 `https://chat.example.org`。聊天服務不會直接暴露在不受信任的網路上。
3. 使用 `openssl rand -hex 32` 產生一個橋接秘密。使用該金鑰在 **控制器服務** 上配置這些環境變量，然後重新啟動它：

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. 在儲存庫簽出中，配置選購的 Web 堆疊。使用私有環境文件，或匯出如下所示的值；產生獨特的強秘密，並且不要提交它們：

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. 渲染私有配置，然後建置並啟動單獨部署的聊天堆疊：

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

當使用根 Docker Compose 部署時，上面的 Controller 變數屬於根 `.env` 並轉發到容器。聊天服務值可以透過 shell 匯出或私人環境文件提供。控制器容器必須可從指定 Docker 網路上位於 `http://local-shell-mcp:8765` 的聊天容器存取。將 `127.0.0.1:3080` 反向代理連接埠到聊天 HTTPS 來源，保留外部主機，並遵循儲存庫中的 [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md)。 Web 堆疊運行 Node.js、MongoDB、Meilisearch 和 SearXNG；他們**不**包含在工人中。這個單獨的部署不是由儲存庫根目錄中的普通 `docker compose up -d` 啟動的。

## 登入並使用聊天功能

1. 開啟 `https://lsm.example.org/ui`，使用 **LSM Controller** 登入進行驗證，然後依照一次性切換進入 Web 工作區。您無需建立第二個 LibreChat 使用者帳戶。
2. 配置模型提供者。可選的 Web 堆疊預設將 OpenAI、Anthropic 和 Google 憑證公開為 `user_provided`：在聊天端點設定中輸入您自己的提供者金鑰，或在開始之前在聊天 Compose 環境中設定 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 或 `GOOGLE_KEY`。在聊天中選擇支援的型號。 **LSM 不包含模型或 API 積分。 ** Gemini Spark 的外部 MCP 連接與此處配置 Gemini 模型是分開的。
3. 創建對話。預設啟用 Web 搜尋和 LSM 工具，但需遵守控制器權限。根據需要使用每個對話 **Web**、**LSM**、**外部 MCP** 和 **記憶體** 控制項。
4. 從唯讀請求開始：“檢查控制器狀態並列出工作空間根目錄。請勿修改文件。”
5. 導航至**文件**、**終端**、**桌面**、**會話**、**遠端**或**審核**以進行直接檢查和控制。

聊天上傳（最多 32 MiB）儲存在控制器工作區下，並且它們的絕對路徑提供給模型。瀏覽器上傳不會授予額外的檔案權限。模型導向的工具呼叫透過 LSM 授權、稽核和遠端工作路由器。

## 外部 MCP、安全性和數據

使用工作區 MCP 側邊欄管理嵌套的外部 MCP 伺服器。這支援本機 stdio 伺服器和 HTTP 伺服器，包括單獨的私人環境變數和請求標頭。秘密不會返回瀏覽器。 **外部 MCP** 聊天切換允許搜尋、檢查和呼叫嵌套工具；當本機 LSM 工具停用時，它不會授予模型 `mcp_manage`。 UI 管理受到正常控制器授權的保護。

聊天訊息、專案和檔案儲存在伺服器端 Web 堆疊的 MongoDB 中；搜尋使用美麗搜尋。 Controller分別擁有工具權限、Worker身分、會話狀態和稽核。如果需要保留所有歷史記錄，請備份兩個資料儲存。聊天後台是LSM登入下的單一使用者；不要向公眾公開其內部 API 或資料庫。

UI 是頂級應用程序，**不是 iframe**。如果未配置選用聊天服務，`/ui` 將繼續為原始 LSM WebUI 提供服務。本機 OpenTUI 和外部客戶端仍然受支援。

## 故障排除

- **重定向保留在原始 UI 上：** 檢查 `LOCAL_SHELL_MCP_LIBRECHAT_URL`、持久控制器狀態後端和 Web 堆疊的 HTTPS 反向代理。
- **登入或切換失敗：**驗證雙方完全相同的 32 位元組或更長的橋接密鑰，匹配相同站點的來源、HTTPS 和伺服器時鐘。
- **聊天載入但無法應答：**設定實際模型端點或 API 憑證並檢查聊天容器日誌。
- **缺少 MCP 工具：** 驗證控制器範圍和每個對話切換；巢狀伺服器登錄與 LibreChat MCP 資料庫是分開的。
- **檔案或會話顯示為空：**驗證聊天是否到達正確的控制器和工作區，並檢查其 API 驗證日誌。

有關實現詳細資訊和更新，請參閱 [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) 和 [human interface guide](../guides/human-interface.md)。
