# Referência de ferramentas

Esta página é uma visão geral localizada das ferramentas. Nomes de ferramentas e parâmetros permanecem como identificadores de código para corresponder ao MCP schema, ao log de auditoria e aos valores retornados pelo Runtime. Para detalhes completos de campos, use a referência em inglês e o tools JSON exportado pelo Runtime.

## Grupos de ferramentas

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

## Recomendações de uso

Primeiro confirme o contexto com ferramentas somente leitura; depois use ferramentas de escrita, shell, Git ou remotas. Em chamadas de maior risco, preencha purpose ou explanation para facilitar a auditoria.
