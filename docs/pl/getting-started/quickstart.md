# Szybki start

Sklonuj repozytorium, skopiuj .env.example, ustaw publiczny URL HTTPS, OAuth PIN i JWT secret, a potem uruchom Docker Compose.

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

For public ChatGPT access, expose HTTPS and set:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

W publicznych wdrożeniach włącz OAuth i nie montuj Docker socket, katalogu głównego hosta ani długotrwałych poświadczeń.
