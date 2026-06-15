# Tools reference

This page lists the MCP tools exposed by `local-shell-mcp`. Tool availability can depend on server configuration, client support, and whether remote worker mode is enabled.

All tools return a structured result with `ok`, `message`, and `data`. Required input fields are marked with `*`. Normal filesystem and shell tools are scoped to `LOCAL_SHELL_MCP_WORKSPACE_ROOT` unless full-container mode is enabled. Remote tools run on a connected worker and add a required `machine` argument or source/destination machine arguments.

## Which tool should the model use?

| Need | Preferred tools |
|---|---|
| Understand environment and policy | `environment_info`, `audit_tail` |
| Locate code or files | `tree_view`, `glob_search`, `grep_search`, `read_file` |
| Make precise edits | `edit_file`, `multi_edit_file`, `apply_patch` |
| Run commands | `run_shell_tool` for short commands; `shell_start` / `shell_read` for long-running sessions |
| Work with Git | `git_status_tool`, `git_diff_tool`, `git_add_tool`, `git_commit_tool`, `git_push_tool` |
| Capture web evidence | `browser_screenshot_tool`, `browser_get_text_tool`, `browser_eval_tool`, `browser_pdf_tool` |
| Share generated artifacts | `create_file_link`, `list_file_links`, `revoke_file_link` |
| Control another machine | `remote_invite`, `remote_list_machines`, and the relevant `remote_*` tool |

## Tool catalog

### Connector and discovery

| Tool | Inputs | Purpose |
|---|---|---|
| `search` | `query`* | Search workspace files and return ChatGPT connector-compatible results. |
| `fetch` | `id`* | Fetch a workspace file by id returned from search. |

### Environment, audit, and task state

| Tool | Inputs | Purpose |
|---|---|---|
| `environment_info` | None | Return workspace, auth, policy, and basic environment information. |
| `audit_tail` | `lines` | Read recent audit log entries. |
| `secret_scan` | `cwd`<br>`glob`<br>`max_results` | Scan workspace text files for common secrets before commit/push. |
| `todo_read_tool` | None | Read the agent todo list. Similar to Claude Code TodoRead. |
| `todo_write_tool` | `todos`* | Write the agent todo list. Each todo: id, content, status, priority. |

### Shell and Python

| Tool | Inputs | Purpose |
|---|---|---|
| `run_shell_tool` | `command`*<br>`cwd`<br>`max_output_bytes`<br>`timeout_s` | Run one non-interactive shell command in the controlled workspace/container. Use for build, test, package-manager, git, and inspection commands that should finish promptly. Parameters: command is the shell command string; cwd defaults to '.' and is resolved relative to the workspace unless full-container mode allows absolute paths. timeout_s defaults to 10 seconds and may be set to at most 120 seconds. For long-running, interactive, or streaming processes, use shell_start with shell_send and shell_read. |
| `run_python_tool` | `code`*<br>`cwd`<br>`timeout_s` | Write Python code to a temporary file and execute it in the controlled workspace/container. Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. Keep code non-interactive and write durable outputs explicitly if needed. |
| `shell_start` | `command`<br>`cwd`<br>`name` | Start a persistent tmux-backed shell session. Use for interactive programs, development servers, REPLs, long-running watches, or commands whose output must be read incrementally. For one-shot commands, use run_shell_tool. |
| `shell_send` | `enter`<br>`input_text`*<br>`session_id`* | Send input to an existing persistent shell session. Use after shell_start when a process is waiting for commands or interactive input. Set enter=false only when intentionally sending partial input without a newline. |
| `shell_read` | `lines`<br>`session_id`* | Read recent output from a persistent shell session. Use after shell_start or shell_send to inspect incremental output without blocking. Increase lines only when needed for context. |
| `shell_kill` | `session_id`* | Terminate a persistent shell session by session_id. Use when a server, watch process, REPL, or stuck command is no longer needed. This is destructive for that session but does not delete files. |
| `shell_list` | None | List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active. |

### Filesystem, search, and patching

