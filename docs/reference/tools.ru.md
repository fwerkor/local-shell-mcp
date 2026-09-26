<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Справочник tools

Эта страница строится из фактических MCP tool schemas. После изменения public tool surface запустите `python scripts/generate-tools-reference.py`, чтобы обновить English reference.

Большинство инструментов возвращает структурированный `ToolResult` с `ok`, `message` и `data`. `workspace_open` возвращает видимое модели состояние для рендеринга MCP App. Большинство инструментов выполнения и файлов принимает необязательный `machine`: без него используется workspace controller, с ним — подключённый worker. Git-операции намеренно выполняются через `run_shell` или другой shell-инструмент, а не через отдельные Git wrappers.

## Руководство по выбору

| Задача | Рекомендуемые tools |
|---|---|
| Наблюдать за выполнением или совместно работать в ChatGPT | `workspace_open` |
| Исследовать environment | `environment_get`, `file_tree`, `file_read` |
| Запустить короткую command или Git operation | `run_shell` |
| Запустить interactive или long task | `shell_start` or `job_start` |
| Точно изменить files | `file_edit` or `file_patch` |
| Передать file или directory | `remote_transfer` |
| Обнаружить external MCP capability | `mcp_tool_search`, then `mcp_tool_inspect` |
| Взаимодействовать с page | `browser_session`, `browser_snapshot`, then `browser_act` |
| Запустить custom browser logic | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Работать на remote machine | используйте тот же tool с `machine`; `remote_*` только для worker administration |

## Interactive workspace

### `workspace_open`

Открывает или повторно использует Live Workspace, отображающий явно указанную Logical Session. Передайте активный session_id, возвращённый session_manage. Workspace никогда не выводит идентичность задачи из MCP transport; явно передайте null, если активной Logical Session нет.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

## Environment, Skills и task state

### `environment_get`

Возвращает version, workspace, auth, policy и environment information локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `skill_list`

Перечисляет installed Agent Skills без загрузки instructions. MCP tool surface остаётся фиксированным; добавление/удаление Skill directories отражается при следующем call.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Загружает installed Skill по exact name из `skill_list`. Возвращает полные `SKILL.md` instructions и related file paths.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Читает один related text file установленного Skill.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Сканирует local workspace text files на common secrets перед commit или push.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Управляет одной долговечной Logical Session. start создаёт новую задачу и возвращает её session_id. resume продолжает только явный session_id, переданный пользователем или уже присутствующий в этом разговоре. Все действия, кроме start, требуют session_id. Действия: start, resume, get, report, finish, cancel, delete. report принимает summary/findings/next/blockers/objective/label; delete требует terminal Session.

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

Управляет необязательным Goal mode для явно заданной Logical Session. Активный plan включает автоматическое продолжение после 15 минут без активности agent, максимум 10 попыток. session_id должен быть тем же долговечным id, который вернул session_manage. Действия: start, get, update, block, resume, finish, cancel. start требует objective и steps; finish требует, чтобы все steps были completed или skipped.

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

Читает recent local audit log entries.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells и jobs

### `run_shell`

Запускает одну non-interactive shell command локально или на remote machine. Используйте для build, test, package-manager, Git и inspection commands, которые должны быстро завершаться. Для long-running, interactive или streaming process используйте `shell_start` или `job_start`. Optional purpose/explanation fields позволяют указать причину запуска.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `run_python`

Пишет и запускает short Python script локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `shell_start`

Запускает persistent interactive shell локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `shell_send`

Отправляет input в persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `shell_read`

Читает recent output persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `shell_stop`

Завершает persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `shell_list`

Перечисляет persistent shell sessions локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `job_start`

Запускает tracked long-running job локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `job_list`

Перечисляет tracked jobs локально или на remote machine. Активные jobs возвращаются первыми; `limit` ограничивается диапазоном 1-1000.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `job_tail`

