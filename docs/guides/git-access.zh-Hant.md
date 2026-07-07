# Git 訪問

`local-shell-mcp` 包含面向 Git 的工具，也允許通過 shell 工具直接運行 Git 命令。

## 常見任務

```text
克隆倉庫，檢查狀態，做一個聚焦補丁，運行測試，提交併推送。
```

推薦順序：

1. `git_status_tool`
2. `git_diff_tool`
3. 編輯或 patch 文件
4. 運行測試
5. `secret_scan`
6. `git_add_tool`
7. `git_commit_tool`
8. `git_push_tool`

## 憑據

Docker 部署可以在 `/persist/credentials` 下持久化常見 Git 憑據位置。把該 volume 視爲敏感資源。

優先使用：

- 只作用於單個倉庫的 deploy key。
- 短期 GitHub App token。
- 用於自動化的隔離機器用戶。
- 推送前人工複查。

避免：

- 在環境變量中放長期個人訪問令牌。
- 把宿主機 SSH 目錄掛進公開 AI 控制容器。
- 通過文件鏈接分享憑據文件。

## 提交衛生

要求 AI：

- 保持提交聚焦。
- 避免生成緩存和構建產物。
- 說明運行過的測試。
- 當開源維護者偏好簡潔人類風格提交時，避免 AI 味樣板話。

## 故障排查

如果 `git push` 失敗：

- 檢查 remote URL。
- 檢查憑據持久化。
- 如果安裝了 GitHub CLI，運行 `gh auth status`。
- 確認分支保護規則。
- 確認 token 或 deploy key 具有寫權限。
