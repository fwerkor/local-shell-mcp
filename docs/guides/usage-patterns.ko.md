<!-- i18n-source-sha256: 382c9edbbba8fa4fb3aab11dcc4127ba80bff8c7104bdedffdf66b9bbcdb744a -->
# 사용 패턴 및 prompt 가이드

`local-shell-mcp`는 강력한 tools를 제공합니다. 좋은 결과를 얻으려면 먼저 inspect하고, 작은 단계로 행동하고, verification을 실행하고, 무엇이 바뀌었는지 보고하도록 모델에 요청해야 합니다.

## 일반 운영 루프

대부분의 coding task에는 다음 루프를 사용합니다:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` 및 `git status` 같은 command에 `run_shell`을 사용합니다.
2. Plan: 관련된 최소한의 files와 tests를 식별하도록 합니다.
3. Edit: unified `file_edit`, `file_patch` 또는 shell commands를 사용합니다.
4. Verify: `run_shell` 또는 persistent shells로 targeted tests/builds를 실행합니다.
5. Review: `run_shell`로 `git diff`를 실행하고 필요하면 `secret_scan`, `audit_tail`을 사용합니다.
6. Commit/export: `run_shell`의 명시적 Git CLI commands 또는 `link_create`를 사용합니다.

## Tool 선택

| Task | 선호 | 피하기 |
|---|---|---|
| 짧은 one-shot command | `run_shell` | command마다 persistent shell 시작 |
| 장시간 dev server, REPL, watch task | `shell_start` + `shell_read` + `shell_send` | timeout까지 `run_shell` block |
| structured analysis / file generation | `run_python` | 복잡한 JSON/text에 취약한 shell pipeline |
| 작은 exact edit | `file_edit` | 불필요한 전체 file rewrite |
| 한 file의 하나 이상 replacement | `file_edit` with an `edits` array | 다시 읽지 않고 stale edit 반복 |
| multi-file patch | `file_patch` | ad hoc shell edit |
| file 찾기 | `file_tree`, `file_glob` | 큰 repository의 전체 recursive listing |
| code 찾기 | `file_grep` | 많은 file을 무작정 읽기 |
| browser evidence | `browser_snapshot`, `browser_run_script` | page name이나 route로 추측 |
| downloadable artifacts | `link_create` | 큰 binary content를 chat에 붙여넣기 |
| remote machine work | normal tools with `machine`, plus `remote_transfer` | outbound worker로 충분한데 inbound SSH 열기 |

## CLI에서 도구 호출

shell script와 CI에서는 `lsm call <tool>`이 실행 중인 loopback controller를 통해 동일한 등록 도구 표면을 호출하므로 remote worker와 controller 상태가 유지됩니다.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

`--session s_...`으로 호출을 Logical Session에 연결할 수 있습니다. 문서화된 Docker Compose 구성에서는 원본 `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN`이 권한이 제한된 호스트 소유 `.env`에만 저장되고 Compose는 SHA-256 verifier만 controller에 전달합니다. 다른 분리 runtime 구성에서는 `--token-file <path>`를 사용할 수 있습니다. `--direct`는 controller를 우회하고 현재 `.env`의 runtime 설정을 프로세스 내부에 적용하지만 호스트 CLI token은 도구 환경에 주입하지 않으며 로컬 호출만 지원합니다. Human UI token은 `/mcp`에서 절대 허용되지 않으며, 분리 runtime의 controller에는 일치하는 `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256`을 설정해야 합니다.

## Prompt 템플릿

### Read-only repository orientation

```text
local-shell-mcp를 사용하세요. repository layout과 git status를 검사하고 file을 수정하지 마세요. 변경하기 전에 주요 component, 추론 가능한 test command, 명백한 risk를 요약하세요.
```

### Focused bug fix

```text
local-shell-mcp로 bug를 수정하세요. 먼저 가장 작은 relevant command로 재현하거나 위치를 찾고, edit 전에 files를 읽으세요. 최소 patch를 만들고 targeted verification을 실행한 뒤 git diff와 실행한 tests를 정확히 보여 주세요. 승인할 때까지 commit하지 마세요.
```

### Commit 및 push workflow

```text
local-shell-mcp를 사용하세요. git status와 diff를 확인하고 관련 tests와 secret_scan을 실행한 뒤 간결한 message로 focused commit 하나를 만들고 current branch를 push하세요. cache, build artifact, 무관한 formatting은 포함하지 마세요.
```

### 장시간 process

```text
dev server를 persistent shell session에서 시작하고 ready가 될 때까지 output을 읽은 뒤 browser tools로 page를 확인하세요. session id를 유지하고 확인 후 kill하세요.
```

### Remote worker task

```text
연결된 remote worker <machine>을 사용하세요. 먼저 machine=<machine>으로 environment_get를 호출하고 같은 machine으로 file_list를 실행하세요. configured remote workdir 안에서만 작업하고 짧은 command는 run_shell, 장시간 작업은 shell_start 또는 job_start를 사용하세요.
```

## Repository 작업

open-source change 권장 sequence:

1. `run_shell`로 `git status --short --branch`를 실행합니다.
2. upstream state가 중요하면 명시적 Git CLI로 fetch와 branch inspect를 합니다.
3. edit 전에 `file_grep`와 `file_read`을 사용합니다.
4. 최소 patch를 만듭니다.
5. 먼저 targeted tests, 가능하면 broader tests를 실행합니다.
6. commit/push 전에 `secret_scan`을 실행합니다.
7. 명시적으로 stage/commit하고 간결한 message를 사용합니다.

maintainer가 review하기 쉽도록 logical change마다 commit 하나를 요청하십시오.

## 생성 artifact 작업

PDF, report, screenshot, archive, log의 경우:

1. workspace 아래에 file을 생성합니다.
2. file이 존재하고 예상 size인지 확인합니다.
3. 짧은 TTL과 optional `max_downloads`로 `link_create`를 사용합니다.
4. 더 이상 필요 없으면 link를 revoke합니다.

private key, credential directory 또는 무관한 personal data에 public link를 만들지 마십시오.

## Remote machine 작업

Remote worker mode는 outbound HTTPS 요청은 가능하지만 inbound SSH를 받을 수 없는 machine에 유용합니다.

권장 사항:

- `remote_manage(action="invite", ...)` 또는 `remote_manage(action="rename", ...)`로 machine을 생성/rename합니다.
- 작업 전에 `environment_get(machine=...)`를 호출합니다.
- `remote_transfer`로 controller/worker 또는 worker/worker transfer job을 시작하고 일반 `job_*` tools로 관리합니다.
- task 후 `remote_manage(action="revoke", ...)`로 worker를 revoke합니다.

## Anti-patterns

environment가 disposable이고 결과를 이해한 경우가 아니라면 다음 지시를 피하십시오:

- host-launched server에서 “필요한 것은 무엇이든 global install”.
- 시간 제한이나 verification criteria 없이 “될 때까지 실행”.
- generated artifacts가 있는 repository에서 “모두 commit”.
- 편의를 위해 “home directory 전체 expose”.
- “workspace 전체에 대한 file link 생성”.
- `LOCAL_SHELL_MCP_AUTH_MODE=none`으로 public deployment 실행.
