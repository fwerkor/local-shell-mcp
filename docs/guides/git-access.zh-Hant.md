# Git 存取

`local-shell-mcp` 透過 `run_shell_tool`、`shell_start` 或 `job_start` 使用標準 Git CLI，不再暴露專用 Git MCP 工具。這樣可以覆蓋完整 Git 功能，並避免為每個子命令維護重複工具。

## 常見流程

盡量使用有邊界、非互動式命令：

```bash
git status --short --branch
git diff --stat
git diff
git add -- path/to/file
git commit -m "fix: concise description"
git push origin HEAD
```

建議流程：

1. 用 `run_shell_tool` 執行 `git status --short --branch`。
2. 只讀取和修改相關檔案。
3. 執行定向測試。
4. 用 `git diff --check && git diff` 複查。
5. 提交或推送前執行 `secret_scan`。
6. 使用明確的 Git CLI 命令暫存、提交和推送。

倉庫位於遠端 worker 時，在同一個 shell 工具中指定 `machine`。

## 憑據與提交衛生

優先使用倉庫範圍的 deploy key、短期 GitHub App token 和隔離的自動化帳戶。提交應保持聚焦，不包含快取、建置產物或無關改動。執行 reset、clean、force-push 等破壞性命令前，應先檢查準確目標。
