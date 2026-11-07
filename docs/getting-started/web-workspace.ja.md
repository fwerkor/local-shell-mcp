<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
# 統合された Web ワークスペース

**統合 LSM Web ワークスペース**は、local-shell-mcp を日常的に使用するための推奨される方法です。これは、ベンダーが提供する修正済みの LibreChat フロントエンドに基づいて、AI チャット、プロジェクト履歴、LSM コントロール プレーンを 1 つの応答性の高いインターフェイスに統合します。 [ChatGPT](chatgpt-connector.md) や [Gemini](gemini-spark.md) などの外部 MCP クライアントには引き続き接続できます。

ワークスペースは **自己ホスト型で、インストールはオプションです**。これは別個の Web サービスであり、最小限のコントローラー イメージ、スタンドアロンの実行可能ファイル、またはリモート ワーカー バンドルの一部ではありません。コントローラーのみの展開では、元のブラウザー UI と OpenTUI が保持されます。

## ワークスペースには何がありますか?

| エリア | できること |
|---|---|
| チャットとプロジェクト | 構成されたモデルを選択し、会話を作成し、プロジェクトを整理し、過去のチャットを検索し、会話をアーカイブします。履歴はサーバーに残ります。 |
| コントローラーの概要 | ヘルス状態、最近のアクティビティ、接続されているマシンを表示します。 |
| ファイル | ローカルまたはリモートのファイルを参照して管理します。 |
| 端子 | コントローラーまたはワーカー上の永続ターミナルを操作します。 |
| デスクトップ | リモート GUI セッションを検査および制御します。 |
| セッション | 耐久性のある LSM タスクとそのライフサイクルを検査します。 |
| リモコン | アウトバウンド ワーカーを接続して管理します。 |
| 監査 | モデル由来のツールアクティビティを検査します。 |
| ネストされた MCP | LSM の背後にある外部 MCP サーバーを登録、編集、有効化、無効化、更新、削除します。 |

コントローラーのルートは、`/control/overview`、`/control/files`、`/control/terminals`、`/control/desktop`、`/control/sessions`、`/control/remotes`、および `/control/audit` です。チャットは `/c/new` で開きます。 LSM MCP マネージャーは **LSM のネストされた MCP レジストリ**を制御します。 LibreChat に 2 番目のレジストリは作成されません。

## オプションのチャットスタックをデプロイする

1. OAuth を使用した [Install and start an LSM Controller](quickstart.md)、適切に分離されたワークスペース、および永続的な `file` または `redis` 状態ストレージ。 Docker Compose をインストールし、Web スタックを実行しているホストにリポジトリのクローンを作成します。
2. **同じサイトに 2 つの HTTPS オリジン** (コントローラーには `https://lsm.example.org`、ワークスペースには `https://chat.example.org` など) を指定します。チャット サービスは、信頼されていないネットワークには直接公開されません。
3. `openssl rand -hex 32` を使用してブリッジ シークレットを 1 つ生成します。そのシークレットを使用して **コントローラー サービス** でこれらの環境変数を構成し、再起動します。

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. リポジトリのチェックアウトで、オプションの Web スタックを構成します。プライベート環境ファイルを使用するか、以下に示す値をエクスポートします。固有の強力なシークレットを生成し、コミットしません。

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. プライベート構成をレンダリングし、個別にデプロイされたチャット スタックを構築して開始します。

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

ルート Docker Compose デプロイメントを使用する場合、上記のコントローラー変数はルート `.env` に属し、コンテナーに転送されます。チャット サービスの値は、シェル エクスポートまたはプライベート環境ファイルを通じて提供できます。コントローラー コンテナーは、指定された Docker ネットワーク上の `http://local-shell-mcp:8765` にあるチャット コンテナーからアクセス可能である必要があります。チャット HTTPS オリジンへのポート `127.0.0.1:3080` をリバース プロキシし、外部ホストを保持し、リポジトリ内の [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) に従います。 Web スタックは Node.js、MongoDB、Meilisearch、SearXNG を実行します。彼らはワーカーには**含まれません**。この個別のデプロイメントは、リポジトリ ルート内のプレーン `docker compose up -d` によって開始されるわけではありません。

