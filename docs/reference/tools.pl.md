# Dokumentacja narzędzi

Ta strona jest zlokalizowanym przeglądem narzędzi. Nazwy narzędzi i parametrów pozostają identyfikatorami kodu, aby zgadzały się z MCP schema, dziennikiem audytu i wartościami zwracanymi przez Runtime. Pełne szczegóły pól znajdują się w angielskiej dokumentacji i w tools JSON eksportowanym przez Runtime.

## Grupy narzędzi

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

## Zalecenia użycia

Najpierw potwierdź kontekst narzędziami tylko do odczytu, a potem używaj narzędzi zapisu, shell, Git lub zdalnych. Przy bardziej ryzykownych wywołaniach wypełnij purpose albo explanation, aby ułatwić audyt.
