# Usage patterns and prompting guide

`local-shell-mcp` exposes powerful tools. Good results depend on asking the model to inspect first, act in small steps, run verification, and report what changed.

## General operating loop

Use this loop for most coding tasks:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read`, and `run_shell` for commands such as `git status`.
2. Plan: ask the model to identify the minimal files and tests involved.
3. Edit: use unified `file_edit`, `file_patch`, or shell commands.
4. Verify: run targeted tests or builds with `run_shell` or persistent shells.
5. Review: run `git diff` through `run_shell`, then use `secret_scan` and `audit_tail` when needed.
6. Commit or export: use explicit Git CLI commands through `run_shell`, or use `link_create`.

## Tool choice

| Task | Prefer | Avoid |
|---|---|---|
| Quick one-shot command | `run_shell` | Starting a persistent shell for every command |
| Long-running dev server, REPL, watch task | `shell_start` + `shell_read` + `shell_send` | Blocking `run_shell` until timeout |
| Structured analysis or file generation | `run_python` | Fragile shell pipelines for complex JSON/text handling |
| Small exact edit | `file_edit` | Rewriting whole files unnecessarily |
| One or several replacements in one file | `file_edit` with an `edits` array | Repeated stale edits without rereading |
| Multi-file patch | `file_patch` | Ad hoc shell edits |
| Finding files | `file_tree`, `file_glob` | Full recursive listings of large repositories |
| Finding code | `file_grep` | Reading many files blindly |
| Browser evidence | `browser_capture_tool`, `browser_get_text_tool` | Guessing from page names or routes |
| Downloadable artifacts | `link_create` | Pasting large binary content into chat |
| Remote machine work | normal tools with `machine`, plus `remote_transfer` | Opening inbound SSH when outbound worker mode is enough |

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
Use the connected remote worker named <machine>. First call environment_get with machine=<machine>, then file_list with the same machine. Work only inside the configured remote workdir. Use run_shell for short commands and shell_start or job_start for long-running work.
```

## Working with repositories

Recommended sequence for open-source changes:

1. Run `git status --short --branch` through `run_shell`.
2. Fetch and inspect branches with explicit Git CLI commands when upstream state matters.
3. Use `file_grep` and `file_read` before editing.
4. Make a minimal patch.
5. Run targeted tests first, then broader tests when practical.
6. Run `secret_scan` before commit or push.
7. Stage and commit explicitly with a concise message.

Ask for one commit per logical change when maintainers need reviewable history.

## Working with generated artifacts

For PDFs, reports, screenshots, archives, or logs:

1. Generate the file under the workspace.
2. Verify the file exists and has the expected size.
3. Use `link_create` with a short TTL and optional `max_downloads`.
4. Revoke the link when it is no longer needed.

Do not create public links for private keys, credential directories, or unrelated personal data.

## Working with remote machines

Remote worker mode is useful when a machine can make outbound HTTPS requests but cannot accept inbound SSH.

Good practice:

- Name machines clearly with `remote_manage(action="invite", ...)` or `remote_manage(action="rename", ...)`.
- Call `environment_get(machine=...)` before acting.
- Use `remote_transfer` to start tracked controller/worker and worker/worker file or directory transfers, then manage them with the normal `job_*` tools.
- Revoke workers after the task with `remote_manage(action="revoke", ...)`.

## Anti-patterns

Avoid these instructions unless the environment is disposable and the consequences are understood:

- "Install whatever is needed globally" on a host-launched server.
- "Run until it works" without time bounds or verification criteria.
- "Commit everything" in a repository with generated artifacts.
- "Expose the whole home directory" for convenience.
- "Create a file link for the entire workspace".
- Running public deployments with `LOCAL_SHELL_MCP_AUTH_MODE=none`.
