<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# 통합된 웹 작업공간

**통합 LSM 웹 작업공간**은 local-shell-mcp를 일상적으로 사용하는 데 권장되는 방법입니다. 수정된 벤더 LibreChat 프런트엔드를 기반으로 AI 채팅, 프로젝트 기록 및 LSM 제어 평면을 하나의 반응형 인터페이스에 결합합니다. [ChatGPT](chatgpt-connector.md) 또는 [Gemini](gemini-spark.md)와 같은 외부 MCP 클라이언트를 계속 연결할 수 있습니다.

작업 영역은 **자체 호스팅되며 선택적으로 설치됩니다**. 이는 최소 컨트롤러 이미지, 독립 실행형 실행 파일 또는 원격 작업자 번들의 일부가 아닌 별도의 웹 서비스입니다. 컨트롤러 전용 배포는 원래 브라우저 UI 및 OpenTUI를 유지합니다.

## 작업실에는 무엇이 있나요?

| 면적 | 당신이 할 수 있는 일 |
|---|---|
| 채팅 및 프로젝트 | 구성된 모델을 선택하고, 대화를 만들고, 프로젝트를 구성하고, 지난 채팅을 찾고, 대화를 보관하세요. 기록은 서버에 남아있습니다. |
| 컨트롤러 개요 | 상태, 최근 활동 및 연결된 컴퓨터를 봅니다. |
| 파일 | 로컬 또는 원격 파일을 찾아보고 관리합니다. |
| 터미널 | 컨트롤러 또는 작업자의 영구 터미널을 사용하여 작업합니다. |
| 데스크탑 | 원격 GUI 세션을 검사하고 제어합니다. |
| 세션 | 내구성 있는 LSM 작업과 해당 수명 주기를 검사합니다. |
| 리모콘 | 아웃바운드 작업자를 연결하고 관리합니다. |
| 감사 | 모델에서 생성된 도구 활동을 검사합니다. |
| 중첩된 MCP | LSM 뒤에 있는 외부 MCP 서버를 등록, 편집, 활성화, 비활성화, 새로 고침 및 제거합니다. |

컨트롤러 경로는 `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` 및 `/control/audit`입니다. 채팅은 `/c/new`에서 열립니다. LSM MCP 관리자는 **LSM의 중첩 MCP 레지스트리**를 제어합니다. LibreChat에서는 두 번째 레지스트리를 생성하지 않습니다.

## 선택적 채팅 스택 배포

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## 로그인하고 채팅을 사용하세요

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

채팅 업로드(최대 32MiB)는 컨트롤러 작업 영역에 저장되며 절대 경로가 모델에 제공됩니다. 브라우저 업로드는 추가 파일 권한을 부여하지 않습니다. 모델 지향 도구 호출은 LSM 인증, 감사 및 원격 작업자 라우터를 통과합니다.

## 외부 MCP, 보안 및 데이터

작업공간 MCP 사이드바를 사용하여 중첩된 외부 MCP 서버를 관리하세요. 이는 별도의 개인 환경 변수 및 요청 헤더를 포함하여 로컬 stdio 서버 및 HTTP 서버를 지원합니다. 비밀은 브라우저에 반환되지 않습니다. **외부 MCP** 채팅 토글을 사용하면 중첩된 도구를 검색, 검사 및 호출할 수 있습니다. 기본 LSM 도구가 비활성화된 경우 모델 `mcp_manage`를 부여하지 않습니다. UI 관리는 일반 컨트롤러 인증으로 보호됩니다.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## 문제 해결

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

구현 세부정보 및 업데이트는 [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) 및 [human interface guide](../guides/human-interface.md)를 참조하세요.
