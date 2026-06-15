# Tools reference

Cette page est une version localisée qui garde la même structure Runtime/Client.

Tool names, parameter names, and return fields stay as code identifiers. Each entry keeps purpose, inputs, returns, combinations, and notes.

## Tool details

## Connector and discovery

### `search`

**Vue d’ensemble.** Search workspace files and return ChatGPT connector-compatible results.

**Quand l’utiliser.** Use for read-only connector discovery. Prefer the full MCP tools for coding-agent work.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `query` | `str` | required | Search string. For `grep_search`, it is a ripgrep pattern when `regex=true`; for connector `search`, it is a plain discovery query. |

**Returns.** Returns a JSON string matching ChatGPT connector-style search/fetch expectations, not the normal `ToolResult` envelope.

**Common combinations.** `search` -> `fetch` for read-only connector discovery.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `fetch`

**Vue d’ensemble.** Fetch a workspace file by id returned from search.

**Quand l’utiliser.** Use for read-only connector discovery. Prefer the full MCP tools for coding-agent work.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `id` | `str` | required | Workspace file identifier returned by connector-style `search`. |

**Returns.** Returns a JSON string matching ChatGPT connector-style search/fetch expectations, not the normal `ToolResult` envelope.

**Common combinations.** `search` returns ids that `fetch` can read.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

## Environment, audit, and task state

### `environment_info`

**Vue d’ensemble.** Return workspace, auth, policy, and basic environment information.

**Quand l’utiliser.** Use as the first diagnostic call after connecting a client or after upgrading the runtime.

**Inputs.** None.

**Returns.** Returns a `ToolResult`. `data.settings` contains redacted runtime settings; `data.probe` contains a basic command probe.

**Common combinations.** `environment_info` -> `tree_view` -> `git_status_tool` for first contact.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `audit_tail`

**Vue d’ensemble.** Read recent audit log entries.

**Quand l’utiliser.** Use to inspect recent tool activity and troubleshoot or review sensitive operations.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `int` | default `100` | Number of recent output or audit lines to return. |

**Returns.** Returns a `ToolResult`. `data.settings` contains redacted runtime settings; `data.probe` contains a basic command probe.

**Common combinations.** Use with the surrounding tools in the same family.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `secret_scan`

**Vue d’ensemble.** Scan workspace text files for common secrets before commit/push.

**Quand l’utiliser.** Use before commits, pushes, releases, or sharing artifacts.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `glob` | `str | None` | default `None` | Optional glob filter for content search. |
| `max_results` | `int` | default `200` | Maximum number of matches or paths to return. |

**Returns.** Returns a `ToolResult`. `data.settings` contains redacted runtime settings; `data.probe` contains a basic command probe.

**Common combinations.** Use with the surrounding tools in the same family.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `todo_read_tool`

**Vue d’ensemble.** Read the agent todo list. Similar to Claude Code TodoRead.

**Quand l’utiliser.** Use to maintain a multi-step agent task plan inside the controlled environment.

**Inputs.** None.

**Returns.** Returns a `ToolResult`. `data.settings` contains redacted runtime settings; `data.probe` contains a basic command probe.

**Common combinations.** `todo_write_tool` before multi-step work; `todo_read_tool` to resume.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `todo_write_tool`

**Vue d’ensemble.** Write the agent todo list. Each todo: id, content, status, priority.

**Quand l’utiliser.** Use to maintain a multi-step agent task plan inside the controlled environment.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `todos` | `list[dict]` | required | Todo records. Each record should include id, content, status, and priority. |

**Returns.** Returns a `ToolResult`. `data.settings` contains redacted runtime settings; `data.probe` contains a basic command probe.

**Common combinations.** `todo_write_tool` before multi-step work; `todo_read_tool` to resume.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

## Shell and Python

### `run_shell_tool`

**Vue d’ensemble.** Run one non-interactive shell command in the controlled workspace/container. Use for build, test, package-manager, git, and inspection commands that should finish promptly. Parameters: command is the shell command string; cwd defaults to '.' and is resolved relative to the workspace unless full-container mode allows absolute paths. timeout_s defaults to 10 seconds and may be set to at most 120 seconds. For long-running, interactive, or streaming processes, use shell_start with shell_send and shell_read.

**Quand l’utiliser.** Use for one-shot commands that should finish promptly, such as tests, builds, package queries, or repository inspection.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `command` | `str` | required | Shell command string executed by the configured shell. Keep one-shot commands non-interactive. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `timeout_s` | `int | None` | default `None` | Command or script timeout in seconds. Public one-shot shell tools are capped by the server. |
| `max_output_bytes` | `int | None` | default `None` | Maximum captured output bytes before truncation. |

**Returns.** Returns a `ToolResult`. `data` includes exit code, stdout, stderr, timeout status, duration, cwd, command, and truncation status.

**Common combinations.** `run_shell_tool` for quick commands; `shell_start` + `shell_read` for long sessions.

**Notes.**

- For commands that stream, prompt, or run indefinitely, use the persistent shell tools instead.

### `run_python_tool`

**Vue d’ensemble.** Write Python code to a temporary file and execute it in the controlled workspace/container. Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. Keep code non-interactive and write durable outputs explicitly if needed.

