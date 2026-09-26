<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Tools reference

このページは実際の MCP tool schema から構成されます。Public tool surface を変更した後は `python scripts/generate-tools-reference.py` を実行して English reference を更新します。

ほとんどの tool は `ok`、`message`、`data` を含む構造化 `ToolResult` を返します。`workspace_open` は MCP App の描画に使う model-visible state を返します。多くの execution/file tool は optional `machine` を受け取り、省略時は controller workspace、指定時は接続済み worker で実行します。Git 操作は専用 wrapper ではなく、意図的に `run_shell` などの shell tool を使います。

## 選択ガイド

| 目的 | 推奨 tools |
|---|---|
| ChatGPT で実行を監視または協働 | `workspace_open` |
| Environment を調査 | `environment_get`, `file_tree`, `file_read` |
| 短い command または Git operation を実行 | `run_shell` |
| Interactive / long task を実行 | `shell_start` or `job_start` |
| File を正確に変更 | `file_edit` or `file_patch` |
| File/directory を転送 | `remote_transfer` |
| External MCP capability を発見 | `mcp_tool_search`, then `mcp_tool_inspect` |
| Page と interaction | `browser_session`, `browser_snapshot`, then `browser_act` |
| Custom browser logic を実行 | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Remote machine で作業 | 同じ tool に `machine` を指定し、worker administration のみ `remote_*` を使う |

## Interactive workspace

### `workspace_open`

明示的に指定した Logical Session を表示する Live Workspace を開くか再利用します。session_manage が返した active な session_id を渡します。Workspace は MCP transport から task identity を推測しません。active な Logical Session がない場合は明示的に null を渡します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

## Environment、Skills、task state

### `environment_get`

Local または remote machine の version、workspace、auth、policy、environment information を返します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `skill_list`

Instructions を読み込まず installed Agent Skills を列挙します。MCP tool surface は固定され、Skill directories の追加/削除は次の call に反映されます。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

`skill_list` が返した exact name で installed Skill を読み込み、完全な `SKILL.md` instructions と related file paths を返します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Installed Skill の related text file を 1 つ読み取ります。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Commit/push 前に local workspace text files を common secrets について scan します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

1 つの durable Logical Session を管理します。start は新しい task を作成して session_id を返します。resume は user が明示的に指定した、またはこの conversation にすでに存在する session_id だけを継続します。start 以外の全 action には session_id が必要です。Action: start, resume, get, report, finish, cancel, delete。report は summary/findings/next/blockers/objective/label を受け取り、delete には terminal Session が必要です。

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

明示的な Logical Session の optional Goal mode を管理します。active plan は agent activity が 15 分ない場合に automatic continuation を有効化し、最大 10 回まで試行します。session_id は session_manage が返した同じ durable id でなければならず。Action: start, get, update, block, resume, finish, cancel。start には objective と steps、finish には全 steps が completed または skipped であることが必要です。

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

Recent local audit log entries を読み取ります。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells と jobs

### `run_shell`

Local または remote machine で non-interactive shell command を 1 回実行します。速やかに完了する build、test、package-manager、Git、inspection commands に使い、long-running、interactive、streaming process には `shell_start` または `job_start` を使います。Optional purpose/explanation fields で実行理由を示せます。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `run_python`

Local または remote machine で short Python script を書いて実行します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `shell_start`

Local または remote machine で persistent interactive shell を開始します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `shell_send`

Persistent local/remote shell session に input を送ります。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `shell_read`

Persistent local/remote shell session の recent output を読みます。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `shell_stop`

Persistent local/remote shell session を終了します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `shell_list`

Local または remote machine の persistent shell sessions を列挙します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `job_start`

Local または remote machine で tracked long-running job を開始します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `job_list`

Local または remote machine の tracked jobs を列挙します。Active job を先に返し、`limit` は 1-1000 の範囲に制限されます。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `job_tail`

Tracked local/remote job の recent output を読み取ります。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `job_stop`

Tracked local/remote job を停止します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `job_retry`

