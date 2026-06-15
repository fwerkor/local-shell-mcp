# Git access

`local-shell-mcp` includes Git-oriented tools and also allows direct Git commands through shell tools.

## Common tasks

```text
Clone a repository, inspect status, make a focused patch, run tests, commit, and push.
```

Recommended sequence:

1. `git_status_tool`
2. `git_diff_tool`
3. edit or patch files
4. run tests
5. `secret_scan`
6. `git_add_tool`
7. `git_commit_tool`
8. `git_push_tool`

## Credentials

Docker deployments can persist common Git credential locations under `/persist/credentials`. Treat that volume as sensitive.

Prefer:

- Deploy keys scoped to one repository.
- Short-lived GitHub App tokens.
- Isolated machine users for automation.
- Manual review before push.

Avoid:

- Long-lived personal access tokens in environment variables.
- Mounting host SSH directories into a public AI-controlled container.
- Sharing credential files through file links.

## Commit hygiene

Ask the AI to:

- Keep commits focused.
- Avoid generated caches and build artifacts.
- Mention tests run.
- Avoid AI-flavored boilerplate in open-source PRs when maintainers prefer concise human-style commits.

## Troubleshooting

If `git push` fails:

- Check remote URL.
- Check credential persistence.
- Run `gh auth status` if GitHub CLI is installed.
- Confirm branch protection rules.
- Confirm the token or deploy key has write permission.
