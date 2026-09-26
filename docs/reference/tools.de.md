<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Tool-Referenz

Diese Seite wird aus den tatsächlichen MCP-Tool-Schemas aufgebaut. Führen Sie nach Änderungen an der öffentlichen Tool-Oberfläche `python scripts/generate-tools-reference.py` aus, um die English-Referenz zu aktualisieren.

Die meisten Tools liefern ein strukturiertes `ToolResult` mit `ok`, `message` und `data`. `workspace_open` liefert den model-visible State zum Rendern der MCP App. Die meisten Ausführungs- und Datei-Tools akzeptieren ein optionales `machine`; ohne Wert wird der Controller-Workspace verwendet, mit Wert ein verbundener Worker. Git-Operationen nutzen absichtlich `run_shell` oder ein anderes Shell-Tool statt eigener Git-Wrapper.

## Auswahlhilfe

| Bedarf | Bevorzugte Tools |
|---|---|
| Ausführung in ChatGPT beobachten oder daran mitarbeiten | `workspace_open` |
| Umgebung untersuchen | `environment_get`, `file_tree`, `file_read` |
| Kurzen Befehl oder Git-Operation ausführen | `run_shell` |
| Interaktive oder lange Aufgabe ausführen | `shell_start` or `job_start` |
| Dateien exakt ändern | `file_edit` or `file_patch` |
| Datei oder Verzeichnis übertragen | `remote_transfer` |
| Externe MCP-Capability entdecken | `mcp_tool_search`, then `mcp_tool_inspect` |
| Mit einer Seite interagieren | `browser_session`, `browser_snapshot`, then `browser_act` |
| Eigene Browser-Logik ausführen | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Auf einer Remote-Maschine arbeiten | dasselbe Tool mit `machine` verwenden; `remote_*` nur zur Worker-Administration |

## Interaktiver Workspace

### `workspace_open`

Öffnet oder verwendet einen Live Workspace wieder, der die explizit angegebene Logical Session anzeigt. Übergeben Sie die aktive session_id aus session_manage. Der Workspace leitet die Task-Identität nie aus dem MCP-Transport ab; übergeben Sie explizit null, wenn keine Logical Session aktiv ist.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

## Umgebung, Skills und Task-State

### `environment_get`

Gibt Version, Workspace, Auth, Policy und Umgebungsinformationen lokal oder auf einer Remote-Maschine zurück.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `skill_list`

Listet installierte Agent Skills, ohne deren Instructions zu laden. Die MCP-Tool-Oberfläche bleibt fest; hinzugefügte oder entfernte Skill-Verzeichnisse erscheinen beim nächsten Aufruf.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Lädt einen installierten Skill über den exakten von `skill_list` gelieferten Namen. Gibt vollständige `SKILL.md`-Instructions und Pfade zu Related Files zurück.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Liest eine zu einem installierten Skill gehörende Textdatei.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Scannt lokale Workspace-Textdateien vor Commit oder Push nach gängigen Secrets.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Verwaltet genau eine dauerhafte Logical Session. start erstellt eine neue Task und gibt deren session_id zurück. resume setzt nur die explizite session_id fort, die der Benutzer angegeben hat oder die bereits in dieser Unterhaltung vorhanden ist. Alle Aktionen außer start benötigen session_id. Aktionen: start, resume, get, report, finish, cancel, delete. report akzeptiert summary/findings/next/blockers/objective/label; delete erfordert eine terminale Session.

| Parameter | Typ | Erforderlich/default | Beschreibung |
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

Verwaltet den optionalen Goal-Modus für die explizite Logical Session. Ein aktiver Plan aktiviert nach 15 Minuten ohne Agent-Aktivität die automatische Fortsetzung, begrenzt auf 10 Versuche. session_id muss dieselbe dauerhafte ID sein, die session_manage zurückgegeben hat. Aktionen: start, get, update, block, resume, finish, cancel. start erfordert objective und steps; finish verlangt, dass alle steps completed oder skipped sind.

| Parameter | Typ | Erforderlich/default | Beschreibung |
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

Liest aktuelle Einträge des lokalen Audit Logs.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells und Jobs

### `run_shell`

Führt einen nicht-interaktiven Shell-Befehl lokal oder auf einer Remote-Maschine aus. Für Build-, Test-, Package-Manager-, Git- und Inspektionsbefehle, die zeitnah enden sollen. Für lang laufende, interaktive oder streamende Prozesse `shell_start` oder `job_start` verwenden. Optionale purpose/explanation-Felder können den Ausführungsgrund angeben.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `run_python`

Schreibt und führt ein kurzes Python-Skript lokal oder auf einer Remote-Maschine aus.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `shell_start`

Startet eine persistente interaktive Shell lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `shell_send`

Sendet Eingabe an eine persistente lokale oder Remote-Shell-Session.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `shell_read`

Liest aktuelle Ausgabe einer persistenten lokalen oder Remote-Shell-Session.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `shell_stop`

Beendet eine persistente lokale oder Remote-Shell-Session.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `shell_list`

Listet persistente Shell-Sessions lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `job_start`

Startet einen getrackten lang laufenden Job lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `job_list`

Listet getrackte Jobs lokal oder auf einer Remote-Maschine. Aktive Jobs werden zuerst zurückgegeben; `limit` wird auf 1-1000 begrenzt.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `job_tail`

Liest aktuelle Ausgabe eines getrackten lokalen oder Remote-Jobs.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `job_stop`

Stoppt einen getrackten lokalen oder Remote-Job.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `job_retry`

Startet einen gestoppten oder beendeten getrackten lokalen oder Remote-Job neu.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

## Dateien und Transfer

### `file_list`

