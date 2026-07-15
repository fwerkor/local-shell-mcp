# 瀏覽器自動化

瀏覽器工具基於 Playwright，用於檢查頁面、保存證據和執行可重現的互動流程。公開工具面刻意保持精簡。

## 工具

| 工具 | 用途 |
|---|---|
| `browser_get_text_tool` | 從指定 selector 提取可見文字。 |
| `browser_capture_tool` | 保存 PNG 截圖或 Chromium PDF。 |
| `playwright_run_script_tool` | 執行完整 Python Playwright 腳本，處理點擊、表單、主控台檢查或多頁面流程。 |

三個工具都接受可選的 `machine` 參數。控制端或目標 worker 必須已經安裝瀏覽器相依套件；安裝工作透過一般 shell 命令完成，例如 `python -m playwright install chromium`。

## 常見流程

進行視覺驗證時，先用 `shell_start` 或 `job_start` 啟動站點，等服務就緒後呼叫 `browser_capture_tool(capture_format="png")`，最後停止程序。需要可列印輸出時使用 `capture_format="pdf"`，並選擇 Chromium。

只關心渲染文字時使用 `browser_get_text_tool`。需要互動、JavaScript 求值或複雜導覽時使用 `playwright_run_script_tool`。

腳本應設定明確逾時，把產物保存到工作區，並避免在非專用環境中輸入憑據。