**Quand l’utiliser.** Use for short structured scripts, JSON manipulation, repository analysis, or calculations that are awkward in shell.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `code` | `str` | required | Python source code written to a temporary file and executed. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `timeout_s` | `int` | default `60` | Command or script timeout in seconds. Public one-shot shell tools are capped by the server. |

**Returns.** Returns a `ToolResult`. `data` includes exit code, stdout, stderr, timeout status, duration, cwd, command, and truncation status.

**Common combinations.** Use with the surrounding tools in the same family.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `shell_start`

**Vue d’ensemble.** Start a persistent tmux-backed shell session. Use for interactive programs, development servers, REPLs, long-running watches, or commands whose output must be read incrementally. For one-shot commands, use run_shell_tool.

**Quand l’utiliser.** Use for long-running or interactive terminal workflows where output must be read incrementally.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `name` | `str | None` | default `None` | Optional human-readable session or remote-worker name. |
| `command` | `str | None` | default `None` | Shell command string executed by the configured shell. Keep one-shot commands non-interactive. |

**Returns.** Returns a `ToolResult`. `data` includes exit code, stdout, stderr, timeout status, duration, cwd, command, and truncation status.

**Common combinations.** `shell_start` -> `shell_send` -> `shell_read` -> `shell_kill`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `shell_send`

**Vue d’ensemble.** Send input to an existing persistent shell session. Use after shell_start when a process is waiting for commands or interactive input. Set enter=false only when intentionally sending partial input without a newline.

**Quand l’utiliser.** Use for long-running or interactive terminal workflows where output must be read incrementally.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `str` | required | Persistent shell session identifier returned by `shell_start` or `remote_shell_start`. |
| `input_text` | `str` | required | Text sent to a persistent shell session. |
| `enter` | `bool` | default `True` | Whether to append Enter/newline after `input_text`. |

**Returns.** Returns a `ToolResult`. `data` includes exit code, stdout, stderr, timeout status, duration, cwd, command, and truncation status.

**Common combinations.** `shell_start` -> `shell_send` -> `shell_read` -> `shell_kill`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `shell_read`

**Vue d’ensemble.** Read recent output from a persistent shell session. Use after shell_start or shell_send to inspect incremental output without blocking. Increase lines only when needed for context.

**Quand l’utiliser.** Use for long-running or interactive terminal workflows where output must be read incrementally.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `str` | required | Persistent shell session identifier returned by `shell_start` or `remote_shell_start`. |
| `lines` | `int` | default `200` | Number of recent output or audit lines to return. |

**Returns.** Returns a `ToolResult`. `data` includes exit code, stdout, stderr, timeout status, duration, cwd, command, and truncation status.

**Common combinations.** `shell_start` -> `shell_send` -> `shell_read` -> `shell_kill`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `shell_kill`

**Vue d’ensemble.** Terminate a persistent shell session by session_id. Use when a server, watch process, REPL, or stuck command is no longer needed. This is destructive for that session but does not delete files.

**Quand l’utiliser.** Use for long-running or interactive terminal workflows where output must be read incrementally.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `str` | required | Persistent shell session identifier returned by `shell_start` or `remote_shell_start`. |

**Returns.** Returns a `ToolResult`. `data` includes exit code, stdout, stderr, timeout status, duration, cwd, command, and truncation status.

**Common combinations.** `shell_start` -> `shell_send` -> `shell_read` -> `shell_kill`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `shell_list`

**Vue d’ensemble.** List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active.

**Quand l’utiliser.** Use for long-running or interactive terminal workflows where output must be read incrementally.

**Inputs.** None.

**Returns.** Returns a `ToolResult`. `data` includes exit code, stdout, stderr, timeout status, duration, cwd, command, and truncation status.

**Common combinations.** `shell_start` -> `shell_send` -> `shell_read` -> `shell_kill`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

## Filesystem, search, and patching

### `list_files`

**Vue d’ensemble.** List files and directories under a path. Use for quick directory inspection when a compact listing is enough. path defaults to '.' and is workspace-relative unless full-container mode allows absolute paths; recursive walks descendants and max_entries is capped by server settings.

**Quand l’utiliser.** List files and directories under a path. Use for quick directory inspection when a compact listing is enough. path defaults to '.' and is workspace-relative unless full-container mode allows absolute paths; recursive walks descendants and max_entries is capped by server settings.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `path` | `str` | default `'.'` | File or directory path, normally workspace-relative. |
| `recursive` | `bool` | default `False` | Whether to recurse into subdirectories. |
| `max_entries` | `int` | default `500` | Maximum number of directory or tree entries to return. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `tree_view` / `glob_search` / `grep_search` -> `read_file`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `tree_view`

**Vue d’ensemble.** Return a compact directory tree.

**Quand l’utiliser.** Return a compact directory tree.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `depth` | `int` | default `3` | Directory tree depth. |
| `max_entries` | `int` | default `500` | Maximum number of directory or tree entries to return. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `tree_view` / `glob_search` / `grep_search` -> `read_file`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `glob_search`

**Vue d’ensemble.** Find files by glob pattern.

**Quand l’utiliser.** Find files by glob pattern.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `str` | required | Glob pattern for file-path discovery. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `max_results` | `int` | default `500` | Maximum number of matches or paths to return. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `tree_view` / `glob_search` / `grep_search` -> `read_file`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `grep_search`

