# local-shell-mcp 문서

ChatGPT Developer Mode와 다른 MCP 클라이언트를 위한 로컬 제어 평면입니다. 제어된 워크스페이스, shell, 파일, Git, 브라우저 자동화, 파일 링크, 원격 worker를 MCP 도구로 노출합니다.

## 문서 경로

- [빠른 시작](getting-started/quickstart.md)
- [ChatGPT 커넥터](getting-started/chatgpt-connector.md)
- [원격 worker](guides/remote-workers.md)
- [보안](security.md)
- [문제 해결](troubleshooting.md)

## 핵심 아키텍처

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## 핵심 안전 규칙

공개 배포에서는 OAuth를 활성화하고 Docker socket, 호스트 루트, 장기 자격 증명을 마운트하지 마십시오.
