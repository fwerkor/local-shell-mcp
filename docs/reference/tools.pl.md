<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Referencja tools

Ta page jest budowana z rzeczywistych MCP tool schemas. Po zmianie public tool surface uruchom `python scripts/generate-tools-reference.py`, aby zaktualizować English reference.

Większość narzędzi zwraca ustrukturyzowany `ToolResult` zawierający `ok`, `message` i `data`. `workspace_open` zwraca stan widoczny dla modelu używany do renderowania MCP App. Większość narzędzi wykonawczych i plikowych przyjmuje opcjonalny `machine`; pomiń go dla workspace controller albo podaj dla podłączonego workera. Operacje Git celowo używają `run_shell` lub innego narzędzia shell zamiast dedykowanych wrapperów Git.

## Przewodnik wyboru

| Potrzeba | Preferowane tools |
|---|---|
| Monitorować lub współpracować z execution w ChatGPT | `workspace_open` |
| Inspect environment | `environment_get`, `file_tree`, `file_read` |
| Uruchomić short command lub Git operation | `run_shell` |
| Uruchomić interactive lub long task | `shell_start` or `job_start` |
| Dokładnie zmienić file | `file_edit` or `file_patch` |
| Transfer file lub directory | `remote_transfer` |
| Discover external MCP capability | `mcp_tool_search`, then `mcp_tool_inspect` |
| Interact z page | `browser_session`, `browser_snapshot`, then `browser_act` |
| Uruchomić custom browser logic | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Pracować na remote machine | użyj tego samego tool z `machine`; `remote_*` tylko do worker administration |

## Interactive workspace

### `workspace_open`

Otwiera lub ponownie wykorzystuje Live Workspace wyświetlający jawnie wskazaną Logical Session. Przekaż aktywny session_id zwrócony przez session_manage. Workspace nigdy nie wywnioskuje tożsamości zadania z transportu MCP; gdy nie ma aktywnej Logical Session, jawnie przekaż null.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

## Environment, Skills i task state

### `environment_get`

Zwraca version, workspace, auth, policy i environment information lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `skill_list`

Listuje installed Agent Skills bez ładowania instructions. MCP tool surface pozostaje stała; dodanie/usunięcie Skill directories widać przy następnym call.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Ładuje installed Skill po exact name zwróconej przez `skill_list`. Zwraca pełne `SKILL.md` instructions i related file paths.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Czyta jeden related text file installed Skill.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Skanuje local workspace text files pod kątem common secrets przed commit lub push.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Zarządza jedną trwałą Logical Session. start tworzy nowe zadanie i zwraca jego session_id. resume kontynuuje wyłącznie jawny session_id podany przez użytkownika lub już obecny w tej rozmowie. Wszystkie akcje poza start wymagają session_id. Akcje: start, resume, get, report, finish, cancel, delete. report przyjmuje summary/findings/next/blockers/objective/label; delete wymaga terminalnej Session.

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

Zarządza opcjonalnym Goal mode dla jawnej Logical Session. Aktywny plan włącza automatyczną kontynuację po 15 minutach bez aktywności agenta, maksymalnie 10 prób. session_id musi być tym samym trwałym identyfikatorem zwróconym przez session_manage. Akcje: start, get, update, block, resume, finish, cancel. start wymaga objective i steps; finish wymaga, aby wszystkie steps były completed lub skipped.

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

Czyta recent local audit log entries.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells i jobs

### `run_shell`

Uruchamia jedną non-interactive shell command lokalnie lub na remote machine. Używaj do build, test, package-manager, Git i inspection commands, które powinny szybko się zakończyć. Dla long-running, interactive lub streaming process użyj `shell_start` lub `job_start`. Optional purpose/explanation fields mogą podać powód wykonania command.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `run_python`

Pisze i uruchamia short Python script lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `shell_start`

Uruchamia persistent interactive shell lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `shell_send`

Wysyła input do persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `shell_read`

Czyta recent output persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `shell_stop`

Kończy persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `shell_list`

Listuje persistent shell sessions lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `job_start`

Uruchamia tracked long-running job lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `job_list`

Listuje tracked jobs lokalnie lub na remote machine. Aktywne joby są zwracane jako pierwsze; `limit` jest ograniczany do zakresu 1-1000.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `job_tail`

