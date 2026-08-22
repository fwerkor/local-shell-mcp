# Referencia de herramientas

Esta página es una vista general localizada de las herramientas. Los nombres de herramientas y parámetros se mantienen como identificadores de código para que coincidan con el MCP schema, el registro de auditoría y los valores devueltos por el Runtime. Para los detalles completos de campos, usa la referencia en inglés y el tools JSON exportado por el Runtime.

## Grupos de herramientas

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

## Recomendaciones de uso

Primero confirma el contexto con herramientas de solo lectura; después usa herramientas de escritura, shell, Git o remotas. En llamadas de mayor riesgo, completa purpose o explanation para facilitar la auditoría.
