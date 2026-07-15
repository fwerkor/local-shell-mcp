# Git access

`local-shell-mcp` uses the standard Git command-line interface through `run_shell_tool`, `shell_start`, or `job_start`. Dedicated Git MCP wrappers are intentionally not exposed: the CLI is complete, familiar to coding agents, and avoids duplicating every Git subcommand in the tool list.

## Common workflow

Use bounded, non-interactive commands where possible:

```bash
git status --short --branch
git diff --stat
git diff
git add -- path/to/file
git commit -m "fix: concise description"
git push origin HEAD
```

A typical agent sequence is:

1. Inspect with `run_shell_tool(command="git status --short --branch")`.
2. Read and edit only the relevant files.
3. Run targeted tests.
4. Review with `run_shell_tool(command="git diff --check && git diff")`.
5. Run `secret_scan` before committing or pushing.
6. Stage, commit, and push using explicit Git CLI commands.

Use `machine` on the same shell tool when the repository is on a remote worker.

## Credentials

Docker deployments can persist common Git credential locations under `/persist/credentials`. Treat that volume as sensitive. Prefer repository-scoped deploy keys, short-lived GitHub App tokens, isolated automation users, and manual review before push.

## Commit hygiene

Keep commits focused, omit generated caches and build artifacts, record the tests run, and avoid staging unrelated changes. For destructive commands such as reset, clean, or force-push, inspect the exact target first.

## Troubleshooting

When `git push` fails, inspect the remote URL, credential persistence, branch protection, and token permissions. `gh auth status` is useful when GitHub CLI is installed.
