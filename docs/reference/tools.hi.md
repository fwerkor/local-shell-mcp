# टूल संदर्भ

यह पृष्ठ टूल का स्थानीयकृत सारांश है। टूल और पैरामीटर नाम कोड identifiers के रूप में रखे गए हैं ताकि वे MCP schema, audit log और Runtime return values से मेल खाएँ। पूर्ण field details के लिए अंग्रेज़ी reference और Runtime द्वारा export किए गए tools JSON को आधार मानें।

## टूल समूह

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

## उपयोग सुझाव

पहले read-only टूल से context की पुष्टि करें, फिर writing, shell, Git या remote टूल का उपयोग करें। अधिक जोखिम वाले calls में audit के लिए purpose या explanation भरें।
