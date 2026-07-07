# 瀏覽器自動化

瀏覽器工具使用 Playwright 檢查網頁、採集證據、評估頁面狀態並生成 PDF。它們適合文檔站、UI smoke test、視覺迴歸排查，以及收集可復現截圖。

## 工具

| 工具 | 用途 |
|---|---|
| `playwright_install_tool` | 缺少瀏覽器二進制時安裝它們。 |
| `browser_screenshot_tool` | 在工作區內保存頁面截圖。 |
| `browser_get_text_tool` | 從選擇器中提取可見文本。 |
| `browser_eval_tool` | 在頁面上下文中執行 JavaScript。 |
| `browser_pdf_tool` | 保存頁面的 Chromium PDF。 |
| `playwright_run_script_tool` | 運行完整 Python Playwright 腳本。 |
| `remote_browser_*` | 在已連接遠程 worker 上運行等價操作。 |

## 常見流程

### 截取本本文檔站

1. 在持久 shell session 中啓動站點。
2. 等待服務器輸出本地 URL。
3. 對該 URL 調用 `browser_screenshot_tool`。
4. 如果需要從聊天中下載截圖，使用 `create_file_link`。
5. 關閉持久 shell session。

### 提取文本做快速驗證

當主要問題是頁面是否渲染了預期內容時，使用 `browser_get_text_tool`。

示例任務表述：

```text
啓動文檔預覽，對首頁使用 browser_get_text_tool，確認導航中出現 deployment、tools 和 usage-patterns 頁面。
```

### 運行自定義 Playwright 腳本

當內置截圖、文本、PDF 工具不夠時，使用 `playwright_run_script_tool`。例如需要點擊流程、檢查 console error，或採集多個頁面。

腳本應有明確邊界：

- 設置顯式超時。
- 把產物保存到工作區。
- 除非環境專用於該任務，否則避免輸入憑據。
- 對公開站點優先使用只讀檢查。

## 故障排查

如果瀏覽器啓動失敗：

- 對所需瀏覽器運行 `playwright_install_tool`。
- 確認容器或宿主機具備所需系統依賴。
- Docker 中優先使用項目官方鏡像，因爲它包含預期的瀏覽器和文檔工具。
- 對遠程 worker，在遠程機器上安裝依賴，或改用控制服務上的瀏覽器工具。
