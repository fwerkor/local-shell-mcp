<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Riferimento strumenti

Questa pagina è costruita dagli effettivi schema MCP. Esegui `python scripts/generate-tools-reference.py` dopo modifiche alla superficie pubblica degli strumenti per aggiornare il riferimento English.

La maggior parte degli strumenti restituisce un `ToolResult` strutturato con `ok`, `message` e `data`. `workspace_open` restituisce lo stato visibile al modello usato per renderizzare la MCP App. La maggior parte degli strumenti di esecuzione e file accetta un `machine` opzionale: omettilo per il workspace del controller e specificalo per un worker connesso. Le operazioni Git usano deliberatamente `run_shell` o un altro strumento shell invece di wrapper Git dedicati.

## Guida alla selezione

| Necessità | Strumenti preferiti |
|---|---|
| Monitorare o collaborare con l’esecuzione in ChatGPT | `workspace_open` |
| Ispezionare un ambiente | `environment_get`, `file_tree`, `file_read` |
| Eseguire un command breve o operazione Git | `run_shell` |
| Eseguire task interattivo o lungo | `shell_start` or `job_start` |
| Modificare file con precisione | `file_edit` or `file_patch` |
| Trasferire file o directory | `remote_transfer` |
| Scoprire capability MCP esterna | `mcp_tool_search`, then `mcp_tool_inspect` |
| Interagire con una pagina | `browser_session`, `browser_snapshot`, then `browser_act` |
| Eseguire logica browser personalizzata | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Lavorare su macchina remota | usa lo stesso strumento con `machine`; usa `remote_*` solo per amministrazione worker |

## Workspace interattivo

### `workspace_open`

Apre o riutilizza un Live Workspace che mostra la Logical Session fornita esplicitamente. Passa il session_id attivo restituito da session_manage. Il Workspace non deduce mai l’identità del task dal trasporto MCP; passa esplicitamente null quando non è attiva alcuna Logical Session.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

## Ambiente, Skills e stato task

### `environment_get`

Restituisce versione, workspace, auth, policy e informazioni ambiente localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `skill_list`

Elenca Agent Skills installate senza caricarne le instructions. La superficie MCP rimane fissa; aggiunte/rimozioni di directory Skill appaiono alla chiamata successiva.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Carica Skill installata usando il nome esatto restituito da `skill_list`. Restituisce instructions complete `SKILL.md` e path di file correlati.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Legge un file di testo correlato di una Skill installata.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Scansiona file di testo del workspace locale per secret comuni prima di commit o push.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Gestisce una sola Logical Session persistente. start crea un nuovo task e ne restituisce il session_id. resume continua solo il session_id esplicito fornito dall’utente o già presente in questa conversazione. Tutte le azioni tranne start richiedono session_id. Azioni: start, resume, get, report, finish, cancel, delete. report accetta summary/findings/next/blockers/objective/label; delete richiede una Session terminale.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
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

Gestisce il Goal mode opzionale della Logical Session esplicita. Un plan attivo abilita la continuazione automatica dopo 15 minuti senza attività dell’agent, fino a 10 tentativi. session_id deve essere lo stesso id persistente restituito da session_manage. Azioni: start, get, update, block, resume, finish, cancel. start richiede objective e steps; finish richiede che tutti gli steps siano completed o skipped.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
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

Legge entry recenti dell’audit log locale.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shell e job

### `run_shell`

Esegue un command shell non interattivo localmente o su macchina remota. Usalo per build, test, package-manager, Git e inspection che devono terminare rapidamente. Per processi lunghi, interattivi o streaming usa `shell_start` o `job_start`. Campi opzionali purpose/explanation permettono di indicare perché viene eseguito il command.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `run_python`

Scrive ed esegue un breve script Python localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `shell_start`

Avvia shell interattiva persistente localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `shell_send`

Invia input a sessione shell persistente locale o remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `shell_read`

Legge output recente da sessione shell persistente locale o remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `shell_stop`

Termina sessione shell persistente locale o remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `shell_list`

Elenca sessioni shell persistenti localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `job_start`

Avvia job lungo tracciato localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `job_list`

Elenca job tracciati localmente o su macchina remota. I job attivi vengono restituiti per primi; `limit` è limitato all’intervallo 1-1000.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `job_tail`

Legge output recente di job locale o remoto tracciato.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `job_stop`

Ferma job locale o remoto tracciato.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `job_retry`