## サインインしてチャットを使用する

1. `https://lsm.example.org/ui` を開き、**LSM コントローラー** ログインを使用して認証し、Web ワークスペースへのワンタイム ハンドオフに従います。 2 番目の LibreChat ユーザー アカウントは作成しません。
2. チャット サービス用に使用可能な LLM プロバイダーまたはモデル エンドポイントを構成します。ワークスペースはチャット インターフェイスとツール ブリッジを提供します。 **モデルまたは API クレジットは含まれません**。
3. 会話を作成します。 Web 検索および LSM ツールは、コントローラーの権限に従ってデフォルトで有効になっています。必要に応じて、会話ごとの **Web**、**LSM**、**外部 MCP**、**メモリ** コントロールを使用します。
4. 「コントローラーのステータスを確認し、ワークスペースのルートをリストします。ファイルは変更しないでください。」という読み取り専用リクエストから始めます。
5. **ファイル**、**ターミナル**、**デスクトップ**、**セッション**、**リモート**、または**監査**に移動して、直接検査および制御します。

チャットのアップロード (最大 32 MiB) はコントローラー ワークスペースに保存され、その絶対パスがモデルに提供されます。ブラウザーのアップロードでは、追加のファイル権限は付与されません。モデルに面したツールの呼び出しは、LSM 認証、監査、およびリモート ワーカー ルーターを通過します。

## 外部 MCP、セキュリティ、データ

ワークスペース MCP サイドバーを使用して、ネストされた外部 MCP サーバーを管理します。これは、個別のプライベート環境変数と要求ヘッダーを含む、ローカルの stdio サーバーと HTTP サーバーをサポートします。シークレットはブラウザーに返されません。 **外部 MCP** チャット トグルを使用すると、ネストされたツールの検索、検査、呼び出しが可能になります。ネイティブ LSM ツールが無効になっている場合、モデル `mcp_manage` は付与されません。 UI 管理は、通常のコントローラー認証によって保護されます。

チャット メッセージ、プロジェクト、アーカイブはサーバー側の Web スタックの MongoDB に保存されます。検索にはMeilisearchを使用します。コントローラーは、ツールの権限、ワーカー ID、セッション状態、監査を個別に所有します。すべての履歴を保持する必要がある場合は、両方のデータ ストアをバックアップします。チャット バックエンドは、LSM ログインではシングルユーザーです。内部 API やデータベースを一般公開しないでください。

UI はトップレベルのアプリであり、**iframe ではありません**。オプションのチャット サービスが構成されていない場合、`/ui` は引き続き元の LSM WebUI を提供します。ネイティブ OpenTUI および外部クライアントは引き続きサポートされます。

## トラブルシューティング

- **リダイレクトは元の UI に残ります:** `LOCAL_SHELL_MCP_LIBRECHAT_URL`、永続的なコントローラー状態バックエンド、および Web スタックの HTTPS リバース プロキシを確認してください。
- **ログインまたはハンドオフが失敗する:** 両側でまったく同じ 32 バイト以上のブリッジ シークレットがあり、同じサイトのオリジン、HTTPS、およびサーバー クロックが一致していることを確認します。
- **チャットは読み込まれますが、応答できません:** 実際のモデル エンドポイントまたは API 資格情報を設定し、チャット コンテナーのログを確認します。
- **MCP ツールがありません:** コントローラーのスコープと会話ごとの切り替えを確認します。ネストされたサーバーレジストリは、LibreChat MCP データベースとは別のものです。
- **ファイルまたはセッションが空であると表示される:** チャットが正しいコントローラーとワークスペースに到達していることを確認し、その API 認証ログを検査します。

実装の詳細と更新については、[the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) および [human interface guide](../guides/human-interface.md) を参照してください。
