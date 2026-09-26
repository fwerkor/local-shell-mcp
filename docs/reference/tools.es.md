<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Referencia de herramientas

Esta página se construye a partir de los schemas reales de las tools MCP. Ejecute `python scripts/generate-tools-reference.py` después de cambiar la superficie pública de tools para actualizar la referencia English.

La mayoría de las herramientas devuelve un `ToolResult` estructurado con `ok`, `message` y `data`. `workspace_open` devuelve el estado visible al modelo usado para renderizar la MCP App. La mayoría de herramientas de ejecución y archivos acepta un `machine` opcional: omítalo para el workspace del controller y especifíquelo para un worker conectado. Las operaciones Git usan deliberadamente `run_shell` u otra herramienta shell en vez de wrappers Git dedicados.

## Guía de selección

| Necesidad | Tools preferidas |
|---|---|
| Monitorizar o colaborar con la ejecución en ChatGPT | `workspace_open` |
| Inspeccionar un entorno | `environment_get`, `file_tree`, `file_read` |
| Ejecutar un comando corto u operación Git | `run_shell` |
| Ejecutar una tarea interactiva o larga | `shell_start` or `job_start` |
| Hacer cambios exactos en archivos | `file_edit` or `file_patch` |
| Transferir un archivo o directorio | `remote_transfer` |
| Descubrir una capability MCP externa | `mcp_tool_search`, then `mcp_tool_inspect` |
| Interactuar con una página | `browser_session`, `browser_snapshot`, then `browser_act` |
| Ejecutar lógica browser personalizada | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Trabajar en una máquina remota | use la misma tool con `machine`; use `remote_*` solo para administración de workers |

## Workspace interactivo

### `workspace_open`

Abre o reutiliza un Live Workspace que muestra la Logical Session indicada explícitamente. Pasa el session_id activo devuelto por session_manage. El Workspace nunca infiere la identidad de la tarea a partir del transporte MCP; pasa null de forma explícita cuando no haya una Logical Session activa.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

## Entorno, Skills y estado de tareas

### `environment_get`

Devuelve versión, workspace, auth, policy e información de entorno localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `skill_list`

Lista Agent Skills instaladas sin cargar sus instructions. La superficie MCP de tools permanece fija; añadir o eliminar directorios Skill se refleja en la siguiente llamada.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Carga una Skill instalada por el nombre exacto devuelto por `skill_list`. Devuelve las instructions completas de `SKILL.md` y paths de archivos relacionados.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Lee un archivo de texto relacionado de una Skill instalada.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Escanea archivos de texto del workspace local en busca de secrets comunes antes de commit o push.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Gestiona una única Logical Session persistente. start crea una tarea nueva y devuelve su session_id. resume continúa únicamente el session_id explícito proporcionado por el usuario o ya presente en esta conversación. Todas las acciones salvo start requieren session_id. Acciones: start, resume, get, report, finish, cancel, delete. report acepta summary/findings/next/blockers/objective/label; delete requiere una Session terminal.

| Parámetro | Tipo | Requerido/default | Descripción |
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

Gestiona el Goal mode opcional de la Logical Session explícita. Un plan activo habilita la continuación automática tras 15 minutos sin actividad del agente, con un máximo de 10 intentos. session_id debe ser el mismo identificador persistente devuelto por session_manage. Acciones: start, get, update, block, resume, finish, cancel. start requiere objective y steps; finish exige que todos los steps estén completed o skipped.

| Parámetro | Tipo | Requerido/default | Descripción |
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

Lee entradas recientes del audit log local.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells y jobs

### `run_shell`

Ejecuta un comando shell no interactivo localmente o en una máquina remota. Úselo para build, test, package-manager, Git e inspección que deban terminar pronto. Para procesos largos, interactivos o streaming, use `shell_start` o `job_start`. Los campos opcionales purpose/explanation permiten indicar por qué se ejecuta el comando.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `run_python`

Escribe y ejecuta un script Python corto localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `shell_start`

Inicia una shell interactiva persistente localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `shell_send`

Envía input a una sesión shell persistente local o remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `shell_read`

Lee output reciente de una sesión shell persistente local o remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `shell_stop`

Termina una sesión shell persistente local o remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `shell_list`

Lista sesiones shell persistentes localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `job_start`

Inicia un job largo y trackeado localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `job_list`

Lista jobs trackeados localmente o en una máquina remota. Los jobs activos se devuelven primero; `limit` se limita al rango 1-1000.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `job_tail`

Lee output reciente de un job local o remoto trackeado.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `job_stop`

Detiene un job local o remoto trackeado.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `job_retry`

Reinicia un job local o remoto trackeado que se detuvo o salió.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

