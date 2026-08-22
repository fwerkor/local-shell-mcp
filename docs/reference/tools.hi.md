# टूल संदर्भ

यह पृष्ठ टूल का स्थानीयकृत सारांश है। टूल और पैरामीटर नाम कोड identifiers के रूप में रखे गए हैं ताकि वे MCP schema, audit log और Runtime return values से मेल खाएँ। पूर्ण field details के लिए अंग्रेज़ी reference और Runtime द्वारा export किए गए tools JSON को आधार मानें।

## टूल समूह

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

## उपयोग सुझाव

पहले read-only टूल से context की पुष्टि करें, फिर writing, shell, Git या remote टूल का उपयोग करें। अधिक जोखिम वाले calls में audit के लिए purpose या explanation भरें।
