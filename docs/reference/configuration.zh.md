# 配置

环境变量使用 `LOCAL_SHELL_MCP_` 前缀，并覆盖由 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 加载的 YAML 配置值。YAML key 使用下表中的字段名。

## 优先级

1. `Settings` 内置默认值。
2. 由 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 选择的 YAML 配置。
3. 带 `LOCAL_SHELL_MCP_` 前缀的环境变量。
4. `--mode`、`--config`、`--remote`、`--no-remote` 等 CLI 参数；这些参数会在加载 settings 前设置对应环境值。

## 最小公开配置

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

仅本地测试时，`auth_bypass_localhost` 默认启用。不要在公网暴露未认证的完整 MCP 工具。

## 设置参考

### 服务与工作区

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` | 服务绑定地址。 |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` | 服务监听端口。 |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`、`http`、`stdio`，或保留值 `both`。 |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` | 工具默认控制的工作区根目录。 |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` | 运行时状态目录。 |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` | 审计日志路径。 |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` | agent 配置目录。 |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | 为 true 时禁用工作区 / 路径限制；只在一次性边界内使用。 |

### 限制

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `default_timeout_s` | `LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S` | `60` | 默认命令超时时间，单位秒。 |
| `max_timeout_s` | `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | `3600` | 允许配置的最大超时时间。 |
| `max_output_bytes` | `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | `200000` | 单次工具输出最大字节数。 |
| `max_file_read_bytes` | `LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES` | `512000` | 单文件读取最大字节数。 |
| `max_file_write_bytes` | `LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES` | `5000000` | 单文件写入最大字节数。 |
| `max_grep_results` | `LOCAL_SHELL_MCP_MAX_GREP_RESULTS` | `200` | grep 搜索最大结果数。 |
| `max_directory_entries` | `LOCAL_SHELL_MCP_MAX_DIRECTORY_ENTRIES` | `5000` | 目录列表最大条目数。 |
| `max_glob_results` | `LOCAL_SHELL_MCP_MAX_GLOB_RESULTS` | `5000` | glob 搜索最大结果数。 |
| `max_tree_entries` | `LOCAL_SHELL_MCP_MAX_TREE_ENTRIES` | `5000` | tree 视图最大条目数。 |
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | 单次注册表扫描最多返回的 Skill 目录数。 |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | 单个 Skill 最多返回的关联文件数。 |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | 单次 `skills_list` 注册表扫描或单次指定 Skill 加载最多检查的文件系统条目数。 |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | 返回的关联文件路径可占用的最大 UTF-8 字节数。 |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` | 批量读取最大文件数。 |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` | 批量读取总字节上限。 |
| `max_todos` | `LOCAL_SHELL_MCP_MAX_TODOS` | `1000` | todo 记录最大数量。 |
| `max_todo_bytes` | `LOCAL_SHELL_MCP_MAX_TODO_BYTES` | `1000000` | todo 数据最大字节数。 |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | MCP、REST、OAuth、UI 与远程 worker 端点允许缓冲的最大 HTTP 请求体字节数。 |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | 每次长任务运行保留的最大输出字节数。 |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | 最多保留的长任务记录数；运行中的任务不会被清理。 |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` | `audit_tail` 最大返回字节数。 |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` | 审计日志文件大小上限。 |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` | 临时文件最大数量。 |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` | 临时文件总字节上限。 |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | 解包目录传输归档时允许的最大成员数量。 |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | 目录传输归档允许声明的最大解压后总字节数。 |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` | 并发命令数量上限。 |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux、ConPTY 与 native fallback 共用的持久 shell session 数量上限。 |

### 文件链接

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` | 是否启用文件下载链接。 |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` | 默认链接 TTL，单位秒。 |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` | 最大链接 TTL。 |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` 表示默认不限制下载次数。 |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` 表示下载链接无配置层文件大小上限。 |

### 远程 worker

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | 控制 `/join`、`/remote/*` 和 `remote_*` MCP 工具。 |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | 远程邀请默认 TTL。 |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | 远程轮询超时。 |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | 远程 job 默认超时。 |

### Shell 与可执行路径

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` | shell 可执行文件。 |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` | 传给 shell 前需要屏蔽的环境变量。 |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | 环境变量中用逗号分隔，YAML 中用列表。 |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | 首选 tmux 可执行文件；不可用时 Linux 发行包和 Docker 使用内置 helper，其余情况退回 native backend。 |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` | ripgrep 可执行文件。 |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` | git 可执行文件。 |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` | Python 可执行文件。 |

### 认证与 OAuth

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | 公开部署使用 `oauth`。 |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` | 是否允许 localhost 绕过认证。 |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `False` | 工具发现是否要求认证。 |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | 外部 HTTPS origin。不要包含 `/mcp`。 |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` | OAuth issuer 覆盖值。 |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` | OAuth resource 覆盖值。 |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` | OAuth 管理 PIN。 |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> | OAuth JWT secret。 |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` 表示访问令牌不自动过期。 |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` | OAuth code TTL。 |

### 内置策略列表

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | full-container 模式启用时会自动清空。 |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | full-container 模式启用时会自动清空。 |

## YAML 示例

```yaml
host: 0.0.0.0
port: 8765
mode: mcp
workspace_root: /workspace
auth_mode: oauth
remote_enabled: true
file_download_enabled: true
shell_env_blocked_prefixes:
  - LOCAL_SHELL_MCP_
  - DOCKER_
```

## 运维建议

- 除非容器或 VM 是一次性的，否则保持 `allow_full_container=false`。
- 任何公开端点都保持 `auth_mode=oauth`。
- 如果不用远程 worker，关闭 `remote_enabled`。
- 如果从不需要聊天中下载产物，关闭 `file_download_enabled`。
- 命令、文件和审计限制应足够支持编程任务，同时避免意外输出失控。