## Archivos y transferencias

### `file_list`

Lista archivos y directorios localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_tree`

Devuelve un árbol de directorios compacto localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_glob`

Encuentra paths por glob localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_grep`

Busca contenido de archivos localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_read`

Lee un archivo o lista de archivos localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `image_view`

Muestra un archivo PNG, JPEG, GIF o WebP como contenido de imagen MCP nativo localmente o en una máquina remota. Úselo en vez de `file_read` cuando se necesite inspección visual. Las imágenes remotas reutilizan el protocolo de transferencia existente, por lo que el worker no necesita un RPC específico de imágenes.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_write`

Escribe un archivo de texto UTF-8 localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_edit`

Aplica uno o más edits de texto exactos a un archivo local o remoto. Cada edit contiene old, new y `replace_all` opcional; old debe coincidir exactamente, incluyendo whitespace e indentation.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_delete`

Elimina un archivo o directorio local o remoto. `recursive=false` elimina archivos o directorios vacíos; para directorios no vacíos se requiere `recursive=true` y debe usarse con cuidado.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `file_patch`

Comprueba y aplica un unified diff o envelope de file_patch local o remotamente.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `remote_transfer`

Inicia un job trackeado que copia un archivo o directorio entre el controller y máquinas remotas. Los uploads remotos usan chunks raw-binary reanudables; gestione la transferencia con `job_list`, `job_tail`, `job_stop` y `job_retry`.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Debe proporcionarse al menos uno de `source_machine` y `destination_machine`. Los endpoints omitidos se refieren al workspace del controller; el origen puede ser un archivo o directorio.

### `link_create`

Crea una URL temporal accesible por browser para un archivo local. Por defecto la respuesta fuerza descarga como attachment; establezca `inline=true` para render directo en browser o imagen Markdown. Los links son URLs bearer públicas protegidas por token de alta entropía, TTL, límite opcional de descargas y revocación explícita.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Lista URLs de descarga de archivos locales generadas.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Revoca una URL de descarga de archivo local generada.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Gateway MCP dinámico

### `mcp_manage`

Registra, lista, obtiene, habilita, deshabilita, refresca, elimina o actualiza environment/headers aislados de servidores MCP dinámicos. Use transport `stdio` con command/args/cwd o `streamable_http` con url. Los valores secret de env/header se persisten privadamente y nunca se devuelven.

| Parámetro | Tipo | Requerido/default | Descripción |
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
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Busca summaries ligeros cacheados de tools de servidores MCP dinámicos habilitados. Las tools dinámicas no entran en `tools/list` de este server; use el nombre `<server>:<tool>` devuelto con `mcp_tool_inspect` antes de llamarla.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Devuelve el schema completo cacheado de una tool MCP dinámica llamada `<server>:<tool>`. Refresque el server con `mcp_manage` si su cache está stale.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Llama una tool MCP dinámica cacheada llamada `<server>:<tool>`. Descúbrala con `mcp_tool_search` e inspeccione su schema con `mcp_tool_inspect` primero. Las conexiones MCP externas solo se abren durante esta llamada.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Inicia, lista, cierra o limpia sesiones browser persistentes de alto nivel local o remotamente. `start` puede abrir una URL, reutilizar `profile_id` persistente o cargar `storage_state_path`; `close` puede guardar storage state.

| Parámetro | Tipo | Requerido/default | Descripción |
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
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `browser_snapshot`

Captura una página browser persistente: title, URL, texto visible acotado, elementos interactivos con refs cortas estables como `e1`, errores recientes de page/network y path opcional de screenshot. Use las refs directamente como targets de `browser_act` hasta que la página navegue o se tome un nuevo snapshot.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `browser_act`

Ejecuta acciones estructuradas en una sesión browser persistente. Soporta navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text y wait_for_url. `target` puede ser una ref de `browser_snapshot` como `e1` o selector CSS. Use `browser_run_script` solo cuando estas acciones de alto nivel no basten.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

### `browser_run_script`

Ejecuta un script Python Playwright completo localmente o en una máquina remota.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.

## Automatización de GUI de escritorio

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

## Administración de remote workers

### `remote_manage`

Gestiona remote workers con action=invite, list, revoke o rename. invite acepta name/workdir/ttl_s; revoke requiere machine; rename requiere machine y new_name.

| Parámetro | Tipo | Requerido/default | Descripción |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session para esta llamada de herramienta. Mientras trabajes en la tarea, pasa el session_id devuelto por session_manage. Usa null solo cuando no haya una Logical Session activa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Cuando se proporciona `machine`, la llamada también requiere `remote:use` y se ejecuta mediante el protocolo de remote worker.
