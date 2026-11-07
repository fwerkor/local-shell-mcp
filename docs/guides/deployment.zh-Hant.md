<!-- i18n-source-sha256: d7d01bc3f36f434c8e66c3fb6f65c2934937c5b2937dd9e8ba7beefc018fd14f -->
# 運行時選擇與部署模型

`local-shell-mcp` 有兩個互補的決定：

1. **運行時**：服務進程如何運行，以及它控制哪個工作區。
2. **介面**：使用可選的 [unified web workspace](../getting-started/web-workspace.md)，或連接外部 MCP 用戶端，例如 Gemini 或 ChatGPT。

建議的日常介面是自架網站 Web 工作區（聊天、專案和 LSM 控制頁面）。它與控制器分開部署。 Docker、VS Code 擴充功能、發布二進位檔案、Python 安裝和 stdio 模式都是運行控制器的方式；外部聊天應用程式仍然是可選用戶端。

```text
運行時層                         暴露層                         客戶端層
-------------------------------  -----------------------------  ----------------------
Docker Compose 僅本地 HTTP 統一 Web 工作區
VS Code 擴展                     HTTPS 反向代理 / 隧道          通用 MCP 客戶端
獨立二進制                       stdio 進程管道                 VS Code 擴展 UI
pipx / 源碼 checkout             遠程 worker 出站加入           REST 風格診斷接口
```

常見的自架設定是：

```text
瀏覽器 -> https://chat.example.com（統一網路工作區）
        -> 經過驗證的 local-shell-mcp 控制器
        -> 受控工作區與外派員工
可選外部客戶端 -> https://mcp.example.com/mcp
```

本地 MCP 客戶端可以更簡單：

```text
本地 MCP 客戶端
  -> 啓動 local-shell-mcp --mode stdio
  -> 受控工作區
```

**推薦：** 有條件時，應直接部署到具有公網位址的伺服器，或透過公網伺服器搭配 HTTPS 反向代理轉發流量。 **不推薦：** Cloudflare Tunnel 用戶端的上傳速度可能非常慢，導致檔案上傳與傳輸功能難以正常使用。僅在無法進行公網部署或透過公網伺服器轉發時，才考慮作為備選方案。 （[公開 HTTPS 暴露](../clients/connectivity.md)）

## 運行時選擇矩陣

| 運行時 | 最適合 | 隔離邊界 | 工具鏈源碼 | 外部 MCP 訪問 | 頁面 |
|---|---|---|---|---|---|
| **原始碼 checkout（最推薦）** / `pipx` | Python 原生使用、調試、開發 | 宿主機 virtualenv 或 VM | Python 包加宿主機工具 | 添加 HTTPS 代理或隧道 | [Python 安裝](../installation/python.md) |
| Docker 組合 | 一次性隔離容器與可重建工作區 | 貨櫃 | 精實控制器形象；單獨安裝特定於任務的工具鏈 | 新增 HTTPS 代理或隧道 | [Docker Compose](../installation/docker.md) |
| Docker Compose + 隧道 sidecar | 不推薦: 透過公網伺服器轉發；Cloudflare Tunnel 僅作備選 | 貨櫃 | 項目形象 | 透過公網伺服器轉發；Cloudflare Tunnel 僅作備選 | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code 擴展 | 從編輯器工作區啓動或停止服務 | 通常是宿主機進程 | 宿主機工具，以及配置的可執行文件 | 爲 ChatGPT 添加外部 HTTPS 隧道或代理 | [VS Code 擴展](../installation/vscode-extension.md) |
| 獨立二進制 | Docker 不可用，但已有 VM、容器宿主機或專用賬號作爲邊界 | 宿主機或 VM | 宿主機工具 | 添加 HTTPS 代理或隧道 | [獨立二進制](../installation/binary.md) |
| stdio 模式 | 由本地 MCP 客戶端直接拉起工具進程 | 客戶端進程邊界 | 宿主機工具 | ChatGPT 網頁或 App 不能直接使用 | [stdio 模式](../installation/stdio.md) |

## 客戶端連接矩陣