Listet Dateien und Verzeichnisse lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_tree`

Gibt einen kompakten Verzeichnisbaum lokal oder auf einer Remote-Maschine zurück.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_glob`

Findet Pfade per Glob lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_grep`

Durchsucht Dateiinhalte lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_read`

Liest eine Datei oder Liste von Dateien lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `image_view`

Zeigt PNG-, JPEG-, GIF- oder WebP-Dateien als nativen MCP-Bildinhalt lokal oder auf einer Remote-Maschine. Bei visueller Inspektion statt `file_read` verwenden. Remote-Bilder nutzen das bestehende Dateiübertragungsprotokoll, daher braucht der Worker keinen bildspezifischen RPC.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_write`

Schreibt eine UTF-8-Textdatei lokal oder auf einer Remote-Maschine.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_edit`

Wendet einen oder mehrere exakte Text-Edits auf eine lokale oder Remote-Datei an. Jeder Edit enthält old, new und optional `replace_all`; old muss einschließlich Whitespace und Einrückung exakt übereinstimmen.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_delete`

Löscht eine lokale oder Remote-Datei bzw. ein Verzeichnis. `recursive=false` löscht Dateien oder leere Verzeichnisse; für nicht leere Verzeichnisse ist `recursive=true` erforderlich und vorsichtig zu verwenden.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `file_patch`

Prüft und wendet einen Unified Diff oder Apply-Patch-Envelope lokal oder remote an.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `remote_transfer`

Startet einen verfolgten Job, der eine Datei oder ein Verzeichnis zwischen Controller und Remote-Maschinen kopiert. Remote-Uploads verwenden fortsetzbare Raw-Binary-Chunks; verwalten Sie den Transfer mit `job_list`, `job_tail`, `job_stop` und `job_retry`.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Mindestens eines von `source_machine` und `destination_machine` muss angegeben werden. Ausgelassene Endpoints beziehen sich auf den Controller-Workspace; die Quelle kann Datei oder Verzeichnis sein.

### `link_create`

Erstellt eine temporäre browserzugängliche URL für eine lokale Datei. Standardmäßig wird als Attachment heruntergeladen; `inline=true` rendert direkt im Browser oder als Markdown-Bild. Links sind öffentliche Bearer-URLs, geschützt durch High-Entropy-Token, TTL, optionales Download-Count-Limit und expliziten Widerruf.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Listet erzeugte lokale Datei-Download-URLs.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Widerruft eine erzeugte lokale Datei-Download-URL.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamisches MCP-Gateway

### `mcp_manage`

Registriert, listet, liest, aktiviert, deaktiviert, aktualisiert, entfernt oder ändert isolierte Environment/Headers dynamischer MCP-Server. Transport `stdio` verwendet command/args/cwd, `streamable_http` verwendet url. Secret-Env/Header-Werte werden privat persistiert und nie zurückgegeben.

| Parameter | Typ | Erforderlich/default | Beschreibung |
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
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Durchsucht gecachte kompakte Tool-Zusammenfassungen aktivierter dynamischer MCP-Server. Dynamische Tools bleiben aus `tools/list` dieses Servers heraus; verwenden Sie den gelieferten Namen `<server>:<tool>` mit `mcp_tool_inspect`, bevor Sie es aufrufen.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Gibt das vollständige gecachte Schema eines dynamischen MCP-Tools namens `<server>:<tool>` zurück. Refresh den Server mit `mcp_manage`, wenn der Cache stale ist.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Ruft ein gecachtes dynamisches MCP-Tool namens `<server>:<tool>` auf. Zuerst mit `mcp_tool_search` entdecken und mit `mcp_tool_inspect` das Schema prüfen. Externe MCP-Verbindungen werden nur für die Dauer dieses Aufrufs geöffnet.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser-Automatisierung

### `browser_session`

Startet, listet, schließt oder bereinigt persistente High-Level-Browser-Sessions lokal oder remote. `start` kann URL öffnen, persistentes `profile_id` wiederverwenden oder `storage_state_path` laden; `close` kann Storage State speichern.

| Parameter | Typ | Erforderlich/default | Beschreibung |
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
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `browser_snapshot`

Erfasst eine persistente Browser-Seite mit Title, URL, begrenztem sichtbarem Text, interaktiven Elementen mit stabilen kurzen Refs wie `e1`, aktuellen Page-/Network-Fehlern und optionalem Screenshot-Pfad. Refs direkt als `browser_act`-Targets verwenden, bis Navigation oder neuer Snapshot erfolgt.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `browser_act`

Führt strukturierte Aktionen in einer persistenten Browser-Session aus: navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text und wait_for_url. `target` kann eine `browser_snapshot`-Ref wie `e1` oder CSS-Selector sein. `browser_run_script` nur verwenden, wenn diese High-Level-Aktionen nicht reichen.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

### `browser_run_script`

Führt ein vollständiges Python-Playwright-Skript lokal oder auf einer Remote-Maschine aus.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.

## Desktop-GUI-Automatisierung

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

## Remote-Worker-Administration

### `remote_manage`

Verwaltet Remote Workers mit action=invite, list, revoke oder rename. invite akzeptiert name/workdir/ttl_s; revoke benötigt machine; rename benötigt machine und new_name.

| Parameter | Typ | Erforderlich/default | Beschreibung |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session für diesen Tool-Aufruf. Übergeben Sie während der Arbeit an der Task die von session_manage zurückgegebene session_id. Verwenden Sie null nur, wenn keine Logical Session aktiv ist. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Wenn `machine` angegeben ist, benötigt der Aufruf zusätzlich `remote:use` und läuft über das Remote-Worker-Protokoll.