Czyta recent output tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `job_stop`

Zatrzymuje tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `job_retry`

Ponownie uruchamia stopped/exited tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

## Files i transfer

### `file_list`

Listuje files i directories lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_tree`

Zwraca compact directory tree lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_glob`

Znajduje paths przez glob lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_grep`

Przeszukuje file contents lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_read`

Czyta jeden file lub list files lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `image_view`

Wyświetla PNG, JPEG, GIF lub WebP jako native MCP image content lokalnie lub na remote machine. Przy visual inspection używaj zamiast `file_read`. Remote images reuse istniejący file-transfer protocol, więc worker nie potrzebuje image-specific RPC.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_write`

Zapisuje UTF-8 text file lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_edit`

Stosuje jeden lub więcej exact-text edits do local/remote file. Każdy edit ma old, new i optional `replace_all`; old musi exact match łącznie z whitespace i indentation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_delete`

Usuwa local/remote file lub directory. `recursive=false` usuwa files lub empty directories; non-empty directories wymagają `recursive=true`, którego należy używać ostrożnie.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `file_patch`

Sprawdza i stosuje unified diff lub file_patch envelope lokalnie lub remote.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `remote_transfer`

Uruchamia śledzony job kopiujący plik lub katalog między controllerem a remote machines. Remote uploads używają wznawialnych raw-binary chunks; transferem zarządzaj przez `job_list`, `job_tail`, `job_stop` i `job_retry`.

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
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Należy podać co najmniej jedno z `source_machine` i `destination_machine`. Pominięty endpoint oznacza workspace controller; źródłem może być plik lub katalog.

### `link_create`

Tworzy temporary browser-accessible URL dla local file. Default response to attachment download; ustaw `inline=true` dla direct render w browser lub Markdown image. Links są public bearer URLs chronionymi przez high-entropy token, TTL, optional download-count limit i explicit revocation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Listuje generated local file download URLs.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Revoke generated local file download URL.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Register, list, get, enable, disable, refresh, remove lub update isolated environment/headers dynamic MCP servers. Użyj transport `stdio` z command/args/cwd albo `streamable_http` z url. Secret env/header values persist privately i nigdy nie są zwracane.

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
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Wyszukuje cached lightweight tool summaries z enabled dynamic MCP servers. Dynamic tools pozostają poza `tools/list` tego server; przed call użyj returned `<server>:<tool>` name z `mcp_tool_inspect`.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Zwraca full cached schema dynamic MCP tool o nazwie `<server>:<tool>`. Jeśli cache stale, refresh server przez `mcp_manage`.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Call cached dynamic MCP tool `<server>:<tool>`. Najpierw discover przez `mcp_tool_search`, potem inspect schema przez `mcp_tool_inspect`. External MCP connections otwierają się tylko na czas call.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Start, list, close lub cleanup persistent high-level browser sessions lokalnie lub remote. `start` może open URL, reuse persistent `profile_id` lub load `storage_state_path`; `close` może save storage state.

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
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `browser_snapshot`

Capture persistent browser page: title, URL, bounded visible text, interactive elements ze stable short refs jak `e1`, recent page/network errors i optional screenshot path. Używaj refs bezpośrednio jako `browser_act` targets do navigation lub nowego snapshot.

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
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `browser_act`

Uruchamia structured actions w persistent browser session. Obsługuje navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text i wait_for_url. `target` może być `browser_snapshot` ref jak `e1` lub CSS selector. Użyj `browser_run_script` tylko gdy high-level actions nie wystarczą.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

### `browser_run_script`

Uruchamia full Python Playwright script lokalnie lub na remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.

## Automatyzacja GUI pulpitu

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

Zarządza remote workers przez action=invite, list, revoke lub rename. invite przyjmuje name/workdir/ttl_s; revoke wymaga machine; rename wymaga machine i new_name.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session dla tego wywołania narzędzia. Podczas pracy nad zadaniem przekazuj session_id zwrócony przez session_manage. Używaj null tylko wtedy, gdy nie ma aktywnej Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Gdy podano `machine`, wywołanie wymaga również `remote:use` i działa przez protokół remote worker.
