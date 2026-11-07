<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# ネットワーク接続

マシンの外部にある HTTP MCP client から接続するには、到達可能な HTTPS origin が必要です。このページではネットワーク経路を扱い、どの runtime を選ぶかは扱いません。

client endpoint は通常 `/mcp` で終わります。

```text
https://your-public-host.example.com/mcp
```

サーバーの public base URL 設定には origin だけを指定します。

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

この base URL に `/mcp` を含めないでください。

## 接続方法

**推奨:** 公開アクセスには、公開サーバーへの直接デプロイ、または公開サーバー経由の転送と HTTPS リバースプロキシを使用してください。

**非推奨:** Cloudflare Tunnel はクライアント側のアップロード速度が非常に遅くなる場合があり、ファイルのアップロードや転送が実用的でなくなります。公開サーバーや転送経路を用意できない場合のみ使用してください。


| 方法 | 使用する場面 |
|---|---|
| Caddy | 自動 TLS を簡単に使いたい場合 |
| Nginx / Nginx Proxy Manager | 既存の Nginx インフラがある場合 |
| Traefik | 既存のコンテナネイティブなルーティングがある場合 |
| 公開サーバー経由の転送 | 公開アクセスには、公開サーバーへの直接デプロイ、または公開サーバー経由の転送と HTTPS リバースプロキシを使用してください。 |
| Cloudflare Tunnel（非推奨） | 公開サーバー経由で転送し、Cloudflare Tunnel は最終手段にする |

## パス

origin 全体を実行中のサーバーへ転送してください。重要なパスは次のとおりです。

| パス | 用途 |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | ヘルスチェック |
| `/.well-known/...` | client discovery メタデータ |
| `/oauth/...` | client 認可フロー |
| `/downloads/...` | 任意の生成ファイルリンク |
| `/join/...`, `/remote/...` | 任意の remote-worker フロー |

## プロキシの動作

プロキシはパスを保持し、request body を転送し、長時間の response を許可し、極端に短い timeout を避ける必要があります。

## 確認

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## よくある間違い

| 間違い | 修正 |
|---|---|
| ChatGPT で `https://host/mcp` ではなく `https://host` を使う | client endpoint にだけ `/mcp` を追加する |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` と設定する | origin だけを設定する |
| `/mcp` だけをルーティングする | discovery と認可パスも動作するよう origin 全体をルーティングする |
| host runtime で広すぎる workspace を使う | 狭い workspace または Docker を使う |

## 推奨の組み合わせ

| Runtime | ネットワーク構成 |
|---|---|
| サーバー上の Docker Compose | HTTPS リバースプロキシ |
| 自宅マシン上の Docker Compose | 公開サーバー経由で転送し、Cloudflare Tunnel は最終手段にする |
| ノート PC 上の VS Code extension | 公開サーバー経由の転送 |
| VM 上の binary | VM またはネットワーク境界の reverse proxy |
| Python/source 開発サーバー | 通常は localhost のみ |
| Stdio mode | HTTP 経路なし。ローカル MCP client を使う |
