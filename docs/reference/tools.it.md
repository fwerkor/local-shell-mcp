# Riferimento degli strumenti

Questa pagina è una panoramica localizzata degli strumenti. I nomi di strumenti e parametri restano identificatori di codice per corrispondere a MCP schema, log di audit e valori restituiti dal Runtime. Per i dettagli completi dei campi, usa il riferimento in inglese e il tools JSON esportato dal Runtime.

## Gruppi di strumenti

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_get`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### Skill

`skill_list`, `skill_load`, `skill_read`

### Filesystem

`file_list`, `file_read`, `file_write`, `file_edit`, `file_delete`, `remote_transfer`, `file_tree`, `file_glob`, `file_grep`

### Shell and jobs

`run_shell`, `run_python`, `shell_start`, `shell_read`, `shell_send`, `shell_stop`, `shell_list`, `job_start`, `job_list`, `job_tail`, `job_stop`, `job_retry`

### Browser automation

`browser_get_text_tool`, `browser_capture_tool`, `browser_run_script`

### File links

`link_create`, `link_list`, `link_revoke`

### Remote workers

`remote_manage` (`invite`, `list`, `rename`, `revoke`); normal tools use optional `machine`, and `remote_transfer` handles transfers

## Indicazioni d’uso

Conferma prima il contesto con strumenti in sola lettura, poi usa strumenti di scrittura, shell, Git o remoti. Per chiamate più rischiose, compila purpose o explanation per facilitare l’audit.
