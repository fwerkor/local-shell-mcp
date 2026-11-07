<!-- i18n-source-sha256: d699e8855ee01b72db68087e8a5d8f3957c702641e7e6956f268604b8b1f9d2b -->
# Runtime 선택과 deployment 모델

`local-shell-mcp`에는 두 가지 보완적인 결정이 있습니다.

1. **Runtime**: server process를 어떻게 실행하고 어떤 workspace를 제어할지.
2. **인터페이스**: [unified web workspace](../getting-started/web-workspace.md) 옵션을 사용하거나 Gemini 또는 ChatGPT와 같은 외부 MCP 클라이언트를 연결하세요.

권장되는 일일 인터페이스는 자체 호스팅 웹 작업 공간(채팅, 프로젝트 및 LSM 제어 페이지)입니다. 컨트롤러와 별도로 배포됩니다. Docker, VS Code 확장, 릴리스 바이너리, Python 설치 및 stdio 모드는 컨트롤러를 실행하는 방법입니다. 외부 채팅 앱은 선택적인 클라이언트로 남아 있습니다.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose 로컬 HTTP 전용 통합 웹 작업공간
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

일반적인 자체 호스팅 설정은 다음과 같습니다.

```text
브라우저 -> https://chat.example.com (통합 웹 작업공간)
        -> 인증된 local-shell-mcp 컨트롤러
        -> 통제된 작업 공간 및 아웃바운드 근로자
선택적 외부 클라이언트 -> https://mcp.example.com/mcp
```

local MCP client setup은 더 단순할 수 있습니다:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**권장:** 공개 접속에는 공인 서버에 직접 배포하거나 HTTPS 역방향 프록시를 통해 공인 서버에서 트래픽을 전달하세요. **비권장:** Cloudflare Tunnel은 클라이언트 측 업로드 속도가 매우 느릴 수 있어 파일 업로드와 전송 기능을 사용하기 어려울 수 있습니다. 공인 서버 배포나 전달이 불가능할 때만 사용하세요. ([Public HTTPS exposure](../clients/connectivity.md))

## Runtime 선택 매트릭스

| 런타임 | 다음에 가장 적합 | 격리 경계 | 툴체인 소스 | 외부 MCP 액세스 | 페이지 |
|---|---|---|---|---|---|
| 도커 작성 | 대부분의 코딩 에이전트 작업 부하 및 반복 가능한 작업 공간 | 컨테이너 | 린 컨트롤러 이미지; 작업별 툴체인을 별도로 설치 | HTTPS 프록시 또는 터널 추가 | [Docker Compose](../installation/docker.md) |
| Docker Compose + 터널 사이드카 | 비권장: 공인 서버를 통해 전달하고 Cloudflare Tunnel은 최후의 수단으로 사용 | 컨테이너 | 프로젝트 이미지 | 공인 서버를 통해 전달하고 Cloudflare Tunnel은 최후의 수단으로 사용 | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | editor workspace에서 server 시작/중지 | 대개 host process | host tools와 설정된 executable | ChatGPT용 외부 HTTPS tunnel/proxy 추가 | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Docker를 사용할 수 없는 host/VM | Host or VM | host tools와 설정된 executable | HTTPS proxy 또는 tunnel 추가 | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Python-native 사용, debug, development | Host virtualenv or VM | Python package와 host tools | HTTPS proxy 또는 tunnel 추가 | [Python install](../installation/python.md) |
| Stdio mode | tool process를 직접 spawn하는 local MCP client | Client process boundary | host tools와 설정된 executable | ChatGPT web/app에서는 사용 불가 | [Stdio mode](../installation/stdio.md) |

## Client 연결 매트릭스

| 인터페이스 | 공개 HTTPS가 필요합니다 | `/mcp`를 사용합니다. | OAuth 필요 | 일반적인 런타임 |
|---|---:|---:|---:|---|
| 통합 LSM 웹 작업공간 | 예, 원격 액세스의 경우입니다. 로컬 프록시도 가능 | 내부적으로 | LSM 로그인 | 컨트롤러와 별도의 웹 스택 |
| Gemini Spark / 맞춤형 앱 | 예 | 예 | 네, 공용으로 사용하세요 | 모든 HTTP 컨트롤러 |
| ChatGPT custom MCP connector | 예 | 예 | public 사용 시 예 | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | 아니요 | 아니요 | 아니요 | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | localhost는 보통 아니요, 네트워크에서는 예 | 예 | localhost 밖에서는 권장 | Any HTTP runtime |
| VS Code extension helper flow | ChatGPT 연결 시에만 | ChatGPT URL copy 시 예 | ChatGPT에서는 권장 | VS Code-launched runtime |

[unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) 및 [network connectivity](../clients/connectivity.md)를 참조하세요.

## 각 runtime이 제어하는 것

모든 runtime은 동일한 server code를 실행하고, 활성화된 경우 동일한 MCP tool family를 제공합니다:

- Shell 및 persistent shell sessions.
- Filesystem, search, patch tools.
- Git operations.
- Playwright 기반 browser automation.
- Audit log 및 task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle 및 machine-routed tools.

차이는 추상 API가 아니라 그 뒤의 **operating environment**입니다.

| 질문 | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Command 실행 위치? | container 내부 | 대개 host workspace | host 또는 VM process environment |
| Default workspace? | Mounted `/workspace` | 현재 VS Code folder 또는 설정 path | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| 컴파일러와 브라우저가 사전 설치되어 있습니까? | 아니요; 작업에 필요한 것을 설치하십시오. | 호스트에 설치된 경우에만 | 호스트에 설치된 경우에만 |
| Reset이 쉬운가? | container와 workspace volume 재생성 | workspace에 따라 다름 | host/VM에 따라 다름 |
| 임의 package install에 적합? | disposable이면 예 | host에서는 위험 증가 | VM이 아니면 위험 증가 |

## 권장 선택

특별한 이유가 없는 한 **Docker Compose**를 먼저 사용하세요. 사전 설치된 대규모 개발 툴체인 없이도 명확한 안전 경계를 제공합니다.

워크플로가 편집기에서 시작되고 로컬 실행 프로그램이 필요한 경우 **VS Code 확장**을 사용하세요. 아직은 런타임입니다. 원격 웹 클라이언트에는 연결 가능한 HTTPS 프록시 또는 터널이 필요합니다.

Docker를 사용할 수 없지만 VM/container host/dedicated user account가 boundary를 제공한다면 **standalone binary**를 사용하십시오.

`local-shell-mcp` 자체 development/debug 또는 Python-based environment 관리가 더 쉽다면 **`pipx` 또는 source install**을 사용하십시오.

server process를 spawn할 수 있는 local MCP client에만 **stdio mode**를 사용하십시오. public deployment가 아니며 ChatGPT web/app에서 직접 사용할 수 없습니다.

## Public endpoint 규칙

Gemini 및 ChatGPT와 같은 외부 HTTP MCP 클라이언트의 경우 MCP 끝점은 다음과 같습니다.

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL`은 origin만 지정합니다:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL`에 `/mcp`를 붙이지 마십시오.

## Runtime 페이지

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Client 페이지

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