**Vue d’ensemble.** Search file contents using ripgrep.

**Quand l’utiliser.** Search file contents using ripgrep.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `query` | `str` | required | Search string. For `grep_search`, it is a ripgrep pattern when `regex=true`; for connector `search`, it is a plain discovery query. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `glob` | `str | None` | default `None` | Optional glob filter for content search. |
| `regex` | `bool` | default `True` | Whether the search query is treated as a regular expression. |
| `case_sensitive` | `bool` | default `True` | Whether matching is case-sensitive. |
| `max_results` | `int | None` | default `None` | Maximum number of matches or paths to return. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `tree_view` / `glob_search` / `grep_search` -> `read_file`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `read_file`

**Vue d’ensemble.** Read a UTF-8 text file, optionally by line range. Use after locating a file to inspect exact content before editing. start_line and end_line are 1-based inclusive line numbers for paging large files; binary_preview can request a bounded hex or base64 preview.

**Quand l’utiliser.** Use after locating candidate files and before making edits.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `start_line` | `int | None` | default `None` | First 1-based line to read. |
| `end_line` | `int | None` | default `None` | Last 1-based line to read. |
| `binary_preview` | `str | None` | default `None` | Optional bounded binary preview mode, such as hex or base64 when supported. |
| `binary_preview_bytes` | `int` | default `256` | Number of bytes to include in a binary preview. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `read_file` -> `edit_file` or `apply_patch` -> `git_diff_tool`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `read_many_files`

**Vue d’ensemble.** Read multiple UTF-8 text files with the same optional line range. Use when comparing related small files or collecting context across a targeted path list; server settings cap file count and total bytes.

**Quand l’utiliser.** Use after locating candidate files and before making edits.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `paths` | `list[str]` | required | List of file paths, normally workspace-relative. |
| `start_line` | `int | None` | default `None` | First 1-based line to read. |
| `end_line` | `int | None` | default `None` | Last 1-based line to read. |
| `binary_preview` | `str | None` | default `None` | Optional bounded binary preview mode, such as hex or base64 when supported. |
| `binary_preview_bytes` | `int` | default `256` | Number of bytes to include in a binary preview. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `read_file` -> `edit_file` or `apply_patch` -> `git_diff_tool`.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `write_file`

**Vue d’ensemble.** Write a UTF-8 text file. Use to create a new file or intentionally replace a whole file. overwrite defaults to true; set overwrite=false when creating only if absent. For precise modifications to existing files, use edit_file or apply_patch.

**Quand l’utiliser.** Use only after reading enough context to make a precise, reviewable change.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `content` | `str` | required | UTF-8 text content to write. |
| `overwrite` | `bool` | default `True` | Whether an existing destination may be replaced. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `read_file` -> edit tool -> `git_diff_tool` -> tests.

**Notes.**

- Read the target first and show a diff after modification when working on code.

### `edit_file`

**Vue d’ensemble.** Replace exact text in a file. Use for small precise edits after reading the target file. old must match exactly, including whitespace and indentation; replace_all should be true only when every exact occurrence should change.

**Quand l’utiliser.** Use only after reading enough context to make a precise, reviewable change.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `old` | `str` | required | Exact text to replace. It must match whitespace and indentation. |
| `new` | `str` | required | Replacement text. |
| `replace_all` | `bool` | default `False` | Replace every exact occurrence instead of a single occurrence. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `read_file` -> edit tool -> `git_diff_tool` -> tests.

**Notes.**

- Read the target first and show a diff after modification when working on code.

### `multi_edit_file`

**Vue d’ensemble.** Apply multiple exact-text edits to one file. Use when several small replacements in the same file should be made together. Each old string must match exactly; read the file first to avoid stale or ambiguous edits.

**Quand l’utiliser.** Use only after reading enough context to make a precise, reviewable change.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `edits` | `list[dict]` | required | List of exact-text replacement objects for `multi_edit_file`. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `read_file` -> edit tool -> `git_diff_tool` -> tests.

**Notes.**

- Read the target first and show a diff after modification when working on code.

### `delete_file_or_dir`

**Vue d’ensemble.** Delete a file or directory inside the controlled workspace/container. Use only when removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully.

**Quand l’utiliser.** Delete a file or directory inside the controlled workspace/container. Use only when removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `recursive` | `bool` | default `False` | Whether to recurse into subdirectories. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** Use with the surrounding tools in the same family.

**Notes.**

- Read the target first and show a diff after modification when working on code.

### `apply_patch`

**Vue d’ensemble.** Apply a unified diff using git apply. Use for larger or multi-file edits where an exact patch is clearer than multiple edit_file calls. The patch is checked before application and cwd is workspace-relative unless full-container mode allows absolute paths.

**Quand l’utiliser.** Use only after reading enough context to make a precise, reviewable change.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `str` | required | Unified diff to validate and apply with `git apply`. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |

**Returns.** Returns a `ToolResult`. `data` contains file metadata, directory entries, matches, read content, or edit results depending on the operation.

**Common combinations.** `read_file` -> edit tool -> `git_diff_tool` -> tests.

**Notes.**

- Read the target first and show a diff after modification when working on code.

## File links

### `create_file_link`

