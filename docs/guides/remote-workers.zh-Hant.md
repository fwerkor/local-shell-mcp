# 遠端 worker

遠端 worker 適用於能夠發起出站 HTTP(S)、但無法接收入站 SSH 的機器。

```text
MCP 客戶端 -> 控制服務 -> 出站輪詢 worker -> 遠端機器
```

## 基本流程

1. 使用 `remote_invite` 建立一次性邀請。
2. 在遠端機器上執行生成的命令。
3. 使用 `remote_list_machines` 確認註冊成功。
4. 在一般工具中指定 `machine="<worker-name>"`，例如 `environment_info`、`run_shell_tool`、`read_file` 或 `browser_capture_tool`。
5. 使用 `transfer_path` 處理控制端到 worker、worker 到控制端以及 worker 到 worker 的檔案或目錄傳輸。
6. 使用 `remote_rename_machine` 重新命名，或用 `remote_revoke_machine` 撤銷 worker。

只有 worker 管理繼續使用 `remote_*` 名稱。執行、shell、job、檔案、patch 和瀏覽器操作在本地與遠端使用同一 Schema。指定 `machine` 時會額外要求 `remote:use` OAuth scope。

## 能力與安全

worker 支援 shell、持久終端、tracked job、檔案操作、傳輸、Python、patch，以及已安裝相依套件時的 Playwright。Git 透過 `run_shell_tool(machine=...)` 執行標準 CLI。

加入 worker 相當於允許 MCP 客戶端控制其配置環境。應使用較短邀請 TTL、專用工作目錄或帳戶，保留稽核日誌，並在任務結束後撤銷 worker。生成的邀請會安裝與控制服務匹配的 worker 版本。

## 疑難排解

如果 worker 未出現，檢查出站 HTTPS、公開 base URL、邀請是否過期、系統時間以及控制服務日誌。
