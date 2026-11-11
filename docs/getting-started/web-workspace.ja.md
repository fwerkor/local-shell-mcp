<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
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

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## サインインしてチャットを使用する

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

チャットのアップロード (最大 32 MiB) はコントローラー ワークスペースに保存され、その絶対パスがモデルに提供されます。ブラウザーのアップロードでは、追加のファイル権限は付与されません。モデルに面したツールの呼び出しは、LSM 認証、監査、およびリモート ワーカー ルーターを通過します。

## 外部 MCP、セキュリティ、データ

ワークスペース MCP サイドバーを使用して、ネストされた外部 MCP サーバーを管理します。これは、個別のプライベート環境変数と要求ヘッダーを含む、ローカルの stdio サーバーと HTTP サーバーをサポートします。シークレットはブラウザーに返されません。 **外部 MCP** チャット トグルを使用すると、ネストされたツールの検索、検査、呼び出しが可能になります。ネイティブ LSM ツールが無効になっている場合、モデル `mcp_manage` は付与されません。 UI 管理は、通常のコントローラー認証によって保護されます。

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## トラブルシューティング

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

実装の詳細と更新については、[the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) および [human interface guide](../guides/human-interface.md) を参照してください。