Stopped/exited tracked local/remote job を再起動します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

## Files と transfer

### `file_list`

Local または remote machine の files/directories を列挙します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_tree`

Local または remote machine の compact directory tree を返します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_glob`

Local または remote machine で glob により paths を検索します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_grep`

Local または remote machine の file contents を検索します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_read`

Local または remote machine の file 1 個または file list を読み取ります。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `image_view`

PNG、JPEG、GIF、WebP file を native MCP image content として表示します。Visual inspection が必要な場合は `file_read` よりこちらを使います。Remote images は既存 file-transfer protocol を再利用するため、worker に image-specific RPC は不要です。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_write`

Local または remote machine に UTF-8 text file を書き込みます。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_edit`

1 つの local/remote file に 1 件以上の exact-text edits を適用します。各 edit は old、new、optional `replace_all` を含み、old は whitespace/indentation を含め exact match する必要があります。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_delete`

Local/remote file または directory を削除します。`recursive=false` は file/empty directory のみ、non-empty directory には `recursive=true` が必要で、慎重に使うべきです。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `file_patch`

Local または remote で unified diff / file_patch envelope を検証して適用します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `remote_transfer`

controller と remote machine の間で file/directory を copy する tracked job を開始します。remote upload は resumable raw-binary chunk を使い、`job_list`、`job_tail`、`job_stop`、`job_retry` で transfer を管理します。

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
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`source_machine` と `destination_machine` の少なくとも一方を指定する必要があります。省略した endpoint は controller workspace を表し、source は file または directory のどちらでも構いません。

### `link_create`

Local file 用の temporary browser-accessible URL を作成します。Default は attachment download で、browser/Markdown image に直接 render する場合は `inline=true`。Link は high-entropy token、TTL、optional download-count limit、explicit revocation で保護された public bearer URL です。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Generated local file download URLs を列挙します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Generated local file download URL を revoke します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Dynamic MCP servers の isolated environment/headers を register、list、get、enable、disable、refresh、remove、update します。`stdio` transport は command/args/cwd、`streamable_http` は url を使用します。Secret env/header values は private に persist され、返されません。

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
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Enabled dynamic MCP servers の cached lightweight tool summaries を検索します。Dynamic tools はこの server の `tools/list` に入らないため、返された `<server>:<tool>` name を `mcp_tool_inspect` で inspect してから call します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

`<server>:<tool>` という dynamic MCP tool の full cached schema を返します。Cache が stale なら `mcp_manage` で server を refresh します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Cached dynamic MCP tool `<server>:<tool>` を call します。`mcp_tool_search` で discover し、`mcp_tool_inspect` で schema を確認してから使います。External MCP connections は call の期間だけ開きます。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Local/remote の persistent high-level browser sessions を start、list、close、cleanup します。`start` は URL open、persistent `profile_id` reuse、`storage_state_path` load が可能で、`close` は storage state を save できます。

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
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `browser_snapshot`

Persistent browser page の title、URL、bounded visible text、`e1` など stable short refs 付き interactive elements、recent page/network errors、optional screenshot path を capture します。Page navigation または新 snapshot まで refs を `browser_act` targets に直接使えます。

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
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `browser_act`

Persistent browser session で structured actions を実行します。navigate、new_page、close_page、click、fill、type、select、press、check、uncheck、hover、wait、wait_for_text、wait_for_url を support。Target は `browser_snapshot` の `e1` など ref または CSS selector。High-level actions が不足する場合だけ `browser_run_script` を使います。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

### `browser_run_script`

Local または remote machine で full Python Playwright script を実行します。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。

## デスクトップ GUI 自動化

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

action=invite、list、revoke、rename で remote workers を管理します。invite は name/workdir/ttl_s、revoke は machine、rename は machine と new_name が必要です。

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | この tool call に属する Logical Session です。task を処理している間は session_manage が返した session_id を渡します。active な Logical Session がない場合だけ null を使います。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` を指定した場合、この call は追加で `remote:use` を必要とし、remote worker protocol 経由で実行されます。
