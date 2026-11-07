<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# クイックスタート

このガイドでは、LSM コントローラーを起動し、そのブラウザー インターフェイスを開きます。 [unified web workspace](web-workspace.md) は、毎日の推奨エクスペリエンスです。これは、個別にデプロイされるオプションのチャット スタックです。 ChatGPT、Gemini、およびその他の外部 MCP クライアントは、同じコントローラーに接続できます。 [runtime choices and deployment model](../guides/deployment.md)を参照してください。

Controller は隔離された環境で**ソースコードから直接デプロイ**する方法を推奨します。Docker Compose は代替手段です。

## 要件

- Git、Python 3.11 以降と `venv` / `pip`。
- 外部 MCP クライアントやリモート利用者が接続する場合のみ公開 HTTPS。
- 権限を制限した専用ワークスペース。
- 強力な OAuth 管理者 PIN とランダムな JWT シークレット。

!!! warning
    接続されたモデルは設定済み workspace を操作できます。使い捨て container または VM でサービスを実行し、host-control resources を mount しないでください。

## 1. clone と設定

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

`.env` のサンプル PIN と JWT シークレットを変更します（`openssl rand -hex 32` を使用）。ソースから実行する場合、`.env` は自動読み込みされません。

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. サーバーを起動

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

別のターミナルで状態を確認します：

```bash
curl -i http://127.0.0.1:8765/healthz
```

正常なら HTTP `200` が返ります。常駐にはサービスマネージャーを使用してください。

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

ソースを更新し、editable パッケージを再インストールして Controller を再起動します：

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Docker Compose を使用する場合はコンテナーを更新します：

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
