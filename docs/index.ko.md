<!-- i18n-source-sha256: 276e9356b895a85759d31467512bdc530c9baa216a368df4ef1bccce39530d0e -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">자체 호스팅 AI 작업 공간 · MCP 제어 평면</span>

# local-shell-mcp

하나의 자체 호스팅 인터페이스에 채팅, 프로젝트, 파일, 터미널, 원격 시스템 및 AI 도구가 포함되어 있습니다. 필요할 때 외부 MCP 클라이언트를 연결하세요.

<div class="hero-actions" markdown>
[시작하기](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Tools reference](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### 실제 coding environment
하나의 MCP endpoint에서 tests 실행, repository 검사, file patch, Git 조작, audit trail 유지를 수행합니다.
</div>

<div class="feature-card" markdown>
### 통합된 웹 작업공간
컨트롤러 파일, 터미널, 데스크톱, 세션, 원격 및 감사와 함께 내장된 채팅 및 프로젝트 기록을 사용하세요. 외부 MCP 클라이언트는 선택 사항으로 유지됩니다.
</div>

<div class="feature-card" markdown>
### Remote machine control
SSH port를 열지 않고 outbound worker connection으로 NAT, firewall 또는 HPC machine을 연결합니다.
</div>
</div>

## 제공 기능

`local-shell-mcp`는 통합된 자체 호스팅 AI 작업 공간과 외부 클라이언트를 위한 MCP 서버를 제공합니다. 인증된 MCP 엔드포인트를 통해 셸, 영구 셸, 파일 시스템, 검색, 패치, Git, Playwright, 감사, 선택적 목표 계획이 포함된 내구성 있는 논리 세션, 토큰화된 파일 링크 및 원격 작업자 도구를 제공합니다.

AI가 repository를 검사하고 tests를 실행하고 files를 편집하고 Git을 조작하고 browser evidence를 수집하고 downloadable artifacts를 만들거나 control server로 outbound 연결만 가능한 remote machine을 제어해야 할 때 사용합니다.

## 아키텍처

```text
Runtime layer: Docker / VS Code extension / binary / Python / stdio
Exposure layer: localhost / HTTPS proxy / tunnel / stdio pipe
클라이언트 레이어: 통합 WebUI / Gemini / ChatGPT / 일반 MCP 클라이언트
Controlled workspace: /workspace or configured workspace root
Optional remote workers: outbound machine connections
```

의도된 isolation boundary는 service를 실행하는 container 또는 VM입니다.

## 시나리오별 시작

| 시나리오 | 시작 페이지 | 이유 |
|---|---|---|
| 기본 브라우저 작업공간 | [Unified web workspace](getting-started/web-workspace.md) | 공유 로그인이 포함된 채팅, 프로젝트 및 LSM 제어 페이지 |
| 첫 번째 컨트롤러 배포 | [Quickstart](getting-started/quickstart.md) | 권장 소스 배포, OAuth 및 첫 브라우저 세션. |
| runtime layer 선택 | [Runtime choices](guides/deployment.md) | Docker, VS Code, binary, Python, stdio를 별도 runtime option으로 설명 |
| Gemini Spark 연결하기 | [Gemini Custom Apps](getting-started/gemini-spark.md) | 자격, HTTPS MCP URL, OAuth 및 테스트 |
| ChatGPT를 client로 추가 | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, 첫 안전 prompt, tool discovery |
| LSM을 DeepSeek Harness에 추가 | [DeepSeek Harness plugin](clients/deepseek-harness.md) | 이 repository를 DSH bundle로 설치하면서 전체 LSM tool 및 remote-worker surface 유지 |
| VS Code에서 실행 | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime 및 host safety 참고 |
| toolset 운영 방법 학습 | [Usage patterns](guides/usage-patterns.md) | Prompt template과 tool 선택 안내 |
| 모든 tool 이해 | [Tools reference](reference/tools.md) | 각 tool의 purpose, inputs, returns, combinations, notes |
| HPC, NPU/GPU 또는 server node 연결 | [Remote workers](guides/remote-workers.md) | Outbound worker join flow 및 remote tool usage |
| 생성 file 공유 | [File links](guides/file-links.md) | TTL과 revoke를 지원하는 tokenized download URL |
| deployment hardening | [Security](security.md) | Isolation, OAuth, workspace scope, audit logs |

## 주요 tool family

| Family | 예 | 용도 |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Build, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection 및 precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Review 가능한 source-control workflow |
| Sessions 및 Goal | `session_manage`, `plan_manage` | durable task handoff, progress report, optional Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI check, screenshot, rendered docs, page text |
| File links | `link_create`, `link_revoke` | Chat에서 generated artifacts 다운로드 |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | NAT, firewall 또는 cluster login flow 뒤의 machine |

## 대표 workflow

### 웹 작업공간에서 코딩하기

1. LSM 컨트롤러와 선택적 [unified web workspace](getting-started/web-workspace.md)를 시작합니다.
2. `/ui`를 열고 LSM ID를 사용하여 로그인합니다.
3. 모델 엔드포인트를 구성하고 새 대화를 엽니다.
4. 모델에 저장소를 검사하고 읽기 전용 검사를 먼저 실행하도록 요청하세요.
5. 승인되면 file patch, tests, diff review, commit, push를 수행하게 합니다.
6. File link 또는 remote system이 관련된 task에서는 audit log를 확인합니다.

### Remote HPC 또는 accelerator host

1. 일회성 remote worker invite를 만듭니다.
2. 생성 command를 remote host에 붙여넣습니다.
3. 일반 tools에 `machine`을 사용하고 Git은 `run_shell`, path transfer는 `remote_transfer`를 사용합니다.
4. Task 후 worker를 revoke합니다.

### Artifact generation

1. AI가 `/workspace` 아래에 file을 생성하도록 합니다.
2. TTL/download limit가 있는 tokenized file link를 만듭니다.
3. Link를 chat에 공유합니다.
4. 완료되면 revoke합니다.

## 언어

이 site는 native MkDocs i18n plugin으로 build됩니다. Header의 language selector로 English와 translated pages를 전환합니다. 번역이 없는 page는 English로 fallback됩니다.
