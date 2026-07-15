# stdio 모드

이 페이지는 “stdio 모드” 시나리오를 설명하며 문서 사이트의 공통 Runtime/Client 구조를 따릅니다.

## 개요

Runtime은 서버 프로세스가 어떻게 실행되고 어떤 워크스페이스를 제어하는지 정합니다. Client는 ChatGPT 또는 다른 MCP 클라이언트가 어떻게 연결되는지 정합니다. Docker, VS Code 확장, 독립 실행 바이너리, Python/pipx/소스 설치, stdio는 Runtime 선택지입니다. ChatGPT 커넥터, 일반 HTTP MCP 클라이언트, stdio MCP 클라이언트는 Client 연결입니다.

## 사용 시점

- 선택한 Runtime 또는 Client 경로가 이 페이지 제목과 일치할 때 사용합니다.
- 워크스페이스 루트, 공개 base URL, MCP endpoint, 인증 모드, 호스트에서 사용할 수 있는 도구를 일관되게 유지합니다.
- ChatGPT 웹/App에는 `/mcp`로 끝나는 HTTPS MCP endpoint를 노출합니다.
- 로컬 MCP 클라이언트는 지원 범위에 따라 HTTP localhost 또는 `local-shell-mcp --mode stdio`를 사용합니다.

## 단계

1. 먼저 Runtime 설치 페이지를 선택합니다.
2. Runtime을 시작하고 HTTP 모드에서는 `/healthz`를 확인합니다.
3. 그다음 Client 연결 페이지를 선택합니다.
4. Client에 MCP endpoint 또는 stdio 명령을 등록합니다.
5. `environment_info`를 호출해 실제 워크스페이스와 설정을 확인합니다.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## 검증

- `environment_info`는 Runtime 설정과 워크스페이스를 확인합니다.
- `tree_view`는 보이는 파일을 확인합니다.
- `run_shell_tool`은 명령 실행 환경을 확인합니다.

## 참고

작고 검증 가능한 단계, 즉 확인, 편집, diff, 테스트, 스캔, 커밋을 우선합니다. 큰 작업도 감사 가능한 도구 호출로 나눕니다.
