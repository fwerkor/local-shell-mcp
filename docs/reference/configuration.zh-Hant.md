# 配置

環境變量使用 `LOCAL_SHELL_MCP_` 前綴，並覆蓋由 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 加載的 YAML 配置值。YAML key 使用下表中的字段名。

## 優先級

1. `Settings` 內置默認值。
2. 由 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 選擇的 YAML 配置。
3. 帶 `LOCAL_SHELL_MCP_` 前綴的環境變量。
4. `--mode`、`--config`、`--remote`、`--no-remote` 等 CLI 參數；這些參數會在加載 settings 前設置對應環境值。

## 最小公開配置

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

僅本地測試時，`auth_bypass_localhost` 默認啓用。不要在公網暴露未認證的完整 MCP 工具。

## 設置參考

### 服務與工作區

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` | 服務綁定地址。 |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` | 服務監聽端口。 |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`、`http`、`stdio`，或保留值 `both`。 |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` | 工具默認控制的工作區根目錄。 |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` | 運行時狀態目錄。 |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` | 審計日誌路徑。 |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` | agent 配置目錄。 |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | 爲 true 時禁用工作區 / 路徑限制；只在一次性邊界內使用。 |

### 限制

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `default_timeout_s` | `LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S` | `60` | 默認命令超時時間，單位秒。 |
| `max_timeout_s` | `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | `3600` | 允許配置的最大超時時間。 |
| `max_output_bytes` | `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | `200000` | 單次工具輸出最大字節數。 |
| `max_file_read_bytes` | `LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES` | `512000` | 單文件讀取最大字節數。 |
| `max_file_write_bytes` | `LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES` | `5000000` | 單文件寫入最大字節數。 |
| `max_grep_results` | `LOCAL_SHELL_MCP_MAX_GREP_RESULTS` | `200` | grep 搜索最大結果數。 |
| `max_directory_entries` | `LOCAL_SHELL_MCP_MAX_DIRECTORY_ENTRIES` | `5000` | 目錄列表最大條目數。 |
| `max_glob_results` | `LOCAL_SHELL_MCP_MAX_GLOB_RESULTS` | `5000` | glob 搜索最大結果數。 |
| `max_tree_entries` | `LOCAL_SHELL_MCP_MAX_TREE_ENTRIES` | `5000` | tree 視圖最大條目數。 |
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | 單次註冊表掃描最多返回的 Skill 目錄數。 |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | 單個 Skill 最多返回的關聯檔案數。 |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | 單次 `skills_list` 註冊表掃描或單次指定 Skill 載入最多檢查的檔案系統條目數。 |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | 返回的關聯檔案路徑可佔用的最大 UTF-8 位元組數。 |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` | 批量讀取最大文件數。 |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` | 批量讀取總字節上限。 |
| `max_todos` | `LOCAL_SHELL_MCP_MAX_TODOS` | `1000` | todo 記錄最大數量。 |
| `max_todo_bytes` | `LOCAL_SHELL_MCP_MAX_TODO_BYTES` | `1000000` | todo 數據最大字節數。 |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | 每次長任務運行保留的最大輸出字節數。 |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` | `audit_tail` 最大返回字節數。 |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` | 審計日誌文件大小上限。 |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` | 臨時文件最大數量。 |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` | 臨時文件總字節上限。 |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | 解包目錄傳輸歸檔時允許的最大成員數量。 |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | 目錄傳輸歸檔允許聲明的最大解壓後總字節數。 |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` | 併發命令數量上限。 |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux session 數量上限。 |

### Agent bridge

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `agent_bridge_enabled` | `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED` | `False` | 是否啓用 agent bridge。 |
| `agent_mcp_probe_timeout_s` | `LOCAL_SHELL_MCP_AGENT_MCP_PROBE_TIMEOUT_S` | `5.0` | agent MCP 探測超時時間。 |
| `agent_mcp_call_timeout_s` | `LOCAL_SHELL_MCP_AGENT_MCP_CALL_TIMEOUT_S` | `60.0` | agent MCP 調用超時時間。 |
| `agent_dynamic_mcp_tools` | `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` | `False` | 是否啓用動態 MCP 工具。 |

### 文件鏈接

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` | 是否啓用文件下載鏈接。 |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` | 默認鏈接 TTL，單位秒。 |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` | 最大鏈接 TTL。 |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` 表示默認不限制下載次數。 |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` 表示下載鏈接無配置層文件大小上限。 |

### 遠程 worker

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | 控制 `/join`、`/remote/*` 和 `remote_*` MCP 工具。 |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | 遠程邀請默認 TTL。 |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | 遠程輪詢超時。 |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | 遠程 job 默認超時。 |

### Shell 與可執行路徑

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` | shell 可執行文件。 |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` | 傳給 shell 前需要屏蔽的環境變量。 |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | 環境變量中用逗號分隔，YAML 中用列表。 |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | tmux 可執行文件。 |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` | ripgrep 可執行文件。 |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` | git 可執行文件。 |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` | Python 可執行文件。 |

### 認證與 OAuth

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | 公開部署使用 `oauth`。 |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` | 是否允許 localhost 繞過認證。 |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `False` | 工具發現是否要求認證。 |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | 外部 HTTPS origin。不要包含 `/mcp`。 |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` | OAuth issuer 覆蓋值。 |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` | OAuth resource 覆蓋值。 |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` | OAuth 管理 PIN。 |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> | OAuth JWT secret。 |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` 表示訪問令牌不自動過期。 |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` | OAuth code TTL。 |

### 內置策略列表

| YAML key | 環境變量 | 默認值 | 說明 |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | full-container 模式啓用時會自動清空。 |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | full-container 模式啓用時會自動清空。 |

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

## 運維建議

- 除非容器或 VM 是一次性的，否則保持 `allow_full_container=false`。
- 任何公開端點都保持 `auth_mode=oauth`。
- 如果不用遠程 worker，關閉 `remote_enabled`。
- 如果從不需要聊天中下載產物，關閉 `file_download_enabled`。
- 命令、文件和審計限制應足夠支持編程任務，同時避免意外輸出失控。
