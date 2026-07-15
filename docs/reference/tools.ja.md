# ツールリファレンス

このページはローカライズされたツール参照の概要です。ツール名とパラメータ名は MCP schema、監査ログ、Runtime の戻り値と対応しやすいようにコード識別子のままにしています。完全なフィールド詳細は英語リファレンスと Runtime が出力する tools JSON を参照してください。

## ツール分類

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

## 利用上の指針

まず読み取り専用ツールで文脈を確認し、その後に書き込み、shell、Git、リモートツールを使います。リスクのある呼び出しでは監査のため purpose または explanation を入力します。
