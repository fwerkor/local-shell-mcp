# Usage patterns and prompting guide

`local-shell-mcp` exposes powerful tools. Good results depend on asking the model to inspect first, act in small steps, run verification, and report what changed.

## General operating loop

Use this loop for most coding tasks:

1. Inspect: `environment_info`, `tree_view`, `git_status_tool`, `grep_search`, `read_file`.
2. Plan: ask the model to identify the minimal files and tests involved.
3. Edit: use `edit_file`, `multi_edit_file`, `apply_patch`, or shell commands.
4. Verify: run targeted tests or builds with `run_shell_tool` or persistent shells.
5. Review: `git_diff_tool`, `secret_scan`, `audit_tail` when needed.
6. Commit or export: `git_add_tool`, `git_commit_tool`, `git_push_tool`, or `create_file_link`.

## Tool choice

| Task | Prefer | Avoid |
|---|---|---|
| Quick one-shot command | `run_shell_tool` | Starting a persistent shell for every command |
| Long-running dev server, REPL, watch task | `shell_start` + `shell_read` + `shell_send` | Blocking `run_shell_tool` until timeout |
| Structured analysis or file generation | `run_python_tool` | Fragile shell pipelines for complex JSON/text handling |
| Small exact edit | `edit_file` | Rewriting whole files unnecessarily |
| Several replacements in one file | `multi_edit_file` | Repeated stale edits without rereading |
| Multi-file patch | `apply_patch` | Ad hoc shell edits |
| Finding files | `tree_view`, `glob_search` | Full recursive listings of large repositories |
| Finding code | `grep_search` | Reading many files blindly |
| Browser evidence | `browser_screenshot_tool`, `browser_get_text_tool` | Guessing from page names or routes |
| Downloadable artifacts | `create_file_link` | Pasting large binary content into chat |
| Remote machine work | `remote_*` tools | Opening inbound SSH when outbound worker mode is enough |

## Prompt templates

### Read-only repository orientation

```text
Use local-shell-mcp. Inspect the repository layout and git status. Do not modify files. Summarize the main components, test commands you can infer, and any obvious risks before making changes.
```

### Focused bug fix

```text
Use local-shell-mcp to fix the bug. First reproduce or locate it with the smallest relevant command. Read the files before editing. Make a minimal patch, run the targeted verification, then show git diff and the exact tests run. Do not commit until I approve.
```

### Commit and push workflow

```text
Use local-shell-mcp. Check git status and diff, run the relevant tests, run secret_scan, create one focused commit with a concise message, then push the current branch. Do not include caches, build artifacts, or unrelated formatting.
```

### Long-running process

```text
Start the dev server in a persistent shell session, read the output until it is ready, then use browser tools to verify the page. Keep the session id and kill it after verification.
```

### Remote worker task

```text
Use the connected remote worker named <machine>. First call remote_environment_info and remote_list_files. Work only inside the configured remote workdir. Use remote_run_shell_tool for short commands and remote_shell_start for long-running jobs.
```

## Working with repositories

Recommended sequence for open-source changes:

1. `git_status_tool` to detect dirty state.
2. `git_fetch_tool` and branch inspection if the task depends on upstream state.
3. `grep_search` and `read_file` before editing.
4. Minimal patch.
5. Targeted tests first, then broader tests when practical.
6. `secret_scan` before commit or push.
7. Commit with a concise message that describes the behavior change.

Ask for one commit per logical change when maintainers need reviewable history.

## Working with generated artifacts

For PDFs, reports, screenshots, archives, or logs:

1. Generate the file under the workspace.
2. Verify the file exists and has the expected size.
3. Use `create_file_link` with a short TTL and optional `max_downloads`.
4. Revoke the link when it is no longer needed.

Do not create public links for private keys, credential directories, or unrelated personal data.

## Working with remote machines

Remote worker mode is useful when a machine can make outbound HTTPS requests but cannot accept inbound SSH.

Good practice:

- Name machines clearly with `remote_invite` or `remote_rename_machine`.
- Check `remote_environment_info` before acting.
- Use `remote_pull_file` / `remote_push_file` for explicit transfers.
- Use `remote_copy_file` / `remote_copy_dir` for remote-to-remote transfer through the control server.
- Revoke workers after the task with `remote_revoke_machine`.

## Anti-patterns

Avoid these instructions unless the environment is disposable and the consequences are understood:

- "Install whatever is needed globally" on a host-launched server.
- "Run until it works" without time bounds or verification criteria.
- "Commit everything" in a repository with generated artifacts.
- "Expose the whole home directory" for convenience.
- "Create a file link for the entire workspace".
- Running public deployments with `LOCAL_SHELL_MCP_AUTH_MODE=none`.
