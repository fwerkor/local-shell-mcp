<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# 사용자 인터페이스

`local-shell-mcp`는 동일한 service API, workspace, persistent terminal registry, remote-worker registry, MCP audit log 위에 호환되는 두 가지 human interface를 제공합니다.

- **Web UI**는 빠른 운영 상태 확인에 최적화된 네이티브 브라우저 대시보드입니다.
- **OpenTUI**는 완전한 터미널 중심 애플리케이션으로, 브라우저 안에서도 네이티브 터미널 명령으로도 사용할 수 있습니다.

어느 mode도 별도의 control plane을 만들지 않습니다. interface를 전환해도 연결된 machine, Session, job, permission, audit data는 바뀌지 않습니다.

## 서비스 시작

평소와 같이 `local-shell-mcp`를 시작합니다.

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

ChatGPT가 MCP Apps를 렌더링할 수 있으면 `workspace_open(session_id=...)`은 **명시적으로 선택한 Logical Session**의 플로팅 협업 뷰를 엽니다. objective, progress, Plan, Activity 같은 지속 task state는 Session이 소유하고, Live Workspace는 그 state와 live activity, 사람용 control만 표시합니다. MCP transport에서 task identity를 추론하지 않습니다.

일반적인 명시적 handoff 흐름은 다음과 같습니다.

```text
session_manage(action="start", objective=...)
        -> session_id
... 각 tool call에 logical_session_id=session_id 전달
... session_manage(action="report", session_id=...) ...
새 ChatGPT conversation
사용자가 이전 session_id를 전달
session_manage(action="resume", session_id=...)
        -> 기존 progress, Plan, 최근 Activity
workspace_open(session_id=...)
        -> 동일한 Session 표시
```

`session_id`가 유일한 지속 task identity입니다. Agent는 다른 conversation의 Session을 list하거나 추론하거나 자동 선택해서는 안 됩니다. 새 conversation에서 작업을 계속하려면 사용자가 기존 `session_id`를 명시적으로 전달합니다. Agent는 start/resume 직후, 의미 있는 progress checkpoint, 그리고 turn을 끝내기 전에 현재 사용 중인 `session_id`를 사용자에게 알려 수동 handoff가 가능하게 해야 합니다. Session은 machine이나 working directory에 묶이지 않으며 일반 tool parameter가 계속 local/remote target과 path를 선택합니다.

선택적 `plan_manage` Plan은 Session의 Goal mode를 활성화합니다. Plan이 active이고 15분 동안 agent activity가 없으면 연결된 Live Workspace가 ChatGPT에 continuation을 요청할 수 있습니다. continuation은 동일한 명시적 `session_id`를 resume하며 accepted/rejected 여부와 관계없이 최대 10회로 제한됩니다. blocked, completed, cancelled Plan은 자동 continuation되지 않습니다. 모든 step이 completed/skipped인 active Plan은 resumed agent가 Plan을 정식으로 finish할 수 있도록 cleanup continuation 대상에 남습니다. 사람의 pause/resume/cancel control은 임시 Live Workspace state가 아니라 Session 소유 Plan을 갱신합니다.

## 브라우저 인터페이스

다음을 엽니다.

```text
http://127.0.0.1:8765/ui
```

공개 배포에서는 설정된 HTTPS origin을 사용합니다.

```text
https://your-public-host.example.com/ui
```

브라우저 인터페이스는 MCP와 동일한 OAuth 서버와 scope를 사용합니다. 로그인 화면을 불러올 수 있도록 페이지 셸과 정적 자산은 공개되어 있지만 `/api/ui/*`와 OpenTUI 터미널 WebSocket은 보호됩니다. 액세스 토큰은 브라우저 session storage에만 저장됩니다.

### 인터페이스 선택

OAuth 화면에는 두 개의 진입점이 있습니다.

