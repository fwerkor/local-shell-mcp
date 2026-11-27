<!-- i18n-source-sha256: 0d50677fe8bd21dbf6f3fff366adea800f15d50fdbc67ed3b77abf84437f73eb -->
# 連接 Gemini Task / 自訂應用程式

Gemini 的 **自訂連線應用程式** 功能允許符合條件的 Gemini 使用者連接遠端 MCP 伺服器。 LSM 可以提供 MCP 端點。這是到 [unified web workspace](web-workspace.md)、[ChatGPT](chatgpt-connector.md) 和其他 MCP 客戶端的**替代客戶端連接**；它不會替換或部署 LSM 控制器。

Google 目前將自訂應用程式限制為**年滿 18 歲的美國用戶**、使用**個人 Google 帳戶**登入並**保持活動啟用**。該功能以**英語**提供。連接必須在 Gemini Web 應用程式上創建，儘管連接的應用程式稍後可以在行動裝置上使用。可用性和 UI 標籤可能會變更；請參閱 [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137)。

## 連接前

- 啟動 LSM 運行時（例如使用 [Docker Compose](../installation/docker.md)），並驗證其運作狀況。
- 透過**可公開存取的 HTTPS** 公開其 MCP 端點並保持 OAuth 啟用。
- 了解控制器的身份驗證詳細資訊並僅批准您需要的範圍。
- 使用受限的工作空間或容器。雙子座可能會要求對文件、機器和終端機產生實際影響的操作。

在 Gemini 中輸入的端點是：

```text
https://your-public-host.example.com/mcp
```

請勿輸入 Web UI (`/ui`)、LibreChat URL 或不含 `/mcp` 的網站來源。公共部署不應停用身份驗證來解決連線錯誤。

## 連接雙子座

1. 在電腦上，開啟 [Gemini](https://gemini.google.com/) 並使用符合條件的個人帳戶登入。
2. 開啟 **設定和幫助 → 連接的應用程式**。根據目前介面，它可能位於**個人智慧 → 連接的應用程式**下。
3. 在 **自訂應用程式** 下，選擇 **新增自訂應用程式** 或使用自訂應用程式 URL 欄位。
4. 貼上 LSM HTTPS `/mcp` URL，然後選擇 **下一步**。
5. 使用 LSM 控制器完成 OAuth 和同意流程。 LSM 支援 OAuth 發現和動態用戶端註冊。如果 Gemini 請求手動 OAuth 用戶端憑證，請在繼續之前檢查其進階選項和 LSM OAuth 設定。
6. 在 Gemini 對話中，輸入 `@` 並選擇連接的自訂應用程式以請求 LSM 工具。

首先：「使用連接的 LSM 應用程式檢查環境並列出工作區文件。請勿修改任何內容。」在嘗試寫入操作之前檢查工具結果和控制器審核。

## 使用 Task 模式（原 Spark）

對於多步驟程式開發、除錯或伺服器維護，建議優先使用 **Task**：它可以規劃工作、反覆呼叫已連接的工具，並在任務對話中展示進度。這是工作流程建議，不代表經實測的速度或品質保證。

在 Gemini 首頁輸入框下方選擇 **Task**，依提示完成首次設定。輸入 `@`，若顯示 LSM 自訂應用程式則選取它，並提交明確目標、目標機器或工作區及完成條件。

範例：「使用 LSM 檢查儲存庫、重現失敗測試、修正根因並重新執行測試。回報修改的檔案及測試結果。」

查看任務進度並按需確認操作。透過 Controller 稽核記錄確認 LSM 工具確實被呼叫：Gemini 自身的雲端電腦並非你的 LSM 工作區。保持 Controller 與必要 Worker 上線。Task 與自訂應用程式的開放條件不同；若任一入口缺失，請查看 [Task 官方指南](https://support.google.com/gemini/answer/17094507)。

## 限制和故障排除

- **無自訂應用程式選項：** 確認帳戶、地區、年齡、語言和保留活動資格。這是 Gemini 端的可用性限制，而不是 LSM 設定錯誤。
- **URL 被拒絕：** 使用外部可存取的 HTTPS `/mcp` 端點；檢查 OAuth 發現和您的反向代理。
- **OAuth 失敗：** 檢查 LSM 授權畫面、用戶端註冊、回呼 URL 和授予的範圍。請勿發布未經身份驗證的 MCP 端點。
- **工具遺失或失敗：** 用戶端 MCP 工具/架構支援可能有所不同。嘗試一個簡單的唯讀呼叫並檢查 LSM 審核和日誌；不保證與每個 Gemini 用戶端功能完全相容。
- **斷開連接：**當不再需要時，返回**連接的應用程式**以停用、取消連結或刪除 LSM。

Google 的 [official guide](https://support.google.com/gemini/answer/17209137) 描述了最新的自訂應用程式流程和可用性。基於 CLI 的本地 Gemini 集成，請參閱 [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/)。 LSM [ChatGPT connector tutorial](chatgpt-connector.md) 仍然獨立可用。
