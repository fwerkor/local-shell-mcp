<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# 빠른 시작

이 가이드는 LSM 컨트롤러를 시작하고 해당 브라우저 인터페이스를 엽니다. [unified web workspace](web-workspace.md)는 권장되는 일일 경험입니다. 이는 별도로 배포된 선택적 채팅 스택입니다. ChatGPT, Gemini 및 기타 외부 MCP 클라이언트는 동일한 컨트롤러에 연결할 수 있습니다. [runtime choices and deployment model](../guides/deployment.md)를 참조하세요.

격리된 환경에서 **소스 체크아웃으로 직접 배포**하는 방식을 권장합니다. Docker Compose는 대안입니다.

## 요구 사항

- Git, Python 3.11 이상 및 `venv` / `pip`.
- 원격 사용자나 외부 MCP 클라이언트가 필요할 때만 공개 HTTPS.
- 권한을 제한한 전용 작업 공간.
- 강력한 OAuth 관리자 PIN과 임의 JWT 비밀키.

!!! warning
    연결된 모델은 구성된 workspace를 조작할 수 있습니다. 일회용 container 또는 VM에서 서비스를 실행하고 host-control resources를 mount하지 마십시오.

## 1. clone 및 구성

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

`.env`에서 샘플 PIN과 JWT 비밀키를 교체하세요 (`openssl rand -hex 32`). 소스 실행 시 `.env`가 자동 로드되지 않습니다.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. 서버 시작

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

별도의 터미널에서 상태 확인:

```bash
curl -i http://127.0.0.1:8765/healthz
```

정상이면 HTTP `200`이 반환됩니다. 장기 실행은 서비스 관리자를 사용하세요.

## 3. HTTPS 공개

원격 액세스는 공용 서버 또는 HTTPS 역방향 프록시(Caddy, Nginx, Traefik)를 사용하고 업로드와 다운로드를 포함한 전체 사이트를 다음으로 전달하세요:

```text
http://127.0.0.1:8765
```

HTTPS 연결 확인:

```bash
curl -i https://your-public-host.example.com/healthz
```

파일 전송에는 **Cloudflare Tunnel을 권장하지 않습니다**. 클라이언트 업로드가 느릴 수 있습니다. 가능하면 공용 서버나 일반 역방향 프록시를 사용하고 OAuth를 유지하세요. Docker: [안내](../installation/docker.md).

## 4. 브라우저 작업 공간을 엽니다

컨트롤러 로그인을 엽니다.

```text
https://your-public-host.example.com/ui
```

채팅, 프로젝트, 통합 제어 페이지는 [unified web workspace guide](web-workspace.md)를 따르세요. 원래의 경량 WebUI는 채팅이 설치되지 않은 경우에도 사용할 수 있습니다.

## 5. 안전하게 tool access 확인

모델에 다음과 같이 요청합니다:

```text
local-shell-mcp를 사용하세요. 먼저 environment_get를 호출한 다음 workspace root를 나열하세요. 아직 파일을 수정하지 마세요.
```

예상되는 read-only tools:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. 범위가 제한된 coding task로 시작

좋은 첫 task 예시:

```text
이 repository를 검사하고 project layout을 요약하세요. 명확한 기존 test suite가 있다면 실행하되 파일은 변경하지 마세요.
```

연결이 확인되면 더 구체적인 지시를 제공합니다:

```text
실패한 test를 수정하세요. 먼저 관련 파일을 읽고 최소한의 patch를 만든 뒤 대상 test를 실행하고 git diff를 보여 주세요. 승인할 때까지 commit하지 마세요.
```

## 업데이트

소스를 업데이트하고 editable 패키지를 다시 설치한 후 Controller를 재시작하세요:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Docker Compose 배포라면 컨테이너를 업데이트하세요:

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## 다음 페이지

| 목적 | 페이지 |
|---|---|
| runtime과 client 선택 이해 | [Runtime 선택 및 deployment 모델](../guides/deployment.md) |
| Docker Compose로 실행 | [Docker Compose runtime](../installation/docker.md) |
| VS Code에서 실행 | [VS Code extension runtime](../installation/vscode-extension.md) |
| release binary로 실행 | [Standalone binary runtime](../installation/binary.md) |
| Python 또는 source checkout으로 실행 | [Python runtimes](../installation/python.md) |
| 통합 채팅 및 제어 인터페이스 사용 | [Unified web workspace](web-workspace.md) |
| Gemini Spark를 클라이언트로 추가 | [Gemini Custom Apps](gemini-spark.md) |
| ChatGPT를 client로 추가 | [ChatGPT connector](chatgpt-connector.md) |
| tool 선택과 더 나은 prompt 작성 | [Usage patterns](../guides/usage-patterns.md) |
| HPC, NPU/GPU 또는 NAT machine 연결 | [Remote workers](../guides/remote-workers.md) |
| 모든 MCP tool 이해 | [Tools reference](../reference/tools.md) |
