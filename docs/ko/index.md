# local-shell-mcp 한국어 문서

ChatGPT Developer Mode 및 다른 MCP 클라이언트를 위한 로컬 제어 평면입니다. 제어된 작업공간, shell, 파일, Git, 브라우저 자동화, 파일 링크, 원격 워커를 MCP 도구로 제공합니다.

## Documentation paths

- [빠른 시작](getting-started/quickstart.md)
- [ChatGPT 커넥터](getting-started/chatgpt-connector.md)
- [원격 워커](guides/remote-workers.md)
- [보안](security.md)
- [문제 해결](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

공개 배포에서는 OAuth 를 활성화하고 Docker socket, 호스트 루트, 장기 자격 증명을 마운트하지 마십시오.
