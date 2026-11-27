<!-- i18n-source-sha256: 6c9270cab0f3c147ed3790b5042770b1c949119bd63f60b171b4647fb16850ef -->
# WebUI Chat 快速入門

統一 LSM Web 工作區整合 AI 聊天、專案、智慧體與 Controller 運維頁面，由 Python Controller 提供服務，共享其認證和 SQLite 資料庫，無需獨立聊天伺服器。仍支援 [ChatGPT](chatgpt-connector.md)、[Gemini](gemini-spark.md) 等外部 MCP 客戶端。

## 1. 啟動 Controller

按照[安裝快速入門](quickstart.md)選擇部署方式。確認 WebUI 已啟用並使用持久化儲存。以下為正常預設值：

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

匯出服務環境變數後，啟動 Controller：

```sh
local-shell-mcp --mode mcp
```

單檔案發行版使用下載的可執行檔案。已安裝的 Controller 提供編譯好的前端，僅原始碼構建需要 JavaScript 工具鏈。參見[WebUI 構建說明](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md)。

## 2. 開啟瀏覽器工作區

在 Controller 主機訪問 `http://127.0.0.1:8765/ui`，遠端訪問時使用已配置的 HTTPS 地址及 `/ui` 路徑。透過部署中配置的 LSM 認證登入。遠端訪問應使用經過認證的 HTTPS。聊天與控制面頁面共享同一源地址。

## 3. 新增模型渠道

開啟模型選擇器及渠道管理。新增 API 渠道或連線受支援的賬戶。對於典型 OpenAI 相容端點，填寫渠道名稱、選擇 Chat Completions 協議、填寫 API Base URL 和憑證，再自動發現模型或手動填寫已知模型 ID。儲存配置並選擇模型。

本地推理服務的地址必須能被 Controller 訪問，而非僅瀏覽器可訪問。例如，若推理服務在 Controller 網路名稱空間內監聽對應地址，則可填寫 `http://127.0.0.1:8080/v1`。協議、賬戶授權、自動發現和視窗限制詳見[渠道與模型](../chat/channels.md)。

## 4. 執行第一個任務

新建會話並提出簡單問題，驗證模型連線。隨後嘗試只讀工具請求：

```text
列出 Controller 工作區根目錄中的檔案。
告訴我檢查的是哪臺機器，並總結結果。
不要修改檔案或執行任何寫操作。
```

檢視實際工具結果。如果工具缺失，檢查聊天工具開關、智慧體設定及機器許可權。重複任務可使用已儲存的智慧體，並明確配置其訪問許可權。參見[工具與許可權](../chat/permissions.md)。

## 5. 探索工作區

| 區域 | 用途 |
|---|---|
| 聊天與專案 | 新建和搜尋會話、整理專案、標籤和訊息書籤 |
| 智慧體 | 複用模型、指令及工具配置 |
| 記憶與 Skill | 管理可複用知識與指令 |
| 定時會話 | 使用週期性提示詞執行已儲存智慧體 |
| 檔案與終端 | 檢查或操作 Controller 和 Worker 環境 |
| 桌面 | 檢查和控制支援的遠端 GUI 會話 |
| Session、Job 與審計 | 檢視持久任務、執行進度及工具活動 |
| 機器與外部 MCP | 管理 Worker 與巢狀 MCP 伺服器 |

具體控制元件取決於部署、賬戶和啟用能力。關閉瀏覽器不會自動取消服務端推理；需要中斷時應使用停止控制元件。

## 後續閱讀

完整工作流程參見 [WebUI Chat 指南](../chat/index.md)，生產部署、備份與錯誤恢復參見[管理與故障排查](../chat/administration.md)。