Riavvia job locale o remoto tracciato fermo o terminato.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

## File e trasferimenti

### `file_list`

Elenca file e directory localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_tree`

Restituisce albero directory compatto localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_glob`

Trova path per glob localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_grep`

Cerca contenuto dei file localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_read`

Legge un file o lista di file localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `image_view`

Visualizza PNG, JPEG, GIF o WebP come contenuto immagine MCP nativo localmente o su macchina remota. Usalo invece di `file_read` quando serve ispezione visiva. Le immagini remote riusano il protocollo di trasferimento esistente, quindi il worker non necessita RPC specifico immagini.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_write`

Scrive file di testo UTF-8 localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_edit`

Applica uno o più edit di testo esatti a un file locale o remoto. Ogni edit contiene old, new e `replace_all` opzionale; old deve corrispondere esattamente, inclusi whitespace e indentation.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_delete`

Elimina file o directory locale/remoto. `recursive=false` elimina file o directory vuote; per directory non vuote serve `recursive=true` e va usato con cautela.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `file_patch`

Controlla e applica unified diff o envelope file_patch localmente o remotamente.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `remote_transfer`

Avvia un job tracciato che copia un file o directory tra il controller e macchine remote. Gli upload remoti usano chunk raw-binary riprendibili; gestisci il transfer con `job_list`, `job_tail`, `job_stop` e `job_retry`.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Deve essere fornito almeno uno tra `source_machine` e `destination_machine`. Gli endpoint omessi indicano il workspace del controller; la sorgente può essere un file o directory.

### `link_create`

Crea URL temporaneo accessibile da browser per file locale. Di default la risposta scarica come attachment; imposta `inline=true` per render diretto in browser o immagine Markdown. I link sono bearer URL pubblici protetti da token ad alta entropia, TTL, limite opzionale download e revoca esplicita.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Elenca URL download file locali generate.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Revoca URL download file locale generata.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Gateway MCP dinamico

### `mcp_manage`

Registra, elenca, ottiene, abilita, disabilita, refresh, rimuove o aggiorna environment/headers isolati di server MCP dinamici. Usa transport `stdio` con command/args/cwd o `streamable_http` con url. Valori secret env/header persistono privatamente e non vengono mai restituiti.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
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
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Cerca summary leggere cacheate degli strumenti da server MCP dinamici abilitati. Gli strumenti dinamici restano fuori da `tools/list` di questo server; usa il nome `<server>:<tool>` restituito con `mcp_tool_inspect` prima di chiamarlo.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Restituisce schema completo cacheato di strumento MCP dinamico chiamato `<server>:<tool>`. Fai refresh del server con `mcp_manage` se la cache è stale.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Chiama strumento MCP dinamico cacheato `<server>:<tool>`. Scoprilo con `mcp_tool_search` e ispeziona schema con `mcp_tool_inspect` prima. Le connessioni MCP esterne restano aperte solo durante la chiamata.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Avvia, elenca, chiude o pulisce sessioni browser persistenti high-level localmente o remotamente. `start` può aprire URL, riusare `profile_id` persistente o caricare `storage_state_path`; `close` può salvare storage state.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
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
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `browser_snapshot`

Cattura pagina browser persistente: title, URL, testo visibile limitato, elementi interattivi con ref brevi stabili come `e1`, errori recenti page/network e path screenshot opzionale. Usa direttamente le ref come target `browser_act` fino a navigazione o nuovo snapshot.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `browser_act`

Esegue azioni strutturate in sessione browser persistente. Supporta navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text, wait_for_url. `target` può essere ref `browser_snapshot` come `e1` o selector CSS. Usa `browser_run_script` solo se le azioni high-level non bastano.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

### `browser_run_script`

Esegue script Python Playwright completo localmente o su macchina remota.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.

## Automazione GUI desktop

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

## Amministrazione remote worker

### `remote_manage`

Gestisce remote worker con action=invite, list, revoke o rename. invite accetta name/workdir/ttl_s; revoke richiede machine; rename richiede machine e new_name.

| Parametro | Tipo | Obbligatorio/default | Descrizione |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session per questa chiamata tool. Durante il lavoro sul task, passa il session_id restituito da session_manage. Usa null solo quando non è attiva alcuna Logical Session. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando viene fornito `machine`, la chiamata richiede anche `remote:use` e viene eseguita tramite il protocollo remote worker.
