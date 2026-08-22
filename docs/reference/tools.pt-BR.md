# Referência de ferramentas

Esta página é uma visão geral localizada das ferramentas. Nomes de ferramentas e parâmetros permanecem como identificadores de código para corresponder ao MCP schema, ao log de auditoria e aos valores retornados pelo Runtime. Para detalhes completos de campos, use a referência em inglês e o tools JSON exportado pelo Runtime.

## Grupos de ferramentas

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

## Recomendações de uso

Primeiro confirme o contexto com ferramentas somente leitura; depois use ferramentas de escrita, shell, Git ou remotas. Em chamadas de maior risco, preencha purpose ou explanation para facilitar a auditoria.