| Tool | Inputs | Purpose |
|---|---|---|
| `list_files` | `max_entries`<br>`path`<br>`recursive` | List files and directories under a path. Use for quick directory inspection when a compact listing is enough. path defaults to '.' and is workspace-relative unless full-container mode allows absolute paths; recursive walks descendants and max_entries is capped by server settings. |
| `tree_view` | `cwd`<br>`depth`<br>`max_entries` | Return a compact directory tree. |
| `glob_search` | `cwd`<br>`max_results`<br>`pattern`* | Find files by glob pattern. |
| `grep_search` | `case_sensitive`<br>`cwd`<br>`glob`<br>`max_results`<br>`query`*<br>`regex` | Search file contents using ripgrep. |
| `read_file` | `binary_preview`<br>`binary_preview_bytes`<br>`end_line`<br>`path`*<br>`start_line` | Read a UTF-8 text file, optionally by line range. Use after locating a file to inspect exact content before editing. start_line and end_line are 1-based inclusive line numbers for paging large files; binary_preview can request a bounded hex or base64 preview. |
| `read_many_files` | `binary_preview`<br>`binary_preview_bytes`<br>`end_line`<br>`paths`*<br>`start_line` | Read multiple UTF-8 text files with the same optional line range. Use when comparing related small files or collecting context across a targeted path list; server settings cap file count and total bytes. |
| `write_file` | `content`*<br>`overwrite`<br>`path`* | Write a UTF-8 text file. Use to create a new file or intentionally replace a whole file. overwrite defaults to true; set overwrite=false when creating only if absent. For precise modifications to existing files, use edit_file or apply_patch. |
| `edit_file` | `new`*<br>`old`*<br>`path`*<br>`replace_all` | Replace exact text in a file. Use for small precise edits after reading the target file. old must match exactly, including whitespace and indentation; replace_all should be true only when every exact occurrence should change. |
| `multi_edit_file` | `edits`*<br>`path`* | Apply multiple exact-text edits to one file. Use when several small replacements in the same file should be made together. Each old string must match exactly; read the file first to avoid stale or ambiguous edits. |
| `delete_file_or_dir` | `path`*<br>`recursive` | Delete a file or directory inside the controlled workspace/container. Use only when removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully. |
| `apply_patch` | `cwd`<br>`patch`* | Apply a unified diff using git apply. Use for larger or multi-file edits where an exact patch is clearer than multiple edit_file calls. The patch is checked before application and cwd is workspace-relative unless full-container mode allows absolute paths. |

### File links

| Tool | Inputs | Purpose |
|---|---|---|
| `create_file_link` | `filename`<br>`max_downloads`<br>`path`*<br>`ttl_s` | Create a temporary browser-accessible download URL for a regular workspace file. Generated links are public bearer URLs protected by a high-entropy token, TTL, optional download-count limit, optional size limit, and explicit revocation. |
| `list_file_links` | `include_expired` | List generated file download URLs. |
| `revoke_file_link` | `token`* | Revoke a generated file download URL. |

### Git

| Tool | Inputs | Purpose |
|---|---|---|
| `git_clone_tool` | `branch`<br>`cwd`<br>`dest`<br>`repo_url`* | Clone a Git repository. |
| `git_status_tool` | `cwd` | Run git status and list remotes. |
| `git_diff_tool` | `cwd`<br>`path`<br>`staged`<br>`stat` | Run git diff. |
| `git_log_tool` | `cwd`<br>`max_count` | Show recent git commits. |
| `git_checkout_tool` | `create`<br>`cwd`*<br>`ref`* | Checkout an existing ref or create a branch. |
| `git_fetch_tool` | `cwd`<br>`prune`<br>`remote` | Fetch a git remote. |
| `git_pull_tool` | `cwd`<br>`ff_only` | Pull current branch. |
| `git_add_tool` | `cwd`<br>`paths` | Stage paths for commit. |
| `git_commit_tool` | `all_changes`<br>`cwd`*<br>`message`* | Create a git commit. |
| `git_push_tool` | `branch`<br>`cwd`*<br>`remote`<br>`set_upstream` | Push current HEAD to a remote branch. |
| `git_show_tool` | `cwd`<br>`path`<br>`ref` | Show a commit, object, or file at ref:path. |
| `git_reset_tool` | `cwd`<br>`mode`<br>`ref` | Run git reset. Modes: soft, mixed, hard. |

### Browser automation

| Tool | Inputs | Purpose |
|---|---|---|
| `playwright_install_tool` | `browser`<br>`with_deps` | Install Playwright browser binaries in the container. |
| `browser_screenshot_tool` | `browser`<br>`full_page`<br>`height`<br>`output_path`<br>`url`*<br>`wait_until`<br>`width` | Open a URL with Playwright and save a screenshot. |
| `browser_get_text_tool` | `browser`<br>`selector`<br>`url`*<br>`wait_until` | Open a URL with Playwright and return visible text for a selector. |
| `browser_eval_tool` | `browser`<br>`javascript`*<br>`url`*<br>`wait_until` | Open a URL with Playwright and evaluate JavaScript. |
| `browser_pdf_tool` | `height`<br>`output_path`<br>`url`*<br>`wait_until`<br>`width` | Open a URL with Chromium and save a PDF. |
| `playwright_run_script_tool` | `cwd`<br>`script`*<br>`timeout_s` | Run a full Python Playwright script. Powerful; use in disposable containers. |

