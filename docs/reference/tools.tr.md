<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Tools referansı

Bu page gerçek MCP tool schemas üzerinden oluşturulur. Public tool surface değiştiğinde English reference güncellemek için `python scripts/generate-tools-reference.py` çalıştırın.

Çoğu araç `ok`, `message` ve `data` içeren yapılandırılmış bir `ToolResult` döndürür. `workspace_open`, MCP App’i render etmek için model-visible state döndürür. Çoğu execution/file aracı optional `machine` kabul eder; controller workspace için boş bırakın, bağlı worker için belirtin. Git işlemleri özel Git wrapper’ları yerine bilerek `run_shell` veya başka bir shell aracı kullanır.

## Seçim rehberi

| İhtiyaç | Önerilen tools |
|---|---|
| ChatGPT içinde execution izlemek veya collaborate etmek | `workspace_open` |
| Environment inspect etmek | `environment_get`, `file_tree`, `file_read` |
| Short command veya Git operation çalıştırmak | `run_shell` |
| Interactive veya long task çalıştırmak | `shell_start` or `job_start` |
| File üzerinde exact changes yapmak | `file_edit` or `file_patch` |
| File veya directory transfer etmek | `remote_transfer` |
| External MCP capability discover etmek | `mcp_tool_search`, then `mcp_tool_inspect` |
| Page ile interact etmek | `browser_session`, `browser_snapshot`, then `browser_act` |
| Custom browser logic çalıştırmak | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Remote machine üzerinde çalışmak | aynı tool ile `machine` kullanın; yalnız worker administration için `remote_*` |

## Interactive workspace

### `workspace_open`

Açıkça verilen Logical Sessionı gösteren bir Live Workspace açar veya yeniden kullanır. session_manage tarafından döndürülen etkin session_id değerini iletin. Workspace görev kimliğini MCP transport üzerinden asla çıkarsamaz; etkin Logical Session yoksa null değerini açıkça iletin.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

## Environment, Skills ve task state

### `environment_get`

Local veya remote machine için version, workspace, auth, policy ve environment information döndürür.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `skill_list`

Instructions yüklemeden installed Agent Skills listeler. MCP tool surface sabit kalır; Skill directories ekleme/silme bir sonraki call’da görünür.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

`skill_list` tarafından döndürülen exact name ile installed Skill yükler. Full `SKILL.md` instructions ve related file paths döndürür.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Installed Skill’e ait bir related text file okur.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Commit veya push öncesi local workspace text files içinde common secrets scan eder.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Tek bir kalıcı Logical Sessionı yönetir. start yeni bir görev oluşturur ve session_id değerini döndürür. resume yalnızca kullanıcının açıkça verdiği veya bu konuşmada zaten bulunan session_id değerini sürdürür. start dışındaki tüm actionlar session_id gerektirir. Actionlar: start, resume, get, report, finish, cancel, delete. report summary/findings/next/blockers/objective/label kabul eder; delete terminal bir Session gerektirir.

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

Açık Logical Sessionın isteğe bağlı Goal modeunu yönetir. Etkin plan, agent etkinliği olmadan 15 dakika geçince otomatik continuationı etkinleştirir ve en fazla 10 denemeyle sınırlar. session_id, session_manage tarafından döndürülen aynı kalıcı id olmalıdır. Actionlar: start, get, update, block, resume, finish, cancel. start objective ve steps gerektirir; finish tüm steps değerlerinin completed veya skipped olmasını gerektirir.

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

Recent local audit log entries okur.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells ve jobs

### `run_shell`

Local veya remote machine üzerinde bir non-interactive shell command çalıştırır. Hızlı bitmesi gereken build, test, package-manager, Git ve inspection commands için kullanın. Long-running, interactive veya streaming process için `shell_start` ya da `job_start` kullanın. Optional purpose/explanation fields command’in neden çalıştırıldığını belirtebilir.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `run_python`

Local veya remote machine üzerinde short Python script yazar ve çalıştırır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `shell_start`

Local veya remote machine üzerinde persistent interactive shell başlatır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `shell_send`

Persistent local/remote shell session’a input gönderir.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `shell_read`

Persistent local/remote shell session recent output okur.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `shell_stop`

Persistent local/remote shell session sonlandırır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `shell_list`

Local veya remote machine üzerinde persistent shell sessions listeler.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `job_start`

Local veya remote machine üzerinde tracked long-running job başlatır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `job_list`

Local veya remote machine üzerinde tracked jobs listeler. Active joblar önce döndürülür; `limit` 1-1000 aralığıyla sınırlandırılır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `job_tail`

