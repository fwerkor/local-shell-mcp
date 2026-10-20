<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# 원격 workers

Remote worker를 사용하면 outbound HTTP(S) 요청은 보낼 수 있지만 inbound SSH 연결은 받을 수 없는 머신을 `local-shell-mcp`가 제어할 수 있습니다.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## 기본 워크플로

1. `remote_manage(action="invite", ...)`로 초대를 만듭니다.
2. 생성된 command를 remote machine에서 실행합니다.
3. `remote_manage(action="list")`로 등록을 확인합니다.
4. `machine="<worker-name>"`을 지정하여 일반 tool을 호출합니다. 예: `environment_get`, `run_shell`, `file_read`, `browser_run_script`.
5. `remote_transfer`로 controller-to-worker, worker-to-controller 또는 worker-to-worker의 추적되는 file/directory transfer를 시작합니다. `job_list` 또는 `job_tail`로 확인하고 `job_stop` 또는 `job_retry`로 중지하거나 재시도합니다.
6. `remote_manage(action="rename", ...)` 또는 `remote_manage(action="revoke", ...)`로 worker를 rename/revoke합니다.

worker administration만 `remote_*` 이름을 사용합니다. execution, shell, job, filesystem, patch, browser 작업은 local과 remote에서 동일한 schema를 공유합니다. machine을 지정하면 추가로 `remote:use` OAuth scope가 필요합니다.

## 지속 worker

초대 결과에는 플랫폼별 command가 포함됩니다.

- `persistent_command`는 Linux/macOS에서 user service를 설치하고 시작합니다.
- `powershell_persistent_command`는 PowerShell에서 Windows user task를 설치하고 시작합니다.

Windows에서 `local-shell-mcp worker install-service`는 현재 사용자를 위해 `local-shell-mcp-worker` task를 등록합니다. 즉시 시작되고, 재부팅 후 해당 사용자가 로그인하면 다시 시작되며, 배터리 동작을 허용하고, 중복 시작을 무시하고, 실패한 실행을 재시도합니다. 관리자 권한이 필요하지 않으며 사용자가 로그인하기 전에는 실행되지 않습니다.

모든 platform에서 동일한 lifecycle command를 사용합니다.

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

worker log는 worker state directory의 `worker.log`에 저장됩니다.

## 기능

Worker는 shell/persistent shell session, tracked job, filesystem operation, transfer internals, Python execution, patch 및 의존성이 설치된 경우 Playwright를 지원합니다. Git은 `run_shell(machine=...)`에서 표준 command를 사용합니다.

## 보안 및 버전

등록된 worker는 MCP client에 구성된 환경에 대한 제어 권한을 제공합니다. 짧은 invite TTL, 전용 work directory/account를 사용하고 audit log를 검토하며 작업 후 worker를 revoke하십시오. 생성된 초대는 control server version과 일치하는 worker code를 설치합니다.

## 문제 해결

worker가 나타나지 않으면 outbound HTTPS access, public base URL 접근성, invite expiry, system time, control-server log를 확인하십시오.
