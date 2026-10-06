<!-- i18n-source-sha256: 81fe33aa286565e6436467d117cc77d94ec91671e33e559a6bb888223d0c8bc1 -->
# 빠른 시작

이 가이드는 첫 runtime으로 Docker Compose를, 첫 client로 ChatGPT를 사용합니다. 두 선택은 서로 독립적입니다. Docker, VS Code extension, binary, Python, stdio는 runtime 옵션이고 ChatGPT와 일반 MCP client는 client 옵션입니다. 전체 구조는 [runtime 선택 및 deployment 모델](../guides/deployment.md)을 참조하십시오.

## 요구 사항

- Compose v2가 포함된 Docker Engine.
- ChatGPT가 웹에서 연결해야 한다면 공개 HTTPS endpoint.
- 전용 workspace directory.
- 충분히 긴 임의의 OAuth admin PIN과 JWT secret.

!!! warning
    연결된 모델은 구성된 workspace를 조작할 수 있습니다. 일회용 container 또는 VM에서 서비스를 실행하고 host-control resources를 mount하지 마십시오.

## 1. clone 및 구성

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import hashlib,secrets; p=Path(".env"); s=p.read_text(); t=secrets.token_urlsafe(48); s=s.replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=" + t, 1).replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=" + hashlib.sha256(t.encode()).hexdigest(), 1); p.write_text(s)'
chmod 600 .env
```

`.env`를 편집합니다:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. 서버 시작

```bash
mkdir -p workspaces/default
docker compose up -d
```

상태를 확인합니다:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

정상 응답은 HTTP `200`을 반환합니다.

## 3. HTTPS 공개

Cloudflare Tunnel sidecar를 사용하는 경우:

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust에서 public hostname의 대상을 다음으로 설정합니다:

```text
http://local-shell-mcp:8765
```

Caddy, Nginx, Traefik, Nginx Proxy Manager 또는 다른 reverse proxy를 사용한다면 HTTPS traffic을 `127.0.0.1:8765` 또는 container network address로 전달합니다.

## 4. ChatGPT 연결

다음 MCP endpoint를 사용합니다:

```text
https://your-public-host.example.com/mcp
```

[ChatGPT connector 가이드](chatgpt-connector.md)를 따라 OAuth와 tool approval을 완료합니다.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

tunnel profile을 사용한다면:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
| ChatGPT를 client로 추가 | [ChatGPT connector](chatgpt-connector.md) |
| tool 선택과 더 나은 prompt 작성 | [Usage patterns](../guides/usage-patterns.md) |
| HPC, NPU/GPU 또는 NAT machine 연결 | [Remote workers](../guides/remote-workers.md) |
| 모든 MCP tool 이해 | [Tools reference](../reference/tools.md) |
