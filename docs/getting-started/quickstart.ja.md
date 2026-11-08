<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# クイックスタート

このガイドでは、LSM コントローラーを起動し、そのブラウザー インターフェイスを開きます。 [unified web workspace](web-workspace.md) は、毎日の推奨エクスペリエンスです。これは、個別にデプロイされるオプションのチャット スタックです。 ChatGPT、Gemini、およびその他の外部 MCP クライアントは、同じコントローラーに接続できます。 [runtime choices and deployment model](../guides/deployment.md)を参照してください。

[GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) の **Controller 単一実行ファイル**によるデプロイを推奨します。Python、Docker、ソース checkout は不要です。例は **Linux x86_64** 用です。その他は [バイナリガイド](../installation/binary.md) を参照してください。

## 要件

- 対応するリリース実行ファイルと `curl`（Linux x86_64 の例）。
- リモート利用者や外部 MCP クライアントが必要な場合のみ公開 HTTPS。
- 専用で権限を制限したワークスペース。
- 強い OAuth 管理 PIN とランダムな JWT 秘密鍵。

!!! warning
    接続されたモデルは設定済み workspace を操作できます。使い捨て container または VM でサービスを実行し、host-control resources を mount しないでください。

## 1. 実行ファイルの取得と設定

単一ファイルをダウンロードし JWT 秘密鍵を生成します：

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

`.env` を作成し、サンプル PIN と JWT 秘密鍵を変更します（`openssl rand -hex 32` を使用）。バイナリは `.env` を**自動読み込みしません**。

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. サーバーを起動

ダウンロードした実行ファイルを直接起動します：

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

別のターミナルで状態を確認します：

```bash
curl -i http://127.0.0.1:8765/healthz
```

正常な応答は HTTP `200` です。常駐には制限されたアカウントとサービスマネージャーを使用してください。

## 3. HTTPS で公開

リモートアクセスには公開サーバーまたは HTTPS リバースプロキシ（Caddy、Nginx、Traefik）を使い、アップロードとダウンロードを含むサイト全体を転送します：

```text
http://127.0.0.1:8765
```

HTTPS を確認します：

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel は推奨しません**。クライアントからのアップロードが遅く、ファイル転送を妨げる場合があります。可能であれば公開サーバーまたは通常のリバースプロキシを使用し、OAuth を有効にしてください。Docker: [ガイド](../installation/docker.md)。

## 4. ブラウザのワークスペースを開きます

コントローラーのログインを開きます。

```text
https://your-public-host.example.com/ui
```

チャット、プロジェクト、統合コントロール ページについては、[unified web workspace guide](web-workspace.md) に従ってください。チャットがインストールされていない場合は、独自の軽量 WebUI を使用できます。

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

リリース実行ファイルを入れ替え Controller を再起動します：

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Docker Compose の場合はコンテナーを更新します。ソース版：[Python ガイド](../installation/python.md)。

```bash
docker compose pull
docker compose up -d
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
| 統合されたチャットと制御インターフェイスを使用する | [Unified web workspace](web-workspace.md) |
| Gemini Spark をクライアントとして追加する | [Gemini Custom Apps](gemini-spark.md) |
| ChatGPT を client として追加する | [ChatGPT connector](chatgpt-connector.md) |
| tool を選び、より良い prompt を書く | [Usage patterns](../guides/usage-patterns.md) |
| HPC、NPU/GPU、NAT machine を接続する | [Remote workers](../guides/remote-workers.md) |
| すべての MCP tool を理解する | [Tools reference](../reference/tools.md) |