Tracked local/remote job recent output okur.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `job_stop`

Tracked local/remote job durdurur.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `job_retry`

Stopped/exited tracked local/remote job yeniden başlatır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

## Files ve transfer

### `file_list`

Local veya remote machine üzerinde files/directories listeler.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_tree`

Local veya remote machine üzerinde compact directory tree döndürür.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_glob`

Local veya remote machine üzerinde glob ile paths bulur.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_grep`

Local veya remote machine üzerinde file contents arar.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_read`

Local veya remote machine üzerinde bir file veya list files okur.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `image_view`

PNG, JPEG, GIF veya WebP file’ı local veya remote machine üzerinde native MCP image content olarak gösterir. Visual inspection gerektiğinde `file_read` yerine kullanın. Remote images mevcut file-transfer protocol’u reuse eder; worker için image-specific RPC gerekmez.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_write`

Local veya remote machine üzerinde UTF-8 text file yazar.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_edit`

Bir local/remote file üzerinde bir veya daha fazla exact-text edits uygular. Her edit old, new ve optional `replace_all` içerir; old whitespace ve indentation dahil exact match olmalıdır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_delete`

Local/remote file veya directory siler. `recursive=false` files veya empty directories siler; non-empty directories için `recursive=true` gerekir ve dikkatli kullanılmalıdır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `file_patch`

Local veya remote unified diff veya file_patch envelope kontrol eder ve uygular.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `remote_transfer`

Controller ile remote machine’ler arasında file veya directory kopyalayan tracked job başlatır. Remote upload resumable raw-binary chunk kullanır; transfer’ı `job_list`, `job_tail`, `job_stop` ve `job_retry` ile yönetin.

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
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`source_machine` ve `destination_machine` değerlerinden en az biri verilmelidir. Atlanan endpoint controller workspace’i ifade eder; source file veya directory olabilir.

### `link_create`

Local file için temporary browser-accessible URL oluşturur. Default response attachment download’dur; browser veya Markdown image içinde direct render için `inline=true` yapın. Links high-entropy token, TTL, optional download-count limit ve explicit revocation ile korunan public bearer URLs’dir.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Generated local file download URLs listeler.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Generated local file download URL revoke eder.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Dynamic MCP servers için isolated environment/headers register, list, get, enable, disable, refresh, remove veya update eder. Transport `stdio` ile command/args/cwd, `streamable_http` ile url kullanın. Secret env/header values private olarak persist edilir ve asla döndürülmez.

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
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Enabled dynamic MCP servers üzerinden cached lightweight tool summaries arar. Dynamic tools bu server’ın `tools/list` listesinde yer almaz; call öncesi returned `<server>:<tool>` name ile `mcp_tool_inspect` kullanın.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

`<server>:<tool>` adlı dynamic MCP tool için full cached schema döndürür. Cache stale ise `mcp_manage` ile server refresh edin.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

`<server>:<tool>` adlı cached dynamic MCP tool call eder. Önce `mcp_tool_search` ile discover, sonra `mcp_tool_inspect` ile schema inspect edin. External MCP connections yalnız call süresince açıktır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Local veya remote persistent high-level browser sessions start, list, close veya cleanup eder. `start` URL open edebilir, persistent `profile_id` reuse edebilir veya `storage_state_path` load edebilir; `close` storage state save edebilir.

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
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `browser_snapshot`

Persistent browser page capture eder: title, URL, bounded visible text, `e1` gibi stable short refs içeren interactive elements, recent page/network errors ve optional screenshot path. Page navigate olana veya yeni snapshot alınana kadar refs’i doğrudan `browser_act` targets olarak kullanın.

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
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `browser_act`

Persistent browser session içinde structured actions çalıştırır. navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text ve wait_for_url destekler. `target`, `browser_snapshot` ref’i `e1` veya CSS selector olabilir. High-level actions yeterli değilse `browser_run_script` kullanın.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

### `browser_run_script`

Local veya remote machine üzerinde full Python Playwright script çalıştırır.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.

## Masaüstü GUI otomasyonu

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

action=invite, list, revoke veya rename ile remote workers yönetir. invite name/workdir/ttl_s kabul eder; revoke machine gerektirir; rename machine ve new_name gerektirir.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Bu tool çağrısının Logical Sessionı. Görev üzerinde çalışırken session_manage tarafından döndürülen session_id değerini iletin. null yalnızca etkin Logical Session yokken kullanılmalıdır. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` sağlandığında çağrı ayrıca `remote:use` gerektirir ve remote worker protocol üzerinden çalışır.
