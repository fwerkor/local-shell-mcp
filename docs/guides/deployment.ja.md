<!-- i18n-source-sha256: 594169d44520f8abd7cebee1bfa42c5ff0ca31f424115d438107ed01b77fa604 -->
# Runtime の選択とデプロイモデル

`local-shell-mcp` には 2 つの相補的な決定があります。

1. **Runtime**: server process をどのように実行し、どの workspace を制御するか。
2. **インターフェイス**: オプションの [unified web workspace](../getting-started/web-workspace.md) を使用するか、Gemini や ChatGPT などの外部 MCP クライアントに接続します。

推奨される毎日のインターフェイスは、自己ホスト型 Web ワークスペース (チャット、プロジェクト、LSM コントロール ページ) です。コントローラーとは別にデプロイされます。 Docker、VS Code 拡張機能、リリース バイナリ、Python インストール、および stdio モードは、コントローラーを実行する方法です。外部チャット アプリはオプションのクライアントのままです。

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose ローカル HTTP のみの統合 Web ワークスペース
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

一般的な自己ホスト型セットアップは次のとおりです。

```text
ブラウザ -> https://chat.example.com (統合 Web ワークスペース)
        -> 認証された local-shell-mcp コントローラー
        -> 管理されたワークスペースとアウトバウンド労働者
オプションの外部クライアント -> https://mcp.example.com/mcp
```

local MCP client の setup はさらに単純です：

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

## Runtime 選択マトリクス

| ランタイム | こんな方に最適 | 分離境界 | ツールチェーンのソース | 外部 MCP アクセス | ページ |
|---|---|---|---|---|---|
| Docker Compose | ほとんどのコーディング エージェントのワークロードと反復可能なワークスペース | コンテナ | 無駄のないコントローラーのイメージ。タスク固有のツールチェーンを個別にインストールする | HTTPS プロキシまたはトンネルを追加する | [Docker Compose](../installation/docker.md) |
| Docker Compose + トンネル サイドカー | Cloudflareトンネルを使用したパブリックコントローラーのデプロイメント | コンテナ | プロジェクトイメージ | Compose `tunnel` プロファイルに組み込まれています | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | editor workspace から server を start/stop | 通常 host process | host tools と設定済み executable | ChatGPT 用に外部 HTTPS tunnel/proxy を追加 | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Docker が使えない host/VM | Host or VM | host tools と設定済み executable | HTTPS proxy または tunnel を追加 | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Python-native 利用、debug、development | Host virtualenv or VM | Python package と host tools | HTTPS proxy または tunnel を追加 | [Python install](../installation/python.md) |
| Stdio mode | tool process を直接 spawn する local MCP client | Client process boundary | host tools と設定済み executable | ChatGPT web/app では使用不可 | [Stdio mode](../installation/stdio.md) |

## Client 接続マトリクス

| インターフェース | パブリックHTTPSが必要です | `/mcp`を使用します | OAuthが必要です | 一般的なランタイム |
|---|---:|---:|---:|---|
| 統合 LSM Web ワークスペース | リモートアクセスの場合ははい。ローカルプロキシも可能 | 内部的に | LSMログイン | コントローラーと個別の Web スタック |
| Gemini Spark / カスタム アプリ | はい | はい | はい、公共使用可能 | 任意の HTTP コントローラー |
| ChatGPT custom MCP connector | はい | はい | public 利用では必須 | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | いいえ | いいえ | いいえ | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | localhost では通常不要、network 越しでは必要 | はい | localhost 外では推奨 | Any HTTP runtime |
| VS Code extension helper flow | ChatGPT を接続する場合のみ | ChatGPT URL を copy する場合は使用 | ChatGPT では推奨 | VS Code-launched runtime |

[unified web workspace](../getting-started/web-workspace.md)、[Gemini Spark](../getting-started/gemini-spark.md)、[ChatGPT connector](../getting-started/chatgpt-connector.md)、[generic MCP clients](../clients/generic-mcp.md)、および [network connectivity](../clients/connectivity.md) を参照してください。

## 各 runtime が制御するもの

どの runtime も同じ server code を起動し、有効化された場合は同じ MCP tool family を公開します：

- Shell と persistent shell session。
- Filesystem、search、patch tools。
- Git operations。
- Playwright による browser automation。
- Audit log と task-state tools。
- Tokenized file links。
- Optional remote-worker lifecycle と machine-routed tools。

違うのは抽象 API ではなく、その背後の **operating environment** です。

| 質問 | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Command はどこで実行？ | container 内 | 通常 host workspace 上 | host または VM process environment |
| Default workspace は？ | Mounted `/workspace` | 現在の VS Code folder または設定 path | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| コンパイラとブラウザはプリインストールされていますか? | いいえ;タスクに必要なものをインストールする | ホストにインストールされている場合のみ | ホストにインストールされている場合のみ |
| Reset は容易？ | container と workspace volume を再作成 | workspace 次第 | host/VM 次第 |
| 任意 package install に適切？ | disposable なら適切 | host では risk が高い | VM 内でなければ risk が高い |

## 推奨選択

理由がない限り、最初に **Docker Compose** を使用してください。これにより、事前にインストールされた大規模な開発ツールチェーンを必要とせずに、明確な安全境界が得られます。

ワークフローがエディターから開始され、ローカル ランチャーが必要な場合は、**VS Code 拡張機能** を使用します。まだランタイムです。リモート Web クライアントには、到達可能な HTTPS プロキシまたはトンネルが必要です。

Docker が使えず、VM/container host/dedicated user account が boundary を提供する場合は **standalone binary** を使います。

`local-shell-mcp` 自体の development/debug、または Python-based environment が管理しやすい場合は **`pipx` または source install** を使います。

server process を spawn できる local MCP client のみ **stdio mode** を使います。public deployment ではなく、ChatGPT web/app から直接は利用できません。

## Public endpoint のルール

Gemini や ChatGPT などの外部 HTTP MCP クライアントの場合、MCP エンドポイントは次のとおりです。

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` は origin のみです：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` に `/mcp` を追加しないでください。

## Runtime ページ

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Client ページ

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
