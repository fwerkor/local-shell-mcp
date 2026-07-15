# Referencia de herramientas

Esta página es una vista general localizada de las herramientas. Los nombres de herramientas y parámetros se mantienen como identificadores de código para que coincidan con el MCP schema, el registro de auditoría y los valores devueltos por el Runtime. Para los detalles completos de campos, usa la referencia en inglés y el tools JSON exportado por el Runtime.

## Grupos de herramientas

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_info`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### Skills

`skills_list`, `skill_load`, `skill_read_file`

### Filesystem

`list_files`, `read_file`, `write_file`, `edit_file`, `delete_file_or_dir`, `transfer_path`, `tree_view`, `glob_search`, `grep_search`

### Shell and jobs

`run_shell_tool`, `run_python_tool`, `shell_start`, `shell_read`, `shell_send`, `shell_kill`, `shell_list`, `job_start`, `job_list`, `job_tail`, `job_stop`, `job_retry`

### Browser automation

`browser_get_text_tool`, `browser_capture_tool`, `playwright_run_script_tool`

### File links

`create_file_link`, `list_file_links`, `revoke_file_link`

### Remote workers

`remote_invite`, `remote_list_machines`, `remote_rename_machine`, `remote_revoke_machine`; normal tools use optional `machine`, and `transfer_path` handles transfers

## Recomendaciones de uso

Primero confirma el contexto con herramientas de solo lectura; después usa herramientas de escritura, shell, Git o remotas. En llamadas de mayor riesgo, completa purpose o explanation para facilitar la auditoría.
