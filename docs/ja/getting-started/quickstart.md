# クイックスタート

リポジトリを clone し、.env.example をコピーし、公開 HTTPS URL、OAuth PIN、JWT secret を設定して Docker Compose で起動します。

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

公開環境では OAuth を必ず有効にし、Docker socket、ホスト root、長期認証情報をマウントしないでください。
