# local-shell-mcp ドキュメント

ChatGPT Developer Mode とその他の MCP クライアント向けのローカル制御プレーンです。制御されたワークスペース、shell、ファイル、Git、ブラウザー自動化、ファイルリンク、リモート worker を MCP ツールとして公開します。

## ドキュメントの導線

- [クイックスタート](getting-started/quickstart.md)
- [ChatGPT コネクタ](getting-started/chatgpt-connector.md)
- [リモート worker](guides/remote-workers.md)
- [セキュリティ](security.md)
- [トラブルシューティング](troubleshooting.md)

## コアアーキテクチャ

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## 重要な安全ルール

公開デプロイでは OAuth を有効にし、Docker socket、ホストのルート、長期認証情報をマウントしないでください。
