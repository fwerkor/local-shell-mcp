<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# 네트워크 연결

머신 외부의 HTTP MCP client가 연결하려면 접근 가능한 HTTPS origin이 필요합니다. 이 페이지는 네트워크 라우팅을 설명하며 어떤 runtime을 선택할지는 다루지 않습니다.

client endpoint는 보통 `/mcp`로 끝납니다.

```text
https://your-public-host.example.com/mcp
```

서버의 public base URL 설정에는 origin만 넣습니다.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

이 base URL에 `/mcp`를 포함하지 마십시오.

## 연결 옵션

**권장:** 공개 접속에는 공인 서버에 직접 배포하거나 HTTPS 역방향 프록시를 통해 공인 서버에서 트래픽을 전달하세요.

**비권장:** Cloudflare Tunnel은 클라이언트 측 업로드 속도가 매우 느릴 수 있어 파일 업로드와 전송 기능을 사용하기 어려울 수 있습니다. 공인 서버 배포나 전달이 불가능할 때만 사용하세요.


| 옵션 | 사용 시점 |
|---|---|
| Caddy | 간단한 자동 TLS가 필요할 때 |
| Nginx 또는 Nginx Proxy Manager | 기존 Nginx 인프라가 있을 때 |
| Traefik | 기존 container-native 라우팅을 사용할 때 |
| 공인 서버를 통한 전달 | 공개 접속에는 공인 서버에 직접 배포하거나 HTTPS 역방향 프록시를 통해 공인 서버에서 트래픽을 전달하세요. |
| Cloudflare Tunnel(비권장) | 공인 서버를 통해 전달하고 Cloudflare Tunnel은 최후의 수단으로 사용 |

## 경로

전체 origin을 실행 중인 서버로 전달하십시오. 중요한 경로는 다음과 같습니다.

| 경로 | 용도 |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | 상태 확인 |
| `/.well-known/...` | client discovery metadata |
| `/oauth/...` | client 인증 흐름 |
| `/downloads/...` | 선택적 생성 파일 링크 |
| `/join/...`, `/remote/...` | 선택적 remote-worker 흐름 |

## 프록시 동작

프록시는 경로를 보존하고 request body를 전달하며 긴 response를 지원하고 지나치게 짧은 timeout을 피해야 합니다.

## 확인

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## 흔한 실수

| 실수 | 해결 |
|---|---|
| ChatGPT에서 `https://host/mcp` 대신 `https://host` 사용 | client endpoint에만 `/mcp` 추가 |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` 설정 | origin만 설정 |
| `/mcp`만 라우팅 | discovery 및 인증 경로도 작동하도록 전체 origin 라우팅 |
| host runtime에서 너무 넓은 workspace 사용 | 좁은 workspace 또는 Docker 사용 |

## 권장 조합

| Runtime | 네트워크 패턴 |
|---|---|
| 서버의 Docker Compose | HTTPS 역방향 프록시 |
| 가정용 머신의 Docker Compose | 공인 서버를 통해 전달하고 Cloudflare Tunnel은 최후의 수단으로 사용 |
| 노트북의 VS Code extension | 공인 서버를 통한 전달 |
| VM의 binary | VM 또는 네트워크 경계의 reverse proxy |
| Python/source 개발 서버 | 보통 localhost 전용 |
| Stdio mode | HTTP 경로 없음. 로컬 MCP client 사용 |
