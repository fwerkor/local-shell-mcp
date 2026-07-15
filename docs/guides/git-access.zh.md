# Git 访问

`local-shell-mcp` 通过 `run_shell_tool`、`shell_start` 或 `job_start` 使用标准 Git CLI，不再暴露专用 Git MCP 工具。这样可以覆盖完整 Git 功能，并避免为每个子命令维护重复工具。

## 常见流程

尽量使用有边界、非交互式命令：

```bash
git status --short --branch
git diff --stat
git diff
git add -- path/to/file
git commit -m "fix: concise description"
git push origin HEAD
```

建议流程：

1. 用 `run_shell_tool` 执行 `git status --short --branch`。
2. 只读取和修改相关文件。
3. 运行定向测试。
4. 用 `git diff --check && git diff` 复查。
5. 提交或推送前运行 `secret_scan`。
6. 使用明确的 Git CLI 命令暂存、提交和推送。

仓库位于远程 worker 时，在同一个 shell 工具中指定 `machine`。

## 凭据与提交卫生

优先使用仓库范围的 deploy key、短期 GitHub App token 和隔离的自动化账户。提交应保持聚焦，不包含缓存、构建产物或无关改动。执行 reset、clean、force-push 等破坏性命令前，应先检查准确目标。