Читает recent output tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `job_stop`

Останавливает tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `job_retry`

Повторно запускает stopped/exited tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

## Files и transfer

### `file_list`

Перечисляет files/directories локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_tree`

Возвращает compact directory tree локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_glob`

Находит paths по glob локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_grep`

Ищет содержимое files локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_read`

Читает один file или list files локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `image_view`

Показывает PNG, JPEG, GIF или WebP как native MCP image content локально или на remote machine. Для visual inspection используйте вместо `file_read`. Remote images переиспользуют существующий file-transfer protocol, поэтому worker не нужен image-specific RPC.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_write`

Записывает UTF-8 text file локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_edit`

Применяет один или несколько exact-text edits к local/remote file. Каждый edit содержит old, new и optional `replace_all`; old должен точно совпадать, включая whitespace и indentation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_delete`

Удаляет local/remote file или directory. `recursive=false` удаляет files или empty directories; для non-empty directory нужен `recursive=true`, используйте осторожно.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `file_patch`

Проверяет и применяет unified diff или file_patch envelope локально или remote.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `remote_transfer`

Запускает отслеживаемый job для копирования файла или каталога между controller и remote machines. Remote uploads используют возобновляемые raw-binary chunks; управляйте transfer через `job_list`, `job_tail`, `job_stop` и `job_retry`.

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
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Нужно указать как минимум один из `source_machine` и `destination_machine`. Пропущенный endpoint означает workspace controller; источником может быть файл или каталог.

### `link_create`

Создаёт temporary browser-accessible URL для local file. По умолчанию response скачивается как attachment; установите `inline=true` для direct rendering в browser или Markdown image. Links — public bearer URLs, защищённые high-entropy token, TTL, optional download-count limit и explicit revocation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Перечисляет generated local file download URLs.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Отзывает generated local file download URL.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Регистрирует, перечисляет, получает, включает, отключает, refresh, удаляет или обновляет isolated environment/headers dynamic MCP servers. Для transport `stdio` используются command/args/cwd, для `streamable_http` — url. Secret env/header values persist privately и никогда не возвращаются.

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
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Ищет cached lightweight tool summaries enabled dynamic MCP servers. Dynamic tools не входят в `tools/list` этого server; перед call используйте возвращённое имя `<server>:<tool>` с `mcp_tool_inspect`.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Возвращает full cached schema dynamic MCP tool с именем `<server>:<tool>`. Если cache stale, refresh server через `mcp_manage`.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Вызывает cached dynamic MCP tool `<server>:<tool>`. Сначала discover через `mcp_tool_search`, затем inspect schema через `mcp_tool_inspect`. External MCP connections открываются только на время call.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Запускает, перечисляет, закрывает или очищает persistent high-level browser sessions локально или remote. `start` может открыть URL, reuse persistent `profile_id` или load `storage_state_path`; `close` может save storage state.

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
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `browser_snapshot`

Capture persistent browser page: title, URL, bounded visible text, interactive elements со stable short refs вроде `e1`, recent page/network errors и optional screenshot path. Используйте refs напрямую как `browser_act` targets до navigation или нового snapshot.

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
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `browser_act`

Выполняет structured actions в persistent browser session. Поддерживает navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text и wait_for_url. `target` может быть ref `browser_snapshot` вроде `e1` или CSS selector. Используйте `browser_run_script` только если high-level actions недостаточно.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

### `browser_run_script`

Запускает full Python Playwright script локально или на remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.

## Автоматизация GUI рабочего стола

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

Управляет remote workers через action=invite, list, revoke или rename. invite принимает name/workdir/ttl_s; revoke требует machine; rename требует machine и new_name.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session для этого вызова инструмента. Во время работы над задачей передавайте session_id, возвращённый session_manage. Используйте null только когда активной Logical Session нет. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Если указан `machine`, вызов дополнительно требует `remote:use` и выполняется через протокол remote worker.