**Vue d’ensemble.** Create a temporary browser-accessible download URL for a regular workspace file. Generated links are public bearer URLs protected by a high-entropy token, TTL, optional download-count limit, optional size limit, and explicit revocation.

**Quand l’utiliser.** Use when the user needs a browser-accessible download for a generated workspace file.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `ttl_s` | `int | None` | default `None` | Time-to-live in seconds. |
| `filename` | `str | None` | default `None` | Optional download filename shown to the browser. |
| `max_downloads` | `int | None` | default `None` | Maximum allowed downloads; `0` or omitted means no explicit per-link count limit depending on settings. |

**Returns.** Returns a `ToolResult`. `data` contains link metadata, generated URL, expiry, download limits, or revocation/listing status.

**Common combinations.** `create_file_link` -> share URL -> `revoke_file_link` when done.

**Notes.**

- Generated URLs are bearer links. Create them only for files that are safe to share and revoke them when finished.

### `list_file_links`

**Vue d’ensemble.** List generated file download URLs.

**Quand l’utiliser.** Use when the user needs a browser-accessible download for a generated workspace file.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `bool` | default `False` | Whether to include expired file links in the listing. |

**Returns.** Returns a `ToolResult`. `data` contains link metadata, generated URL, expiry, download limits, or revocation/listing status.

**Common combinations.** `create_file_link` -> share URL -> `revoke_file_link` when done.

**Notes.**

- Generated URLs are bearer links. Create them only for files that are safe to share and revoke them when finished.

### `revoke_file_link`

**Vue d’ensemble.** Revoke a generated file download URL.

**Quand l’utiliser.** Use when the user needs a browser-accessible download for a generated workspace file.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `token` | `str` | required | Opaque file-link token to revoke. |

**Returns.** Returns a `ToolResult`. `data` contains link metadata, generated URL, expiry, download limits, or revocation/listing status.

**Common combinations.** `create_file_link` -> share URL -> `revoke_file_link` when done.

**Notes.**

- Generated URLs are bearer links. Create them only for files that are safe to share and revoke them when finished.

## Git

### `git_clone_tool`

**Vue d’ensemble.** Clone a Git repository.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `repo_url` | `str` | required | Git repository URL. |
| `dest` | `str | None` | default `None` | Optional clone destination directory. |
| `branch` | `str | None` | default `None` | Branch name to clone or push. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_status_tool`

**Vue d’ensemble.** Run git status and list remotes.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_diff_tool`

**Vue d’ensemble.** Run git diff.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `staged` | `bool` | default `False` | Whether to show staged Git diff instead of unstaged diff. |
| `path` | `str | None` | default `None` | File or directory path, normally workspace-relative. |
| `stat` | `bool` | default `False` | Whether to show diff statistics instead of a full diff. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_log_tool`

**Vue d’ensemble.** Show recent git commits.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `max_count` | `int` | default `20` | Tool-specific argument. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_checkout_tool`

**Vue d’ensemble.** Checkout an existing ref or create a branch.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | required | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `ref` | `str` | required | Git ref, branch, tag, or commit. |
| `create` | `bool` | default `False` | Create a new branch while checking it out. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_fetch_tool`

**Vue d’ensemble.** Fetch a git remote.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `remote` | `str` | default `'origin'` | Git remote name, usually `origin`. |
| `prune` | `bool` | default `True` | Whether to prune removed remote-tracking references during fetch. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_pull_tool`

**Vue d’ensemble.** Pull current branch.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `ff_only` | `bool` | default `True` | Whether pull must be fast-forward only. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_add_tool`

**Vue d’ensemble.** Stage paths for commit.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `paths` | `list[str] | None` | default `None` | List of file paths, normally workspace-relative. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_commit_tool`

**Vue d’ensemble.** Create a git commit.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | required | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `message` | `str` | required | Commit message. |
| `all_changes` | `bool` | default `False` | Whether to include all changed tracked files in the commit operation. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_push_tool`

**Vue d’ensemble.** Push current HEAD to a remote branch.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | required | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `remote` | `str` | default `'origin'` | Git remote name, usually `origin`. |
| `branch` | `str | None` | default `None` | Branch name to clone or push. |
| `set_upstream` | `bool` | default `True` | Whether push should set upstream tracking for the branch. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_show_tool`

**Vue d’ensemble.** Show a commit, object, or file at ref:path.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `ref` | `str` | default `'HEAD'` | Git ref, branch, tag, or commit. |
| `path` | `str | None` | default `None` | File or directory path, normally workspace-relative. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `git_reset_tool`

**Vue d’ensemble.** Run git reset. Modes: soft, mixed, hard.

**Quand l’utiliser.** Use for source-control operations after checking repository status and user intent.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `mode` | `str` | default `'soft'` | Tool-specific argument. |
| `ref` | `str` | default `'HEAD'` | Git ref, branch, tag, or commit. |

**Returns.** Returns a `ToolResult`. `data` contains the underlying Git command result and captured output.

**Common combinations.** `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` -> `git_push_tool`.

**Notes.**

- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

## Browser automation

### `playwright_install_tool`

**Vue d’ensemble.** Install Playwright browser binaries in the container.

**Quand l’utiliser.** Use when rendered web/UI evidence is needed rather than raw HTTP or text files.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `with_deps` | `bool` | default `False` | Whether to install browser OS dependencies where supported. |

