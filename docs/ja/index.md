# local-shell-mcp 日本語ドキュメント

ChatGPT Developer Mode と他の MCP クライアント向けのローカル制御プレーンです。制御されたワークスペース、shell、ファイル、Git、ブラウザ自動化、ファイルリンク、リモートワーカーを MCP ツールとして提供します。

## Documentation paths

- [クイックスタート](getting-started/quickstart.md)
- [ChatGPT コネクタ](getting-started/chatgpt-connector.md)
- [リモートワーカー](guides/remote-workers.md)
- [セキュリティ](security.md)
- [トラブルシューティング](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

公開環境では OAuth を必ず有効にし、Docker socket、ホスト root、長期認証情報をマウントしないでください。