| 介面 | 需要公共 HTTPS | 使用 `/mcp` | 需要 OAuth | 典型運行時間 |
|---|---:|---:|---:|---|
| 統一 LSM Web 工作區 | 是的，用於遠端存取；也可以使用本地代理 | 內部 | LSM登入 | 控制器加上獨立的網路堆疊 |
| Gemini Spark / 自訂應用程式 | 是的 | 是的 | 是的，供大眾使用 | 任何 HTTP 控制器 |
| ChatGPT 自定義 MCP 連接器 | 是 | 是 | 公網使用時需要 | Docker、VS Code 擴展、二進制或 Python |
| 通過 stdio 的通用本地 MCP 客戶端 | 否 | 否 | 否 | `local-shell-mcp --mode stdio` |
| 通用 HTTP MCP 客戶端 | localhost 通常不需要；跨網絡需要 | 是 | localhost 之外建議開啓 | 任意 HTTP 運行時 |
| VS Code 擴展輔助流程 | 只有 ChatGPT 需要連接時才需要 | 複製 ChatGPT URL 時使用 | 用於 ChatGPT 時建議開啓 | VS Code 啓動的運行時 |

請參閱 [unified web workspace](../getting-started/web-workspace.md)、[Gemini Spark](../getting-started/gemini-spark.md)、[ChatGPT connector](../getting-started/chatgpt-connector.md)、[generic MCP clients](../clients/generic-mcp.md) 和 [network connectivity](../clients/connectivity.md)。

## 每種運行時控制什麼

每種運行時都會啓動同一套服務代碼，並在啓用時暴露同樣的 MCP 工具族：

- Shell 和持久 shell session。
- 文件系統、搜索和補丁工具。
- Git 操作。
- 基於 Playwright 的瀏覽器自動化。
- 審計日誌和任務狀態工具。
- 帶 token 的文件鏈接。
- 可選的遠程 worker 生命週期和遠程工具。

區別不在抽象 API，而在 API 背後的**操作環境**。

| 問題 | Docker Compose | VS Code 擴展 | 二進制 / Python |
|---|---|---|---|
| 命令在哪裏運行？ | 容器內 | 通常在宿主機工作區 | 宿主機或 VM 的進程環境 |
| 默認工作區是什麼？ | 掛載的 `/workspace` | 當前 VS Code 文件夾或配置路徑 | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| 是否預先安裝了編譯器和瀏覽器？ | 不;安裝任務所需的內容 | 僅當安裝在主機上時 | 僅當安裝在主機上時 |
| 是否容易重置？ | 刪除並重建容器和工作區卷 | 取決於工作區 | 取決於宿主機或 VM |
| 是否適合任意包安裝？ | 如果是一次性環境，適合 | 直接宿主機上風險更高 | 除非在 VM 中，否則風險更高 |

## 推薦選擇

**最推薦直接從原始碼儲存庫部署** Controller，並使用隔離的 VM、容器或受限帳號。參見 [Python/原始碼安裝指南](../installation/python.md)。Docker Compose 適合一次性隔離環境。

當工作流程從編輯器啟動並且您需要本機啟動器時，請使用 **VS Code 擴充功能**。它仍然是一個運行時。遠端 Web 用戶端需要可存取的 HTTPS 代理或隧道。

當 Docker 不可用，但已有 VM、容器宿主機或專用用戶賬號提供邊界時，使用**獨立二進制**。

當你在開發或調試 `local-shell-mcp` 本身，或 Python 環境更容易維護時，使用 **`pipx` 或源碼安裝**。

**stdio 模式**只適合能夠啓動服務進程的本地 MCP 客戶端。它不是公開部署方式，也不能被 ChatGPT 網頁或 App 直接使用。

## 公開端點規則

對於外部 HTTP MCP 用戶端（例如 Gemini 和 ChatGPT），MCP 端點是：

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 只填寫 origin：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

不要把 `/mcp` 追加到 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`。

## 運行時頁面

- [Docker Compose](../installation/docker.md)
- [VS Code 擴展](../installation/vscode-extension.md)
- [獨立二進制](../installation/binary.md)
- [Python、`pipx` 和源碼安裝](../installation/python.md)
- [stdio 模式](../installation/stdio.md)

## 客戶端頁面

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT 連接器](../getting-started/chatgpt-connector.md)
- [通用 MCP 客戶端](../clients/generic-mcp.md)
- [公開 HTTPS 暴露](../clients/connectivity.md)