**Returns.** Returns a `ToolResult`. `data` contains Playwright operation status and output paths or extracted text.

**Common combinations.** `browser_get_text_tool` for text, `browser_screenshot_tool` for visual proof, `browser_pdf_tool` for printable capture.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

### `browser_screenshot_tool`

**Vue d’ensemble.** Open a URL with Playwright and save a screenshot.

**Quand l’utiliser.** Use when rendered web/UI evidence is needed rather than raw HTTP or text files.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `url` | `str` | required | URL opened by Playwright. |
| `output_path` | `str` | default `'screenshots/page.png'` | Workspace-relative path where an artifact such as a screenshot or PDF is saved. |
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `full_page` | `bool` | default `True` | Capture a full-page screenshot instead of only the viewport. |
| `width` | `int` | default `1440` | Viewport or PDF width in pixels. |
| `height` | `int` | default `1000` | Viewport or PDF height in pixels. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |

**Returns.** Returns a `ToolResult`. `data` contains Playwright operation status and output paths or extracted text.

**Common combinations.** `browser_get_text_tool` for text, `browser_screenshot_tool` for visual proof, `browser_pdf_tool` for printable capture.

**Notes.**

- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `browser_get_text_tool`

**Vue d’ensemble.** Open a URL with Playwright and return visible text for a selector.

**Quand l’utiliser.** Use when rendered web/UI evidence is needed rather than raw HTTP or text files.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `url` | `str` | required | URL opened by Playwright. |
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |
| `selector` | `str` | default `'body'` | CSS selector used to select visible text. |

**Returns.** Returns a `ToolResult`. `data` contains Playwright operation status and output paths or extracted text.

**Common combinations.** `browser_get_text_tool` for text, `browser_screenshot_tool` for visual proof, `browser_pdf_tool` for printable capture.

**Notes.**

- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `browser_eval_tool`

**Vue d’ensemble.** Open a URL with Playwright and evaluate JavaScript.

**Quand l’utiliser.** Use when rendered web/UI evidence is needed rather than raw HTTP or text files.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `url` | `str` | required | URL opened by Playwright. |
| `javascript` | `str` | required | JavaScript evaluated in the page context. |
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |

**Returns.** Returns a `ToolResult`. `data` contains Playwright operation status and output paths or extracted text.

**Common combinations.** `browser_get_text_tool` for text, `browser_screenshot_tool` for visual proof, `browser_pdf_tool` for printable capture.

**Notes.**

- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `browser_pdf_tool`

**Vue d’ensemble.** Open a URL with Chromium and save a PDF.

**Quand l’utiliser.** Use when rendered web/UI evidence is needed rather than raw HTTP or text files.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `url` | `str` | required | URL opened by Playwright. |
| `output_path` | `str` | default `'screenshots/page.pdf'` | Workspace-relative path where an artifact such as a screenshot or PDF is saved. |
| `width` | `int` | default `1440` | Viewport or PDF width in pixels. |
| `height` | `int` | default `1000` | Viewport or PDF height in pixels. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |

**Returns.** Returns a `ToolResult`. `data` contains Playwright operation status and output paths or extracted text.

**Common combinations.** `browser_get_text_tool` for text, `browser_screenshot_tool` for visual proof, `browser_pdf_tool` for printable capture.

**Notes.**

- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `playwright_run_script_tool`

**Vue d’ensemble.** Run a full Python Playwright script. Powerful; use in disposable containers.

**Quand l’utiliser.** Use when rendered web/UI evidence is needed rather than raw HTTP or text files.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `script` | `str` | required | Full Python Playwright script to execute. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `timeout_s` | `int` | default `60` | Command or script timeout in seconds. Public one-shot shell tools are capped by the server. |

**Returns.** Returns a `ToolResult`. `data` contains Playwright operation status and output paths or extracted text.

**Common combinations.** `browser_get_text_tool` for text, `browser_screenshot_tool` for visual proof, `browser_pdf_tool` for printable capture.

**Notes.**

- Arguments and output are also governed by runtime limits in the configuration reference.

## Remote worker lifecycle

### `remote_invite`

**Vue d’ensemble.** Create a one-time command for a remote machine to join this control server.

**Quand l’utiliser.** Use when managing the remote-worker connection itself before or after running remote work.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `name` | `str | None` | default `None` | Optional human-readable session or remote-worker name. |
| `workdir` | `str | None` | default `None` | Optional working directory used by the remote worker join command. |
| `ttl_s` | `int | None` | default `None` | Time-to-live in seconds. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_list_machines`

**Vue d’ensemble.** List remote worker machines connected to this control server.

**Quand l’utiliser.** Use when managing the remote-worker connection itself before or after running remote work.

**Inputs.** None.

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_rename_machine`

**Vue d’ensemble.** Rename a remote worker machine.

**Quand l’utiliser.** Use when managing the remote-worker connection itself before or after running remote work.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `new_name` | `str` | required | New human-readable remote-worker name. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_revoke_machine`

**Vue d’ensemble.** Revoke and remove a remote worker machine.

**Quand l’utiliser.** Use when managing the remote-worker connection itself before or after running remote work.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_environment_info`

**Vue d’ensemble.** Return remote workspace, auth, policy, and basic environment information.

**Quand l’utiliser.** Use when managing the remote-worker connection itself before or after running remote work.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