### Remote worker lifecycle

| Tool | Inputs | Purpose |
|---|---|---|
| `remote_invite` | `name`<br>`ttl_s`<br>`workdir` | Create a one-time command for a remote machine to join this control server. |
| `remote_list_machines` | None | List remote worker machines connected to this control server. |
| `remote_rename_machine` | `machine`*<br>`new_name`* | Rename a remote worker machine. |
| `remote_revoke_machine` | `machine`* | Revoke and remove a remote worker machine. |
| `remote_environment_info` | `machine`* | Return remote workspace, auth, policy, and basic environment information. |

### Remote shell and Python

| Tool | Inputs | Purpose |
|---|---|---|
| `remote_run_shell_tool` | `command`*<br>`cwd`<br>`machine`*<br>`max_output_bytes`<br>`timeout_s` | Run a shell command on a remote worker machine. timeout_s defaults to 10 seconds and may be set to at most 120 seconds. |
| `remote_run_python_tool` | `code`*<br>`cwd`<br>`machine`*<br>`timeout_s` | Write Python code to a temporary file and execute it on a remote worker. |
| `remote_shell_start` | `command`<br>`cwd`<br>`machine`*<br>`name` | Start a persistent shell session on a remote worker. |
| `remote_shell_send` | `enter`<br>`input_text`*<br>`machine`*<br>`session_id`* | Send input to a persistent remote shell session. |
| `remote_shell_read` | `lines`<br>`machine`*<br>`session_id`* | Read recent output from a persistent remote shell session. |
| `remote_shell_kill` | `machine`*<br>`session_id`* | Kill a persistent remote shell session. |
| `remote_shell_list` | `machine`* | List persistent shell sessions on a remote worker. |

### Remote filesystem, search, and patching

| Tool | Inputs | Purpose |
|---|---|---|
| `remote_list_files` | `machine`*<br>`max_entries`<br>`path`<br>`recursive` | List files and directories on a remote worker. |
| `remote_tree_view` | `cwd`<br>`depth`<br>`machine`*<br>`max_entries` | Return a compact directory tree from a remote worker. |
| `remote_glob_search` | `cwd`<br>`machine`*<br>`max_results`<br>`pattern`* | Find files by glob pattern on a remote worker. |
| `remote_grep_search` | `case_sensitive`<br>`cwd`<br>`glob`<br>`machine`*<br>`max_results`<br>`query`*<br>`regex` | Search remote file contents using ripgrep. |
| `remote_read_file` | `binary_preview`<br>`binary_preview_bytes`<br>`end_line`<br>`machine`*<br>`path`*<br>`start_line` | Read a UTF-8 text file on a remote worker, optionally by line range. |
| `remote_read_many_files` | `binary_preview`<br>`binary_preview_bytes`<br>`end_line`<br>`machine`*<br>`paths`*<br>`start_line` | Read multiple UTF-8 text files on a remote worker. |
| `remote_write_file` | `content`*<br>`machine`*<br>`overwrite`<br>`path`* | Write a UTF-8 text file on a remote worker. |
| `remote_edit_file` | `machine`*<br>`new`*<br>`old`*<br>`path`*<br>`replace_all` | Replace exact text in a remote file. |
| `remote_multi_edit_file` | `edits`*<br>`machine`*<br>`path`* | Apply multiple exact-text edits to one remote file. |
| `remote_delete_file_or_dir` | `machine`*<br>`path`*<br>`recursive` | Delete a file or directory on a remote worker. |
| `remote_apply_patch` | `cwd`<br>`machine`*<br>`patch`* | Apply a unified diff on a remote worker using git apply. |

### Remote file transfer