- **Open Web UI**는 인증 후 네이티브 대시보드를 엽니다.
- **Continue to OpenTUI**는 인증 후 터미널 인터페이스를 열어 기존 브라우저 동작을 유지합니다.

인증 후에는 다시 로그인하지 않고 사이드바의 인터페이스 선택기로 Web UI와 OpenTUI를 전환할 수 있습니다. 잠시 OpenTUI로 이동해도 현재 네이티브 페이지는 기억됩니다.

다음 경로는 북마크할 수 있습니다.

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web`와 `#/dashboard`는 Overview의 별칭이고, `#/tui`와 `#/opentui`는 Console의 별칭입니다.

## 네이티브 Web UI

네이티브 Web UI는 기존 사용자 인터페이스 API를 5초마다 폴링하고 터미널 셀 대신 브라우저 네이티브 컨트롤을 렌더링합니다. OpenTUI를 선택하기 전에는 PTY를 시작하지 않습니다.

### Overview

Overview는 가장 중요한 운영 정보를 먼저 표시합니다.

- Controller 상태와 현재 LSM 버전.
- 온라인 및 오프라인 머신 수.
- 활성 tracked job과 영구 터미널 세션.
- CPU, 메모리, 워크스페이스 디스크, load, 네트워크 처리량 및 uptime.
- worker 상태, 리소스 임계값, 실패한 job 및 실패한 MCP 호출에서 생성된 경고.
- 최근 모델에서 시작된 MCP 활동.

### Machines

Machines는 로컬 controller와 연결된 원격 worker를 상태, 플랫폼, 버전, 작업 디렉터리, 기능 및 last-seen 정보와 함께 보여 줍니다.

### Workloads

Workloads는 활성 tracked job과 독립적인 영구 shell 세션을 함께 표시합니다. Web UI에서는 이러한 레코드를 읽기만 할 수 있으며, 대화형 세션 관리에는 OpenTUI를 사용합니다.

### Activity

Activity는 현재 경고와 최근 MCP 감사 활동을 결합합니다. 사람이 입력한 명령과 파일 작업은 MCP 감사 로그에서 제외됩니다.

## 브라우저 OpenTUI

**OpenTUI**를 선택하면 네이티브 터미널 런처와 동일한 OpenTUI 애플리케이션이 지연 시작됩니다. 브라우저 console은 다음 기능을 유지합니다.

- WebSocket을 통한 인증된 바이너리 PTY 전송.
- 자동 터미널 크기 조정 및 재연결 백오프.
- OpenTUI 컨트롤의 마우스 상호작용.
- 전체 화면 모드 및 브라우저에 안전한 키보드 단축키.
- 모바일 단축키와 명시적인 소프트 키보드 제어.
- xterm.js를 통한 SIXEL 및 inline image 지원.

사용자가 네이티브 Web UI 모드에 머무는 동안 브라우저는 OpenTUI PTY를 만들지 않습니다.

## 네이티브 OpenTUI

독립 실행 release 파일에는 플랫폼 OpenTUI runtime이 포함됩니다. 기본 실행 파일만 유지하고 서비스를 시작한 다음 다음을 실행합니다.

```bash
local-shell-mcp tui
```

네이티브 TUI는 사용자에게 로그인을 요구하지 않습니다. 문서화된 Docker Compose 구성에서는 launcher가 loopback Human UI API에 대해 host에만 보관되는 전용 CLI credential을 재사용하며, 다른 split-runtime 구성은 `--token-file`을 사용할 수 있습니다. 브라우저에서 생성된 OpenTUI는 controller process 안에서 필요할 때만 생성되는 credential을 사용하고 state directory나 state backend에는 절대 저장하지 않습니다. reverse proxy는 단지 loopback으로 연결했다는 이유만으로 이 로컬 bypass를 얻지 못합니다.

소스 checkout에서도 Bun 의존성을 설치한 뒤 TUI를 실행할 수 있습니다.

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

