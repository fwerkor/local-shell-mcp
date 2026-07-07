# 文件鏈接

`local-shell-mcp` 可以通過高熵 bearer URL 暴露受控工作區中的文件。當 AI 生成報告、壓縮包、PDF、截圖或其它需要從聊天中下載的產物時，這很有用。

## 何時使用文件鏈接

文件鏈接適合：

- 生成的 PDF 或報告。
- 截圖和瀏覽器產物。
- 構建輸出。
- 過大而不適合粘貼的日誌。
- 準備用於人工檢查的壓縮包。

不要把文件鏈接用於密鑰、私鑰、憑據存儲或無關個人數據。

## 典型流程

1. 在 `/workspace` 下生成或定位文件。
2. 調用 `create_file_link`，設置 TTL 和可選下載次數限制。
3. 分享返回的 URL。
4. 不再需要時撤銷鏈接。

## 相關工具

| 工具 | 用途 |
|---|---|
| `create_file_link` | 爲工作區文件創建帶 token 的 URL。 |
| `list_file_links` | 顯示活動鏈接。 |
| `revoke_file_link` | 在到期前禁用鏈接。 |

## 控制項

相關配置包括：

- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES`

對敏感產物使用較短 TTL；當鏈接只面向單個接收者時，設置最大下載次數。

## 安全說明

文件鏈接是 bearer URL。任何拿到 URL 的人都可以在鏈接過期、達到下載次數限制或被撤銷前下載文件。應把它們視爲臨時密鑰。
