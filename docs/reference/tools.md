# Tools reference

This page is generated from the actual MCP tool schemas. Run `python scripts/generate-tools-reference.py` after changing the public tool surface.

All tools except connector-style `search` and `fetch` return a structured `ToolResult` containing `ok`, `message`, and `data`. Most execution and file tools accept an optional `machine`; omit it for the controller workspace and provide it for a connected worker. Git operations intentionally use `run_shell_tool` or another shell tool rather than dedicated Git wrappers.

## Selection guide

| Need | Preferred tools |
|---|---|
| Inspect an environment | `environment_info`, `tree_view`, `read_file` |
| Run a short command or Git operation | `run_shell_tool` |
| Run an interactive or long task | `shell_start` or `job_start` |
| Make exact file changes | `edit_file` or `apply_patch` |
| Transfer a file or directory | `transfer_path` |
| Capture a page | `browser_get_text_tool` or `browser_capture_tool` |
| Work on a remote machine | use the same tool with `machine`; use `remote_*` only for worker administration |

## Connector and discovery

### `search`

Search workspace files and return ChatGPT connector-compatible results.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |

OAuth scopes: `shell:read`.

### `fetch`

Fetch a workspace file by id returned from search.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `id` | `string` | required |  |

OAuth scopes: `shell:read`.

## Environment, skills, and task state

### `environment_info`

Return version, workspace, auth, policy, and environment information locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `skills_list`

List installed agent skills without loading their instructions. The MCP tool surface stays fixed; adding or removing skill directories is reflected on the next call.

OAuth scopes: `shell:read`.

### `skill_load`

Load one installed agent skill by the exact name returned from skills_list. Returns SKILL.md instructions plus related file paths.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |

OAuth scopes: `shell:read`.

### `skill_read_file`

Read one related text file from an installed Skill.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |

OAuth scopes: `shell:read`.

### `secret_scan`

Scan local workspace text files for common secrets before commit or push.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |

OAuth scopes: `shell:read`.

### `todo_read_tool`

Read the local agent todo list.

OAuth scopes: `shell:read`.

### `todo_write_tool`

Write the local agent todo list.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `todos` | `array[object]` | required |  |

OAuth scopes: `shell:read, shell:write`.

### `audit_tail`

Read recent local audit log entries.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |

OAuth scopes: `shell:read`.

## Shells and jobs

### `run_shell_tool`

Run one non-interactive shell command locally or on a remote machine. Use for build, test, package-manager, Git, and inspection commands that should finish promptly. For long-running, interactive, or streaming processes, use shell_start or job_start. Optional purpose/explanation fields let agents state why the command is being run.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `run_python_tool`

Write and run a short Python script locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `shell_start`

Start a persistent interactive shell locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `shell_send`

Send input to a persistent local or remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `shell_read`

Read recent output from a persistent local or remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `shell_kill`

Terminate a persistent local or remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `shell_list`

List persistent shell sessions locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `job_start`

Start a tracked long-running job locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `job_list`

List tracked jobs locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `job_tail`

Read recent output for a tracked local or remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `job_stop`

Stop a tracked local or remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `job_retry`

Restart a stopped or exited tracked local or remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## Files and transfer

### `list_files`

List files and directories locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `tree_view`

Return a compact directory tree locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `glob_search`

Find paths by glob locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `grep_search`

Search file contents locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `read_file`

Read one file or a list of files locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `write_file`

Write a UTF-8 text file locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `edit_file`

Apply one or more exact-text edits to one local or remote file. Each edits entry contains old, new, and optional replace_all; old must match exactly, including whitespace and indentation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[object]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `delete_file_or_dir`

Delete a local or remote file or directory. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `apply_patch`

Check and apply a unified diff locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `transfer_path`

Copy a file or directory between the controller and remote machines. A missing machine denotes the controller; at least one endpoint must be remote.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write`.

At least one of `source_machine` and `destination_machine` must be supplied. Omitted endpoints refer to the controller workspace; the source may be either a file or a directory.

### `create_file_link`

Create a temporary browser-accessible download URL for a local file. Links are public bearer URLs protected by a high-entropy token, TTL, optional download-count limit, and explicit revocation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |

OAuth scopes: `shell:read, file:share`.

### `list_file_links`

List generated local file download URLs.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |

OAuth scopes: `shell:read, file:share`.

### `revoke_file_link`

Revoke a generated local file download URL.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |

OAuth scopes: `shell:read, file:share`.

## Browser automation

### `browser_capture_tool`

Open a URL and save a PNG screenshot or PDF locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `url` | `string` | required |  |
| `output_path` | `string \| null` | `null` |  |
| `capture_format` | `string` | `"png"` |  |
| `browser` | `string` | `"chromium"` |  |
| `full_page` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `wait_until` | `string` | `"networkidle"` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `browser:use, shell:write`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `browser_get_text_tool`

Open a URL and return visible text locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `url` | `string` | required |  |
| `browser` | `string` | `"chromium"` |  |
| `wait_until` | `string` | `"networkidle"` |  |
| `selector` | `string` | `"body"` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `browser:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `playwright_run_script_tool`

Run a full Python Playwright script locally or on a remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |

OAuth scopes: `browser:use, shell:execute`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## Remote worker administration

### `remote_invite`

Create a one-time command for a remote machine to join this server.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |

OAuth scopes: `remote:use`.

### `remote_list_machines`

List registered remote worker machines.

OAuth scopes: `remote:use`.

### `remote_revoke_machine`

Revoke and remove a remote worker machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string` | required |  |

OAuth scopes: `remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `remote_rename_machine`

Rename a remote worker machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string` | required |  |
| `new_name` | `string` | required |  |

OAuth scopes: `remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.