로컬 서비스가 기본 포트가 아닌 경우에만 `--api-base`를 사용합니다.

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## OpenTUI 화면

### Dashboard

Dashboard는 OpenTUI 운영 개요입니다. 넓은 터미널에서는 node, workload, alert, activity, 시스템 정보 및 trend 영역을 분리해 보여 주고, 좁은 터미널에서는 가로 스크롤 없이 압축된 요약으로 접습니다.

### Files

Files는 로컬 및 원격 머신을 위한 LSM 네이티브 3패널 파일 관리자입니다. 생성, 편집, 이름 변경, 복사, 이동, 붙여넣기, 삭제, 숨김 파일 토글, 새로 고침, 텍스트 미리보기, 바이너리 미리보기 및 제한된 이미지 썸네일을 제공합니다.

### Terminals

Terminals는 로컬 및 원격 머신의 영구 shell 세션을 관리합니다. 완전한 명령 입력, raw 대화형 입력, 세션 전환, 세션 생성과 종료, 최근 출력, 접을 수 있는 MCP 감사 레일을 지원합니다.

### Audit

Audit는 제한된 JSONL 감사 로그를 읽고 node, operation, event, session, search, time-range 및 sort 필터와 레코드 상세 검사를 지원합니다.

### Remotes

Remotes는 온라인 및 오프라인 원격 worker, 기능, 작업 디렉터리 및 시스템 메타데이터를 표시합니다. 일회성 join invite를 만들고 node 이름을 바꾸거나 영구 identity를 revoke할 수 있습니다.

## OpenTUI 탐색

상단 카테고리 바와 상황별 푸터 작업은 네이티브 터미널과 브라우저 console 모두에서 마우스로 클릭할 수 있습니다.

| 키 | 동작 |
|---|---|
| `Alt+1` … `Alt+5` | Dashboard, Files, Terminals, Remotes, Audit를 엽니다. |
| `F2` … `F6` | 대체 category shortcut. |
| `F1` | 키보드 가이드를 엽니다. |
| `F9` | 머신 목록을 새로 고칩니다. |
| `Alt+Q` | 브라우저 예약 Ctrl 단축키를 호출하지 않고 네이티브 OpenTUI 프로세스를 종료합니다. |

Terminals에서는 `Alt+N`으로 새 세션을 만들고, `Alt+W`로 선택한 세션을 종료하고, `Alt+A`로 감사 레일을 전환하고, `Alt+R`로 새로 고치며, `Alt+Left/Right`로 세션을 전환합니다. 브라우저 console은 브라우저 수준 탐색이나 메뉴 처리보다 먼저 이 키 조합을 가로챕니다.

## 구성

| YAML key | 환경 변수 | 기본값 | 용도 |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | 사용자 인터페이스를 마운트하거나 비활성화합니다. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | MCP 서비스의 브라우저 인터페이스 마운트 경로입니다. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | 네이티브 OpenTUI 실행 파일 해석을 재정의합니다. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | OpenTUI 브라우저 console 배포를 위해 유지되는 배경화면 설정입니다. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | 비활성 브라우저 OpenTUI PTY를 이 초 수 뒤에 닫습니다. `0`은 비활성화합니다. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | 동시 브라우저 OpenTUI PTY 세션 최대 수입니다. |

## 패키징 참고

- Docker 이미지는 Web UI 자산과 네이티브 OpenTUI runtime을 포함합니다.
- 독립 실행 파일은 Web UI 자산과 압축된 플랫폼 OpenTUI runtime을 내장합니다.
- Python wheel은 브라우저 자산을 포함합니다. 네이티브 OpenTUI에는 release 실행 파일 또는 Bun 의존성이 설치된 소스 checkout이 필요합니다.
- 두 인터페이스 모두 MCP와 같은 프로세스와 포트에서 제공되므로 별도의 웹 서비스가 필요하지 않습니다.