## Remote shell and Python

### `remote_run_shell_tool`

**Vue d’ensemble.** Run a shell command on a remote worker machine. timeout_s defaults to 10 seconds and may be set to at most 120 seconds.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `run_shell_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `command` | `str` | required | Shell command string executed by the configured shell. Keep one-shot commands non-interactive. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `timeout_s` | `int | None` | default `None` | Command or script timeout in seconds. Public one-shot shell tools are capped by the server. |
| `max_output_bytes` | `int | None` | default `None` | Maximum captured output bytes before truncation. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- For commands that stream, prompt, or run indefinitely, use the persistent shell tools instead.

### `remote_run_python_tool`

**Vue d’ensemble.** Write Python code to a temporary file and execute it on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `run_python_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `code` | `str` | required | Python source code written to a temporary file and executed. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `timeout_s` | `int` | default `60` | Command or script timeout in seconds. Public one-shot shell tools are capped by the server. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_shell_start`

**Vue d’ensemble.** Start a persistent shell session on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `shell_start` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `name` | `str | None` | default `None` | Optional human-readable session or remote-worker name. |
| `command` | `str | None` | default `None` | Shell command string executed by the configured shell. Keep one-shot commands non-interactive. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_shell_send`

**Vue d’ensemble.** Send input to a persistent remote shell session.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `shell_send` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `session_id` | `str` | required | Persistent shell session identifier returned by `shell_start` or `remote_shell_start`. |
| `input_text` | `str` | required | Text sent to a persistent shell session. |
| `enter` | `bool` | default `True` | Whether to append Enter/newline after `input_text`. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_shell_read`

**Vue d’ensemble.** Read recent output from a persistent remote shell session.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `shell_read` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `session_id` | `str` | required | Persistent shell session identifier returned by `shell_start` or `remote_shell_start`. |
| `lines` | `int` | default `200` | Number of recent output or audit lines to return. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_shell_kill`

**Vue d’ensemble.** Kill a persistent remote shell session.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `shell_kill` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `session_id` | `str` | required | Persistent shell session identifier returned by `shell_start` or `remote_shell_start`. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_shell_list`

**Vue d’ensemble.** List persistent shell sessions on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `shell_list` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

## Remote filesystem, search, and patching

### `remote_list_files`

**Vue d’ensemble.** List files and directories on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `list_files` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `path` | `str` | default `'.'` | File or directory path, normally workspace-relative. |
| `recursive` | `bool` | default `False` | Whether to recurse into subdirectories. |
| `max_entries` | `int` | default `500` | Maximum number of directory or tree entries to return. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_tree_view`

**Vue d’ensemble.** Return a compact directory tree from a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `tree_view` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `depth` | `int` | default `3` | Directory tree depth. |
| `max_entries` | `int` | default `500` | Maximum number of directory or tree entries to return. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_glob_search`

**Vue d’ensemble.** Find files by glob pattern on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `glob_search` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `pattern` | `str` | required | Glob pattern for file-path discovery. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `max_results` | `int` | default `500` | Maximum number of matches or paths to return. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_grep_search`

**Vue d’ensemble.** Search remote file contents using ripgrep.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `grep_search` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `query` | `str` | required | Search string. For `grep_search`, it is a ripgrep pattern when `regex=true`; for connector `search`, it is a plain discovery query. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `glob` | `str | None` | default `None` | Optional glob filter for content search. |
| `regex` | `bool` | default `True` | Whether the search query is treated as a regular expression. |
| `case_sensitive` | `bool` | default `True` | Whether matching is case-sensitive. |
| `max_results` | `int | None` | default `None` | Maximum number of matches or paths to return. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_read_file`

**Vue d’ensemble.** Read a UTF-8 text file on a remote worker, optionally by line range.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `read_file` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `start_line` | `int | None` | default `None` | First 1-based line to read. |
| `end_line` | `int | None` | default `None` | Last 1-based line to read. |
| `binary_preview` | `str | None` | default `None` | Optional bounded binary preview mode, such as hex or base64 when supported. |
| `binary_preview_bytes` | `int` | default `256` | Number of bytes to include in a binary preview. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_read_many_files`

