# 자주 묻는 질문

이 페이지는 LSM 서버가 정상이어도 장애처럼 보일 수 있는 반복적인 Client 및 역방향 프록시 문제를 정리합니다.

## LSM 업그레이드 후 ChatGPT에서 일부 도구를 사용할 수 없는 이유는 무엇입니까?

### 증상

- 새 도구가 ChatGPT에 표시되지 않습니다.
- ChatGPT가 삭제, 이름 변경 또는 통합된 이전 도구를 계속 호출합니다.
- 도구는 존재하지만 ChatGPT가 이전 입력 스키마를 보내 검증에 실패합니다.
- LSM을 재시작하거나 새 대화를 열어도 해결되지 않습니다.

### 원인

ChatGPT는 MCP App이 스캔, 승인 또는 게시될 때 사용 가능했던 도구와 입력 스키마의 고정 스냅샷을 보관할 수 있습니다. LSM 릴리스에서 `tools/list`가 변경되어도 저장된 스냅샷이 자동으로 갱신된다는 보장은 없습니다. 공개된 만료 시간이 있는 단기 캐시가 아닙니다.

### 해결 방법

=== "개발자 모드 또는 개인 연결"

    1. **ChatGPT Settings → Apps**를 엽니다.
    2. LSM App을 열고 **Refresh**로 도구를 다시 스캔합니다.
    3. Refresh가 없으면 기존 App을 삭제하고 동일한 MCP 엔드포인트를 다시 추가합니다.
    4. 새 도구 목록을 승인한 후 새 대화를 시작합니다.

=== "ChatGPT Business에 게시된 App"

    현재 게시된 사용자 지정 App은 도구나 메타데이터를 제자리에서 갱신할 수 없습니다. 워크스페이스 관리자가 새 App을 만들고 현재 LSM 엔드포인트를 스캔하여 게시한 뒤 이전 App을 폐기해야 합니다.

=== "ChatGPT Enterprise 또는 Edu"

    워크스페이스 관리자는 **Workspace Settings → Apps → LSM App → … → Action control → Refresh**에서 차이를 검토하고 필요한 새 action을 활성화할 수 있습니다.

[Issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70)과 [OpenAI MCP App 문서](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)를 참고하십시오.

## Nginx 뒤에서 WebUI가 계속 재연결되는 이유는 무엇입니까?

### 증상

- WebUI 페이지와 OAuth 로그인은 정상적으로 열립니다.
- TUI가 나타나지 않습니다.
- 상태가 `Connecting`, `Connection error`, `Reconnecting` 사이에서 반복됩니다.
- 포트 `8765`에 직접 연결하면 작동합니다.

### 원인

브라우저 UI는 PTY WebSocket을 통해 네이티브 TUI를 렌더링합니다. 기본 엔드포인트는 `/ui/ws`이며 사용자 지정 `ui_path`를 사용하면 `${ui_path}/ws`입니다. 일반 Nginx `proxy_pass`는 WebSocket 업그레이드에 필요한 hop-by-hop 헤더를 자동으로 전달하지 않습니다.

### 해결 방법

HTTP/1.1을 사용하고 `Upgrade` 및 `Connection` 헤더를 전달합니다.

```nginx
# map은 http 블록에 배치합니다.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

설정을 수정한 후 Nginx를 검사하고 다시 로드합니다.

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Nginx Proxy Manager에서는 Proxy Host의 **Websockets Support**를 활성화하십시오. 계속 재연결되면 Advanced 설정에 동일한 업그레이드 헤더를 추가하십시오.

### 확인

브라우저 개발자 도구에서 WebUI를 다시 로드하고 `/ui/ws` 요청을 확인합니다. 정상 연결은 다음을 반환합니다.

```text
101 Switching Protocols
```

[Issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71)을 참고하십시오.