| Tool | Inputs | Purpose |
|---|---|---|
| `remote_pull_file` | `chunk_size`<br>`local_path`*<br>`machine`*<br>`overwrite`<br>`remote_path`* | Copy a file from a remote worker to the control server workspace. |
| `remote_push_file` | `chunk_size`<br>`local_path`*<br>`machine`*<br>`overwrite`<br>`remote_path`* | Copy a file from the control server workspace to a remote worker. |
| `remote_pull_dir` | `chunk_size`<br>`local_path`*<br>`machine`*<br>`overwrite`<br>`remote_path`* | Copy a directory tree from a remote worker to the control server workspace. |
| `remote_push_dir` | `chunk_size`<br>`local_path`*<br>`machine`*<br>`overwrite`<br>`remote_path`* | Copy a directory tree from the control server workspace to a remote worker. |
| `remote_copy_file` | `chunk_size`<br>`dst_machine`*<br>`dst_path`*<br>`overwrite`<br>`src_machine`*<br>`src_path`* | Copy a file from one remote worker machine to another through the control server. |
| `remote_copy_dir` | `chunk_size`<br>`dst_machine`*<br>`dst_path`*<br>`overwrite`<br>`src_machine`*<br>`src_path`* | Copy a directory tree from one remote worker machine to another through the control server. |

### Remote Git

| Tool | Inputs | Purpose |
|---|---|---|
| `remote_git_clone_tool` | `branch`<br>`cwd`<br>`dest`<br>`machine`*<br>`repo_url`* | Clone a Git repository on a remote worker. |
| `remote_git_status_tool` | `cwd`<br>`machine`* | Run git status on a remote worker. |
| `remote_git_diff_tool` | `cwd`<br>`machine`*<br>`path`<br>`staged`<br>`stat` | Run git diff on a remote worker. |
| `remote_git_log_tool` | `cwd`<br>`machine`*<br>`max_count` | Show recent git commits on a remote worker. |
| `remote_git_checkout_tool` | `create`<br>`cwd`*<br>`machine`*<br>`ref`* | Checkout an existing ref or create a branch on a remote worker. |
| `remote_git_fetch_tool` | `cwd`<br>`machine`*<br>`prune`<br>`remote` | Fetch a git remote on a remote worker. |
| `remote_git_pull_tool` | `cwd`<br>`ff_only`<br>`machine`* | Pull current branch on a remote worker. |
| `remote_git_add_tool` | `cwd`<br>`machine`*<br>`paths` | Stage paths on a remote worker. |
| `remote_git_commit_tool` | `all_changes`<br>`cwd`*<br>`machine`*<br>`message`* | Create a git commit on a remote worker. |
| `remote_git_push_tool` | `branch`<br>`cwd`*<br>`machine`*<br>`remote`<br>`set_upstream` | Push current HEAD from a remote worker. |
| `remote_git_show_tool` | `cwd`<br>`machine`*<br>`path`<br>`ref` | Show a commit, object, or file at ref:path on a remote worker. |
| `remote_git_reset_tool` | `cwd`<br>`machine`*<br>`mode`<br>`ref` | Run git reset on a remote worker. Modes: soft, mixed, hard. |

### Remote browser automation

| Tool | Inputs | Purpose |
|---|---|---|
| `remote_playwright_install_tool` | `browser`<br>`machine`*<br>`with_deps` | Install Playwright browser binaries on a remote worker. |
| `remote_browser_screenshot_tool` | `browser`<br>`full_page`<br>`height`<br>`machine`*<br>`output_path`<br>`url`*<br>`wait_until`<br>`width` | Open a URL with Playwright on a remote worker and save a screenshot. |
| `remote_browser_get_text_tool` | `browser`<br>`machine`*<br>`selector`<br>`url`*<br>`wait_until` | Open a URL with Playwright on a remote worker and return visible text. |
| `remote_browser_eval_tool` | `browser`<br>`javascript`*<br>`machine`*<br>`url`*<br>`wait_until` | Open a URL with Playwright on a remote worker and evaluate JavaScript. |
| `remote_browser_pdf_tool` | `height`<br>`machine`*<br>`output_path`<br>`url`*<br>`wait_until`<br>`width` | Open a URL with Chromium on a remote worker and save a PDF. |
| `remote_playwright_run_script_tool` | `cwd`<br>`machine`*<br>`script`*<br>`timeout_s` | Run a full Python Playwright script on a remote worker. |

## Notes for client authors

- Use `/mcp` for the full MCP surface. Connector-style `search` and `fetch` are read-only and are not a replacement for the full coding-agent tools.
- Respect tool descriptions and input schemas from MCP discovery; this page is a human-readable catalog, not a schema substitute.
- For long-running commands, prefer persistent shell sessions so the client can poll incremental output instead of waiting for a single blocking response.
- Remote tools have near-parity with local tools but depend on the remote worker having the required OS packages and language runtimes installed.
