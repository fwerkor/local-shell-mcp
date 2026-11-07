<!-- i18n-source-sha256: 670ede6656fe032f81c54057c27df5536ac478338889455a2dbc76d4c9b36fd7 -->
# Docker Compose runtime

Docker Compose は隔離コンテナー向けの代替手段です。**ソースからの直接デプロイを推奨**します。[Python/ソースのガイド](python.md)を参照してください。

これは runtime の選択です。ChatGPT、generic HTTP MCP client に接続することも、local testing のみに使うこともできます。

## Docker image に含まれるもの

イメージは python:3.12-slim ベースで、最低限の実行ツールのみを含みます。開発ツールチェーン、Playwright/ブラウザー、オフィスソフトはプリインストールされません。

含まれる category：

| Category | 例 |
|---|---|
| Shell と inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git と credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | 未搭載。必要に応じて追加 |
| Python | Python 3.12, pip, virtualenv |
| JavaScript/TypeScript | 未搭載。必要に応じて追加 |
| その他の言語 | 未搭載。必要に応じて追加 |
| Browser automation | 未搭載。必要に応じて追加 |
| Document tooling | 未搭載。必要に応じて追加 |

正確な image content は convenience layer であり stable API ではありません。Project-specific dependencies は workspace または project build scripts に置いてください。

## 基本 local run

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

生の CLI トークンはホスト所有の `.env`（モード `0600`）にのみ保存されます。Compose がコンテナへ渡すのは SHA-256 verifier だけです。これにより `lsm call` は Docker の公開ポートブリッジ越しに認証でき、コンテナ内の管理対象 shell プロセスへ再利用可能な高権限トークンを公開しません。

Default Compose file は service を localhost に bind します：

```text
127.0.0.1:8765 -> container:8765
```

これは local testing、および同じ host 上の reverse proxy に適しています。

## Workspace layout

Default Compose runtime は次を mount します：

| Host path / volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Tools から見える controlled workspace |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Trust boundary ごとに 1 workspace directory を使ってください。便利だからという理由で home directory 全体を mount しないでください。

## 必須の public settings

ChatGPT または public HTTP MCP client 用に `.env` を設定します：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

JWT secret は次のような command で生成できます：

```bash
openssl rand -hex 32
```

Public MCP URL：

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

**非推奨:** Cloudflare Tunnel はクライアント側のアップロード速度が非常に遅くなる場合があり、ファイルのアップロードや転送が実用的でなくなります。公開サーバーや転送経路を用意できない場合のみ使用してください。 公開アクセスには、公開サーバーへの直接デプロイ、または公開サーバー経由の転送と HTTPS リバースプロキシを使用してください。 ([network connectivity](../clients/connectivity.md))

Compose file には `tunnel` profile の optional `cloudflared` service が含まれます。Tunnel を MCP server と並べて実行します。

`.env` を設定します：

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

両方の service を開始します：

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust では public hostname を次へ route します：

```text
http://local-shell-mcp:8765
```

これは Cloudflare Tunnel であり Cloudflare Access ではありません。ChatGPT 用 OAuth は引き続き `local-shell-mcp` が処理します。
公開 port が localhost に制限されるため、Compose service は forwarded headers を信頼します。これにより OAuth PIN rate limiting で public caller address を保持できます。Container port を直接公開する場合は `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` を trusted reverse proxy の明示的 address に置き換えてください。

## Tunnel sidecar なしの reverse proxy

**推奨:** 公開アクセスには、公開サーバーへの直接デプロイ、または公開サーバー経由の転送と HTTPS リバースプロキシを使用してください。
既に Caddy、Nginx、Traefik、Nginx Proxy Manager を使っているなら通常の Compose service を維持し、HTTPS を次へ forward します：

```text
http://127.0.0.1:8765
```

Proxy は path を削らず次の routes を forward する必要があります：

| Route | Purpose |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | OAuth resource metadata |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata |
| `/oauth/register` | Dynamic client registration |
| `/oauth/authorize` | Browser authorization page |
| `/oauth/token` | Token exchange |
| `/downloads/<token>` | Optional generated file downloads |
| `/join/<token>`, `/remote/*` | Optional remote-worker bootstrap / polling |

Proxy behavior の要件は [network connectivity](../clients/connectivity.md) を参照してください。

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` は filesystem operation を workspace 内に制限します。より安全な default です。

Container を意図的に disposable とし、model が container filesystem 全体を操作する想定の場合のみ `true` にします。有効化すると built-in command/path denylist restrictions が解除されます。

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Laptop 上で直接動く VS Code extension や binary のような host-launched runtime では full-container mode を有効にしないでください。

## Credentials

Docker runtime は一般的な developer credentials を dedicated volume に永続化できます。GitHub CLI login、Git HTTPS credential helpers、`.netrc`、SSH config、GPG state に便利です。

Credential volume は sensitive として扱ってください。Repository-scoped deploy key、fine-grained token、short-lived credential を優先し、model が自由に読める workspace に broad personal credential を置かないでください。

SSH agent socket を mount して SSH-agent forwarding もできますが、container から active agent への trust を拡張します。Exposure を理解している場合のみ使用してください。

## 更新

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Tunnel sidecar を使う場合：

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Upgrade 後は client にまず read-only check を依頼します：

```text
local-shell-mcp を使用してください。environment_get を呼び、workspace root に対して file_list を実行してください。ファイルは変更しないでください。
```

## Troubleshooting

| 症状 | 確認項目 |
|---|---|
| `/healthz` が local で失敗 | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT が tools を discover できない | Public URL は `/mcp` で終わり、`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` には `/mcp` を含めない |
| OAuth page が失敗 | Public OAuth deployment では admin PIN と JWT secret を設定 |
| Tools から files が見えない | 意図した host directory が `/workspace` に mount されているか確認 |
| Browser tools が失敗 | Playwright image が current か確認し、target browser に `run_shell` を試す |
| Git auth が消えた | Credential volume と、再作成した container が同じ volume を使っているか確認 |