**Vue d’ensemble.** Read multiple UTF-8 text files on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `read_many_files` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `paths` | `list[str]` | required | List of file paths, normally workspace-relative. |
| `start_line` | `int | None` | default `None` | First 1-based line to read. |
| `end_line` | `int | None` | default `None` | Last 1-based line to read. |
| `binary_preview` | `str | None` | default `None` | Optional bounded binary preview mode, such as hex or base64 when supported. |
| `binary_preview_bytes` | `int` | default `256` | Number of bytes to include in a binary preview. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_write_file`

**Vue d’ensemble.** Write a UTF-8 text file on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `write_file` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `content` | `str` | required | UTF-8 text content to write. |
| `overwrite` | `bool` | default `True` | Whether an existing destination may be replaced. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Read the target first and show a diff after modification when working on code.

### `remote_edit_file`

**Vue d’ensemble.** Replace exact text in a remote file.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `edit_file` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `old` | `str` | required | Exact text to replace. It must match whitespace and indentation. |
| `new` | `str` | required | Replacement text. |
| `replace_all` | `bool` | default `False` | Replace every exact occurrence instead of a single occurrence. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Read the target first and show a diff after modification when working on code.

### `remote_multi_edit_file`

**Vue d’ensemble.** Apply multiple exact-text edits to one remote file.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `multi_edit_file` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `edits` | `list[dict]` | required | List of exact-text replacement objects for `multi_edit_file`. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Read the target first and show a diff after modification when working on code.

### `remote_delete_file_or_dir`

**Vue d’ensemble.** Delete a file or directory on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `delete_file_or_dir` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `path` | `str` | required | File or directory path, normally workspace-relative. |
| `recursive` | `bool` | default `False` | Whether to recurse into subdirectories. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Read the target first and show a diff after modification when working on code.

### `remote_apply_patch`

**Vue d’ensemble.** Apply a unified diff on a remote worker using git apply.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `apply_patch` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `patch` | `str` | required | Unified diff to validate and apply with `git apply`. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Read the target first and show a diff after modification when working on code.

## Remote file transfer

### `remote_copy_file`

**Vue d’ensemble.** Copy a file from one remote worker machine to another through the control server.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `copy_file` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `src_machine` | `str` | required | Source remote worker identifier. |
| `src_path` | `str` | required | Source path on the source remote worker. |
| `dst_machine` | `str` | required | Destination remote worker identifier. |
| `dst_path` | `str` | required | Destination path on the destination remote worker. |
| `overwrite` | `bool` | default `True` | Whether an existing destination may be replaced. |
| `chunk_size` | `int | None` | default `None` | Optional transfer chunk size. Leave unset unless tuning large transfers. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_copy_dir`

**Vue d’ensemble.** Copy a directory tree from one remote worker machine to another through the control server.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `copy_dir` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `src_machine` | `str` | required | Source remote worker identifier. |
| `src_path` | `str` | required | Source path on the source remote worker. |
| `dst_machine` | `str` | required | Destination remote worker identifier. |
| `dst_path` | `str` | required | Destination path on the destination remote worker. |
| `overwrite` | `bool` | default `False` | Whether an existing destination may be replaced. |
| `chunk_size` | `int | None` | default `None` | Optional transfer chunk size. Leave unset unless tuning large transfers. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_pull_file`

**Vue d’ensemble.** Copy a file from a remote worker to the control server workspace.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `pull_file` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `remote_path` | `str` | required | Path on the remote worker. |
| `local_path` | `str` | required | Path on the control-server workspace. |
| `overwrite` | `bool` | default `True` | Whether an existing destination may be replaced. |
| `chunk_size` | `int | None` | default `None` | Optional transfer chunk size. Leave unset unless tuning large transfers. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_push_file`

**Vue d’ensemble.** Copy a file from the control server workspace to a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `push_file` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `local_path` | `str` | required | Path on the control-server workspace. |
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `remote_path` | `str` | required | Path on the remote worker. |
| `overwrite` | `bool` | default `True` | Whether an existing destination may be replaced. |
| `chunk_size` | `int | None` | default `None` | Optional transfer chunk size. Leave unset unless tuning large transfers. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_pull_dir`

**Vue d’ensemble.** Copy a directory tree from a remote worker to the control server workspace.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `pull_dir` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `remote_path` | `str` | required | Path on the remote worker. |
| `local_path` | `str` | required | Path on the control-server workspace. |
| `overwrite` | `bool` | default `False` | Whether an existing destination may be replaced. |
| `chunk_size` | `int | None` | default `None` | Optional transfer chunk size. Leave unset unless tuning large transfers. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_push_dir`

**Vue d’ensemble.** Copy a directory tree from the control server workspace to a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `push_dir` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `local_path` | `str` | required | Path on the control-server workspace. |
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `remote_path` | `str` | required | Path on the remote worker. |
| `overwrite` | `bool` | default `False` | Whether an existing destination may be replaced. |
| `chunk_size` | `int | None` | default `None` | Optional transfer chunk size. Leave unset unless tuning large transfers. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

## Remote Git

### `remote_git_clone_tool`

**Vue d’ensemble.** Clone a Git repository on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_clone_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `repo_url` | `str` | required | Git repository URL. |
| `dest` | `str | None` | default `None` | Optional clone destination directory. |
| `branch` | `str | None` | default `None` | Branch name to clone or push. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_status_tool`

**Vue d’ensemble.** Run git status on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_status_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_diff_tool`

**Vue d’ensemble.** Run git diff on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_diff_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `staged` | `bool` | default `False` | Whether to show staged Git diff instead of unstaged diff. |
| `path` | `str | None` | default `None` | File or directory path, normally workspace-relative. |
| `stat` | `bool` | default `False` | Whether to show diff statistics instead of a full diff. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_log_tool`

**Vue d’ensemble.** Show recent git commits on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_log_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `max_count` | `int` | default `20` | Tool-specific argument. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_checkout_tool`

**Vue d’ensemble.** Checkout an existing ref or create a branch on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_checkout_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | required | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `ref` | `str` | required | Git ref, branch, tag, or commit. |
| `create` | `bool` | default `False` | Create a new branch while checking it out. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_fetch_tool`

**Vue d’ensemble.** Fetch a git remote on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_fetch_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `remote` | `str` | default `'origin'` | Git remote name, usually `origin`. |
| `prune` | `bool` | default `True` | Whether to prune removed remote-tracking references during fetch. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_pull_tool`

