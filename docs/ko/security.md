# 보안

공개 배포에서는 OAuth 를 활성화하고 Docker socket, 호스트 루트, 장기 자격 증명을 마운트하지 마십시오.

Mandatory rules:

1. Keep OAuth enabled for public deployments.
2. Do not mount `/var/run/docker.sock`.
3. Do not mount the host root filesystem.
4. Do not expose unauthenticated MCP tools on the public internet.
5. Treat file links and credential volumes as sensitive.
6. Use disposable containers or VMs when granting broad authority.
