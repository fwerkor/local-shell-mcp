<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Tools reference

이 페이지는 실제 MCP tool schema에서 구성됩니다. Public tool surface를 변경한 뒤 `python scripts/generate-tools-reference.py`를 실행해 English reference를 갱신하십시오.

대부분의 tool은 `ok`, `message`, `data`를 포함한 구조화된 `ToolResult`를 반환합니다. `workspace_open`은 MCP App 렌더링에 사용되는 model-visible state를 반환합니다. 대부분의 실행/파일 tool은 optional `machine`을 받으며, 생략하면 controller workspace, 지정하면 연결된 worker에서 실행합니다. Git 작업은 전용 wrapper 대신 의도적으로 `run_shell` 또는 다른 shell tool을 사용합니다.

## 선택 가이드

| 필요 | 권장 tools |
|---|---|
| ChatGPT에서 실행을 모니터링하거나 협업 | `workspace_open` |
| Environment 검사 | `environment_get`, `file_tree`, `file_read` |
| 짧은 command 또는 Git operation 실행 | `run_shell` |
| Interactive/long task 실행 | `shell_start` or `job_start` |
| File을 정확히 변경 | `file_edit` or `file_patch` |
| File/directory 전송 | `remote_transfer` |
| External MCP capability 발견 | `mcp_tool_search`, then `mcp_tool_inspect` |
| Page와 interaction | `browser_session`, `browser_snapshot`, then `browser_act` |
| Custom browser logic 실행 | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Remote machine 작업 | 동일 tool에 `machine`을 지정하고 worker administration에만 `remote_*` 사용 |

## Interactive workspace

### `workspace_open`

명시적으로 지정한 Logical Session을 표시하는 Live Workspace를 열거나 재사용합니다. session_manage가 반환한 active session_id를 전달합니다. Workspace는 MCP transport에서 task identity를 추론하지 않으며, active Logical Session이 없을 때는 null을 명시적으로 전달합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

## Environment, Skills 및 task state

### `environment_get`

Local 또는 remote machine의 version, workspace, auth, policy, environment information을 반환합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `skill_list`

Instructions를 로드하지 않고 installed Agent Skills를 나열합니다. MCP tool surface는 고정되며 Skill directories 추가/삭제는 다음 call에 반영됩니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

`skill_list`가 반환한 exact name으로 installed Skill을 로드하고 전체 `SKILL.md` instructions와 related file paths를 반환합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Installed Skill의 related text file 하나를 읽습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Commit/push 전에 local workspace text files에서 common secrets를 scan합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

하나의 durable Logical Session을 관리합니다. start는 새 task를 만들고 session_id를 반환합니다. resume은 사용자가 명시적으로 제공했거나 이 conversation에 이미 있는 session_id만 계속. start 이외의 모든 action에는 session_id가 필요합니다. Action: start, resume, get, report, finish, cancel, delete. report는 summary/findings/next/blockers/objective/label을 받고, delete에는 terminal Session이 필요합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

명시적 Logical Session의 optional Goal mode를 관리합니다. active plan은 agent activity가 15분 없으면 automatic continuation을 활성화하며 최대 10회로 제한됩니다. session_id는 session_manage가 반환한 동일한 durable id여야 합니다. Action: start, get, update, block, resume, finish, cancel. start에는 objective와 steps가 필요하고 finish에는 모든 steps가 completed 또는 skipped여야 합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

Recent local audit log entries를 읽습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells 및 jobs

### `run_shell`

Local 또는 remote machine에서 non-interactive shell command 하나를 실행합니다. 빠르게 끝나야 하는 build, test, package-manager, Git, inspection command에 사용하며 long-running, interactive, streaming process에는 `shell_start` 또는 `job_start`를 사용합니다. Optional purpose/explanation fields로 실행 이유를 설명할 수 있습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `run_python`

Local 또는 remote machine에서 short Python script를 작성하고 실행합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `shell_start`

Local 또는 remote machine에서 persistent interactive shell을 시작합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `shell_send`

Persistent local/remote shell session에 input을 보냅니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `shell_read`

Persistent local/remote shell session의 recent output을 읽습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `shell_stop`

Persistent local/remote shell session을 종료합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `shell_list`

Local 또는 remote machine의 persistent shell sessions를 나열합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `job_start`

Local 또는 remote machine에서 tracked long-running job을 시작합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `job_list`

Local 또는 remote machine의 tracked jobs를 나열합니다. Active job을 먼저 반환하며 `limit`은 1-1000 범위로 제한됩니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `job_tail`

Tracked local/remote job의 recent output을 읽습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `job_stop`

Tracked local/remote job을 중지합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `job_retry`

Stopped/exited tracked local/remote job을 다시 시작합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

## Files 및 transfer

### `file_list`

Local 또는 remote machine의 files/directories를 나열합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_tree`

Local 또는 remote machine의 compact directory tree를 반환합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_glob`

Local 또는 remote machine에서 glob으로 paths를 찾습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_grep`

Local 또는 remote machine의 file contents를 검색합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_read`

