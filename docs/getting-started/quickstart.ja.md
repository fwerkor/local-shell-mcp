<!-- i18n-source-sha256: 51bfe29de540492ab1da2df9479464641bb335796b0538357235fac5b4a2e446 -->
# クイックスタート

このガイドでは最初の runtime として Docker Compose、最初の client として ChatGPT を使用します。これらは別々の選択です。Docker、VS Code extension、binary、Python、stdio は runtime の選択肢で、ChatGPT と汎用 MCP client は client の選択肢です。全体像は [runtime の選択とデプロイモデル](../guides/deployment.md) を参照してください。

## 要件

- Compose v2 を備えた Docker Engine。
- ChatGPT が Web から接続する場合は公開 HTTPS endpoint。
- 専用の workspace directory。
- 十分に長いランダムな OAuth admin PIN と JWT secret。

!!! warning
    接続されたモデルは設定済み workspace を操作できます。使い捨て container または VM でサービスを実行し、host-control resources を mount しないでください。

## 1. clone と設定

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
```

`.env` を編集します：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. サーバーを起動

```bash
mkdir -p workspaces/default
docker compose up -d
```

状態を確認します：

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

正常な応答は HTTP `200` を返します。

## 3. HTTPS で公開

Cloudflare Tunnel sidecar を使う場合：

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust で public hostname の転送先を次に設定します：

```text
http://local-shell-mcp:8765
```

Caddy、Nginx、Traefik、Nginx Proxy Manager などの reverse proxy では、HTTPS traffic を `127.0.0.1:8765` または container network address に転送します。

## 4. ChatGPT を接続

次の MCP endpoint を使います：

```text
https://your-public-host.example.com/mcp
```

[ChatGPT connector ガイド](chatgpt-connector.md) に従って OAuth と tool approval を完了します。

## 5. 安全に tool access を確認

モデルに次のように依頼します：

```text
local-shell-mcp を使用してください。まず environment_get を呼び出し、その後 workspace root を一覧してください。まだファイルを変更しないでください。
```

想定される read-only tools：

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. 範囲を限定した coding task から開始

最初の task の例：

```text
この repository を調べて project layout を要約し、明らかな既存 test suite があれば実行してください。ファイルは変更しないでください。
```

接続確認後は、より具体的な指示を与えます：

```text
失敗している test を修正してください。まず関連ファイルを読み、最小限の patch を作成し、対象 test を実行してから git diff を表示してください。承認するまで commit しないでください。
```

## 更新

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

tunnel profile を使っている場合：

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

## 次に読むページ

| 目的 | ページ |
|---|---|
| runtime と client の選択を理解する | [Runtime の選択とデプロイモデル](../guides/deployment.md) |
| Docker Compose で実行する | [Docker Compose runtime](../installation/docker.md) |
| VS Code から実行する | [VS Code extension runtime](../installation/vscode-extension.md) |
| release binary で実行する | [Standalone binary runtime](../installation/binary.md) |
| Python または source checkout で実行する | [Python runtimes](../installation/python.md) |
| ChatGPT を client として追加する | [ChatGPT connector](chatgpt-connector.md) |
| tool を選び、より良い prompt を書く | [Usage patterns](../guides/usage-patterns.md) |
| HPC、NPU/GPU、NAT machine を接続する | [Remote workers](../guides/remote-workers.md) |
| すべての MCP tool を理解する | [Tools reference](../reference/tools.md) |
