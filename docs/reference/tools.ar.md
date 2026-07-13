# مرجع الأدوات

هذه الصفحة نظرة عامة مترجمة على الأدوات. تبقى أسماء الأدوات والمعاملات كمعرّفات برمجية حتى تطابق MCP schema وسجل التدقيق وقيم Runtime المعادة. للحصول على تفاصيل الحقول الكاملة، استخدم المرجع الإنجليزي وملف tools JSON الذي يصدّره Runtime.

## مجموعات الأدوات

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_info`, `version_info`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### المهارات

`skills_list`, `skill_load`, `skill_read_file`

### Filesystem

`list_files`, `read_file`, `read_many_files`, `write_file`, `edit_file`, `multi_edit_file`, `delete_file_or_dir`, `tree_view`, `glob_search`, `grep_search`

### Shell and jobs

`run_shell_tool`, `run_python_tool`, `shell_start`, `shell_read`, `shell_send`, `shell_kill`, `shell_list`, `job_start`, `job_list`, `job_tail`, `job_stop`, `job_retry`

### Git

`git_status_tool`, `git_diff_tool`, `git_add_tool`, `git_commit_tool`, `git_push_tool`, `git_pull_tool`, `git_fetch_tool`, `git_checkout_tool`, `git_log_tool`, `git_show_tool`, `git_reset_tool`

### Browser automation

`browser_get_text_tool`, `browser_eval_tool`, `browser_screenshot_tool`, `browser_pdf_tool`, `playwright_run_script_tool`, `playwright_install_tool`

### File links

`create_file_link`, `list_file_links`, `revoke_file_link`

### Remote workers

`remote_list_machines`, `remote_invite`, `remote_environment_info`, `remote_run_shell_tool`, `remote_run_python_tool`, `remote_shell_start`, `remote_shell_read`, `remote_shell_send`, `remote_shell_kill`, `remote_shell_list`, `remote_job_start`, `remote_job_list`, `remote_job_tail`, `remote_job_stop`, `remote_job_retry`, `remote_read_file`, `remote_write_file`, `remote_push_file`, `remote_pull_file`, `remote_copy_file`

## إرشادات الاستخدام

ابدأ بتأكيد السياق عبر أدوات القراءة فقط، ثم استخدم أدوات الكتابة أو shell أو Git أو الأدوات البعيدة. في الاستدعاءات الأعلى خطراً، املأ purpose أو explanation لتسهيل التدقيق.
