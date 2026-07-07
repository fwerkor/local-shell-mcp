# Git 访问

`local-shell-mcp` 包含面向 Git 的工具，也允许通过 shell 工具直接运行 Git 命令。

## 常见任务

```text
克隆仓库，检查状态，做一个聚焦补丁，运行测试，提交并推送。
```

推荐顺序：

1. `git_status_tool`
2. `git_diff_tool`
3. 编辑或 patch 文件
4. 运行测试
5. `secret_scan`
6. `git_add_tool`
7. `git_commit_tool`
8. `git_push_tool`

## 凭据

Docker 部署可以在 `/persist/credentials` 下持久化常见 Git 凭据位置。把该 volume 视为敏感资源。

优先使用：

- 只作用于单个仓库的 deploy key。
- 短期 GitHub App token。
- 用于自动化的隔离机器用户。
- 推送前人工复查。

避免：

- 在环境变量中放长期个人访问令牌。
- 把宿主机 SSH 目录挂进公开 AI 控制容器。
- 通过文件链接分享凭据文件。

## 提交卫生

要求 AI：

- 保持提交聚焦。
- 避免生成缓存和构建产物。
- 说明运行过的测试。
- 当开源维护者偏好简洁人类风格提交时，避免 AI 味样板话。

## 故障排查

如果 `git push` 失败：

- 检查 remote URL。
- 检查凭据持久化。
- 如果安装了 GitHub CLI，运行 `gh auth status`。
- 确认分支保护规则。
- 确认 token 或 deploy key 具有写权限。