Local 또는 remote machine의 file 하나 또는 file list를 읽습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `image_view`

PNG, JPEG, GIF, WebP file을 native MCP image content로 표시합니다. Visual inspection이 필요하면 `file_read` 대신 사용합니다. Remote image는 기존 file-transfer protocol을 재사용하므로 worker에 image-specific RPC가 필요 없습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_write`

Local 또는 remote machine에 UTF-8 text file을 씁니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_edit`

하나의 local/remote file에 하나 이상의 exact-text edits를 적용합니다. 각 edit에는 old, new, optional `replace_all`이 있고 old는 whitespace와 indentation까지 exact match해야 합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_delete`

Local/remote file 또는 directory를 삭제합니다. `recursive=false`는 file/empty directory만 삭제하고 non-empty directory에는 `recursive=true`가 필요하며 주의해서 사용해야 합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `file_patch`

Local 또는 remote에서 unified diff 또는 file_patch envelope를 검사하고 적용합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `remote_transfer`

controller와 remote machine 사이에서 file/directory를 복사하는 tracked job을 시작합니다. remote upload는 resumable raw-binary chunk를 사용하며 `job_list`, `job_tail`, `job_stop`, `job_retry`로 transfer를 관리합니다.

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
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`source_machine`과 `destination_machine` 중 하나 이상을 지정해야 합니다. 생략한 endpoint는 controller workspace를 뜻하며 source는 file 또는 directory일 수 있습니다.

### `link_create`

Local file용 temporary browser-accessible URL을 생성합니다. Default는 attachment download이며 browser/Markdown image에서 직접 render하려면 `inline=true`로 설정합니다. Link는 high-entropy token, TTL, optional download-count limit, explicit revocation으로 보호되는 public bearer URL입니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Generated local file download URLs를 나열합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Generated local file download URL을 revoke합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Dynamic MCP servers의 isolated environment/headers를 register, list, get, enable, disable, refresh, remove, update합니다. `stdio` transport는 command/args/cwd, `streamable_http`는 url을 사용합니다. Secret env/header values는 private하게 persist되며 반환되지 않습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Enabled dynamic MCP servers의 cached lightweight tool summaries를 검색합니다. Dynamic tools는 이 server의 `tools/list`에 들어가지 않으므로 반환된 `<server>:<tool>` name을 `mcp_tool_inspect`로 inspect한 뒤 call합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

`<server>:<tool>`이라는 dynamic MCP tool의 full cached schema를 반환합니다. Cache가 stale하면 `mcp_manage`로 server를 refresh합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Cached dynamic MCP tool `<server>:<tool>`을 call합니다. `mcp_tool_search`로 discover하고 `mcp_tool_inspect`로 schema를 확인한 뒤 사용합니다. External MCP connection은 call 기간에만 열립니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Local/remote persistent high-level browser sessions를 start, list, close, cleanup합니다. `start`는 URL open, persistent `profile_id` reuse, `storage_state_path` load가 가능하고 `close`는 storage state를 save할 수 있습니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `browser_snapshot`

Persistent browser page의 title, URL, bounded visible text, `e1` 같은 stable short refs가 있는 interactive elements, recent page/network errors, optional screenshot path를 capture합니다. Page navigation 또는 새 snapshot 전까지 refs를 `browser_act` targets로 직접 사용합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `browser_act`

Persistent browser session에서 structured actions를 실행합니다. navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text, wait_for_url을 지원합니다. Target은 `browser_snapshot`의 `e1` 같은 ref 또는 CSS selector이며 high-level actions가 부족할 때만 `browser_run_script`를 사용합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

### `browser_run_script`

Local 또는 remote machine에서 full Python Playwright script를 실행합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.

## 데스크톱 GUI 자동화

### `gui_list`

List visible desktop application windows and GUI backend capabilities locally or remotely.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_state`

Observe one desktop window before acting. Returns its accessibility elements plus an optional native MCP screenshot and a short-lived state_id. Prefer element_id actions; coordinate actions are relative to the observed window and are rejected if the window moved or resized.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_action`

Execute GUI actions against a fresh gui_state observation locally or remotely. The state_id is single-use. Prefer semantic element_id targeting; raw x/y coordinates are window-relative. Supported actions are click, double_click, right_click, move, scroll, drag, type, key, set_value, focus, and wait.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `state_id` | `string` | required |  |
| `actions` | `array[GuiAction]` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## Remote worker administration

### `remote_manage`

action=invite, list, revoke, rename으로 remote workers를 관리합니다. invite는 name/workdir/ttl_s, revoke는 machine, rename은 machine과 new_name이 필요합니다.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 이 tool call이 속한 Logical Session입니다. task를 수행하는 동안 session_manage가 반환한 session_id를 전달합니다. active Logical Session이 없을 때만 null을 사용합니다. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine`을 지정하면 이 call에는 추가로 `remote:use`가 필요하며 remote worker protocol을 통해 실행됩니다.
