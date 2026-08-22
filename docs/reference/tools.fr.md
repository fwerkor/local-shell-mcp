# Référence des outils

Cette page est une vue d’ensemble localisée des outils. Les noms d’outils et de paramètres restent des identifiants de code afin de correspondre au MCP schema, au journal d’audit et aux valeurs renvoyées par le Runtime. Pour le détail complet des champs, utilisez la référence anglaise et le tools JSON exporté par le Runtime.

## Groupes d’outils

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_get`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### Skills

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

## Conseils d’utilisation

Vérifiez d’abord le contexte avec des outils en lecture seule, puis utilisez les outils d’écriture, shell, Git ou distants. Pour les appels plus sensibles, renseignez purpose ou explanation afin de faciliter l’audit.
