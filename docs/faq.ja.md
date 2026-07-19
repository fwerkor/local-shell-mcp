# よくある質問

このページでは、LSM サーバー自体が正常でも障害のように見える、繰り返し発生する Client とリバースプロキシの問題をまとめます。

## LSM の更新後に ChatGPT で一部のツールが使えないのはなぜですか？

### 症状

- 新しいツールが ChatGPT に表示されない。
- ChatGPT が削除、名称変更、統合された古いツールを呼び出そうとする。
- ツールは存在するが、古い入力スキーマが送信されて検証に失敗する。
- LSM の再起動や新しい会話では解決しない。

### 原因

ChatGPT は、MCP App のスキャン、承認、公開時に存在したツールと入力スキーマの凍結スナップショットを保持することがあります。LSM の更新で `tools/list` が変わっても、そのスナップショットが自動更新される保証はありません。公開された有効期限を持つ短期キャッシュではありません。

### 解決方法

=== "開発者モードまたは個人接続"

    1. **ChatGPT Settings → Apps** を開きます。
    2. LSM App を開き、**Refresh** でツールを再スキャンします。
    3. Refresh がない場合は古い App を削除し、同じ MCP エンドポイントを追加し直します。
    4. 新しいツール一覧を受け入れた後、新しい会話を開始します。

=== "ChatGPT Business で公開済みの App"

    現在、公開済みのカスタム App はツールやメタデータをその場で更新できません。ワークスペース管理者が新しい App を作成し、現在の LSM エンドポイントをスキャンして公開し、古い App を廃止する必要があります。

=== "ChatGPT Enterprise または Edu"

    ワークスペース管理者は **Workspace Settings → Apps → LSM App → … → Action control → Refresh** を開き、差分を確認して必要な新しい action を有効化できます。

[Issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) と [OpenAI の MCP App ドキュメント](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)も参照してください。

## Nginx の背後で WebUI が再接続を繰り返すのはなぜですか？

### 症状

- WebUI ページと OAuth ログインは正常に読み込める。
- TUI が表示されない。
- 状態が `Connecting`、`Connection error`、`Reconnecting` の間で繰り返し変化する。
- ポート `8765` に直接接続すると動作する。

### 原因

ブラウザー UI は PTY WebSocket 経由でネイティブ TUI を描画します。既定のエンドポイントは `/ui/ws` で、`ui_path` を変更した場合は `${ui_path}/ws` です。通常の Nginx `proxy_pass` は WebSocket アップグレードに必要な hop-by-hop ヘッダーを自動転送しません。

### 解決方法

HTTP/1.1 を有効にし、`Upgrade` と `Connection` ヘッダーを転送します。

```nginx
# map は http ブロック内に配置します。
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

設定後、Nginx を検証して再読み込みします。

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Nginx Proxy Manager では Proxy Host の **Websockets Support** を有効にします。まだ再接続する場合は Advanced 設定に同等のアップグレードヘッダーを追加してください。

### 確認

ブラウザーの開発者ツールで WebUI を再読み込みし、`/ui/ws` リクエストを確認します。正常な接続では次が返ります。

```text
101 Switching Protocols
```

[Issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71)も参照してください。
