# Araç başvurusu

Bu sayfa araçların yerelleştirilmiş özetidir. Araç ve parametre adları MCP schema, denetim günlüğü ve Runtime dönüş değerleriyle eşleşmesi için kod tanımlayıcısı olarak kalır. Alanların tam ayrıntıları için İngilizce başvuruya ve Runtime tarafından dışa aktarılan tools JSON çıktısına bakın.

## Araç grupları

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

## Kullanım önerileri

Önce salt okunur araçlarla bağlamı doğrulayın, ardından yazma, shell, Git veya uzak araçları kullanın. Daha riskli çağrılarda denetim için purpose veya explanation doldurun.