**Vue d’ensemble.** Pull current branch on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_pull_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `ff_only` | `bool` | default `True` | Whether pull must be fast-forward only. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_add_tool`

**Vue d’ensemble.** Stage paths on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_add_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `paths` | `list[str] | None` | default `None` | List of file paths, normally workspace-relative. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_commit_tool`

**Vue d’ensemble.** Create a git commit on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_commit_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | required | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `message` | `str` | required | Commit message. |
| `all_changes` | `bool` | default `False` | Whether to include all changed tracked files in the commit operation. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_push_tool`

**Vue d’ensemble.** Push current HEAD from a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_push_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | required | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `remote` | `str` | default `'origin'` | Git remote name, usually `origin`. |
| `branch` | `str | None` | default `None` | Branch name to clone or push. |
| `set_upstream` | `bool` | default `True` | Whether push should set upstream tracking for the branch. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_show_tool`

**Vue d’ensemble.** Show a commit, object, or file at ref:path on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_show_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `ref` | `str` | default `'HEAD'` | Git ref, branch, tag, or commit. |
| `path` | `str | None` | default `None` | File or directory path, normally workspace-relative. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

### `remote_git_reset_tool`

**Vue d’ensemble.** Run git reset on a remote worker. Modes: soft, mixed, hard.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `git_reset_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `mode` | `str` | default `'soft'` | Tool-specific argument. |
| `ref` | `str` | default `'HEAD'` | Git ref, branch, tag, or commit. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Prefer `git_status_tool` and `git_diff_tool` before commit/push operations.

## Remote browser automation

### `remote_playwright_install_tool`

**Vue d’ensemble.** Install Playwright browser binaries on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `playwright_install_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `with_deps` | `bool` | default `False` | Whether to install browser OS dependencies where supported. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

### `remote_browser_screenshot_tool`

**Vue d’ensemble.** Open a URL with Playwright on a remote worker and save a screenshot.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `browser_screenshot_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `url` | `str` | required | URL opened by Playwright. |
| `output_path` | `str` | default `'screenshots/page.png'` | Workspace-relative path where an artifact such as a screenshot or PDF is saved. |
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `full_page` | `bool` | default `True` | Capture a full-page screenshot instead of only the viewport. |
| `width` | `int` | default `1440` | Viewport or PDF width in pixels. |
| `height` | `int` | default `1000` | Viewport or PDF height in pixels. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `remote_browser_get_text_tool`

**Vue d’ensemble.** Open a URL with Playwright on a remote worker and return visible text.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `browser_get_text_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `url` | `str` | required | URL opened by Playwright. |
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |
| `selector` | `str` | default `'body'` | CSS selector used to select visible text. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `remote_browser_eval_tool`

**Vue d’ensemble.** Open a URL with Playwright on a remote worker and evaluate JavaScript.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `browser_eval_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `url` | `str` | required | URL opened by Playwright. |
| `javascript` | `str` | required | JavaScript evaluated in the page context. |
| `browser` | `str` | default `'chromium'` | Playwright browser name, usually `chromium`. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `remote_browser_pdf_tool`

**Vue d’ensemble.** Open a URL with Chromium on a remote worker and save a PDF.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `browser_pdf_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `url` | `str` | required | URL opened by Playwright. |
| `output_path` | `str` | default `'screenshots/page.pdf'` | Workspace-relative path where an artifact such as a screenshot or PDF is saved. |
| `width` | `int` | default `1440` | Viewport or PDF width in pixels. |
| `height` | `int` | default `1000` | Viewport or PDF height in pixels. |
| `wait_until` | `str` | default `'networkidle'` | Playwright load-state condition such as `networkidle`. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.
- Saved screenshots and PDFs are written into the runtime workspace unless an absolute path is permitted by policy.

### `remote_playwright_run_script_tool`

**Vue d’ensemble.** Run a full Python Playwright script on a remote worker.

**Quand l’utiliser.** Use when the target files, commands, browser session, or Git repository live on a connected remote worker. It mirrors `playwright_run_script_tool` where applicable and adds a required `machine` argument.

**Inputs.**

| Name | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `str` | required | Remote worker machine name or identifier. |
| `script` | `str` | required | Full Python Playwright script to execute. |
| `cwd` | `str` | default `'.'` | Working directory. Normally workspace-relative; absolute paths are allowed only when policy permits them. |
| `timeout_s` | `int` | default `60` | Command or script timeout in seconds. Public one-shot shell tools are capped by the server. |

**Returns.** Returns a `ToolResult`. Lifecycle tools return invite, machine, or revocation metadata; remote operations proxy the corresponding remote result.

**Common combinations.** `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> remote operation -> `remote_revoke_machine` when done.

**Notes.**

- Remote tools depend on the worker being online and having the necessary host tools installed.
- Run `remote_list_machines` and `remote_environment_info` before assuming paths or dependencies.

## Client-author notes

- `/mcp` exposes the full MCP tool surface. Connector-style `search` and `fetch` are intentionally read-only and limited.
- Tool availability can depend on runtime configuration. Remote tools are removed when remote-worker mode is disabled.
- Clients should use MCP discovery as the schema source of truth and treat this page as human guidance.
- Long-running commands should use persistent shell sessions instead of one blocking command response.
