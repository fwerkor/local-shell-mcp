# Docker Compose

このページでは「Docker Compose」の場面を説明し、サイト全体で共通の Runtime/Client 構造に従います。

## 概要

Runtime はサーバープロセスの起動方法と制御するワークスペースを決めます。Client は ChatGPT または別の MCP クライアントの接続方法を決めます。Docker、VS Code 拡張、スタンドアロンバイナリ、Python/pipx/ソースインストール、stdio は Runtime の選択肢です。ChatGPT コネクタ、汎用 HTTP MCP クライアント、stdio MCP クライアントは Client 接続です。

## 利用する場面

- 選択した Runtime または Client の経路がこのページのタイトルに一致する場合に使用します。
- ワークスペースルート、公開 base URL、MCP endpoint、認証モード、ホストで利用できるツールをそろえます。
- ChatGPT の Web/App では `/mcp` で終わる HTTPS MCP endpoint を公開します。
- ローカル MCP クライアントでは、対応状況に応じて HTTP localhost または `local-shell-mcp --mode stdio` を使用します。

## 手順

1. まず Runtime のインストールページを選びます。
2. Runtime を起動し、HTTP モードでは `/healthz` を確認します。
3. 次に Client 接続ページを選びます。
4. Client に MCP endpoint または stdio コマンドを登録します。
5. `environment_info` を呼び出して実際のワークスペースと設定を確認します。

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## 検証

- `environment_info` は Runtime 設定とワークスペースを確認します。
- `tree_view` は見えているファイルを確認します。
- `git_status_tool` はリポジトリの文脈を確認します。
- `run_shell_tool` はコマンド実行環境を確認します。

## 注記

小さく検証可能な手順を優先します。確認、編集、diff、テスト、スキャン、コミットの順に進めます。大きな作業も監査可能なツール呼び出しに分解します。
