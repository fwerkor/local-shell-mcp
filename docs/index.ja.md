<!-- i18n-source-sha256: a66d491558f07c419c8b5958d36c47cd90b081fc1c81f015bb62398cfd573e55 -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">セルフホスト型 AI ワークスペース · MCP コントロール プレーン</span>

# local-shell-mcp

1 つの自己ホスト型インターフェイスでチャット、プロジェクト、ファイル、端末、リモート マシン、AI ツールを実行します。必要に応じて外部 MCP クライアントに接続します。

<div class="hero-actions" markdown>
[はじめる](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Tools reference](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### 実際の coding environment
1 つの MCP endpoint から tests の実行、repository の調査、file patch、Git 操作、audit trail の保持を行えます。
</div>

<div class="feature-card" markdown>
### 統合された Web ワークスペース
組み込みのチャットとプロジェクト履歴を、コントローラー ファイル、ターミナル、デスクトップ、セッション、リモート、監査とともに使用します。外部 MCP クライアントはオプションのままです。
</div>

<div class="feature-card" markdown>
### Remote machine control
SSH port を開かず、outbound worker connection で NAT、firewall、HPC machine を接続します。
</div>
</div>

## 提供するもの

`local-shell-mcp` は、統合された自己ホスト型 AI ワークスペースと外部クライアント用の MCP サーバーを提供します。シェル、永続シェル、ファイルシステム、検索、パッチ、Git、Playwright、監査、オプションの目標プランを備えた耐久性のある論理セッション、トークン化されたファイルリンク、認証された MCP エンドポイントを介したリモート ワーカー ツールを提供します。

AI が repository を調査し、tests を実行し、files を編集し、Git を操作し、browser evidence を収集し、downloadable artifacts を作成し、control server へ outbound 接続しかできない remote machine を制御する必要がある場合に使います。

## アーキテクチャ

```text
Runtime layer: Docker / VS Code extension / binary / Python / stdio
Exposure layer: localhost / HTTPS proxy / tunnel / stdio pipe
クライアント層: 統合 WebUI / Gemini / ChatGPT / 汎用 MCP クライアント
Controlled workspace: /workspace or configured workspace root
Optional remote workers: outbound machine connections
```

意図された isolation boundary は service を実行する container または VM です。

## シナリオ別の入口

| シナリオ | 開始ページ | 理由 |
|---|---|---|
| プライマリブラウザワークスペース | [Unified web workspace](getting-started/web-workspace.md) | 共有ログインを使用したチャット、プロジェクト、LSM コントロール ページ |
| 最初のコントローラーの導入 | [Quickstart](getting-started/quickstart.md) | Docker Compose、OAuth、および最初のブラウザー セッション |
| runtime layer を選ぶ | [Runtime choices](guides/deployment.md) | Docker、VS Code、binary、Python、stdio を別々の runtime option として説明 |
| ジェミニスパークを接続する | [Gemini Custom Apps](getting-started/gemini-spark.md) | 資格、HTTPS MCP URL、OAuth、およびテスト |
| ChatGPT を client として追加 | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint、OAuth、最初の安全な prompt、tool discovery |
| LSM を DeepSeek Harness に追加 | [DeepSeek Harness plugin](clients/deepseek-harness.md) | この repository を DSH bundle として install し、完全な LSM tool/remote-worker surface を維持 |
| VS Code から実行 | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime と host safety の注意 |
| toolset の運用方法を学ぶ | [Usage patterns](guides/usage-patterns.md) | Prompt template と tool 選択ガイド |
| すべての tool を理解 | [Tools reference](reference/tools.md) | 各 tool の purpose、inputs、returns、combinations、notes |
| HPC、NPU/GPU、server node を接続 | [Remote workers](guides/remote-workers.md) | Outbound worker join flow と remote tool usage |
| 生成 file を共有 | [File links](guides/file-links.md) | TTL と revoke を備えた tokenized download URL |
| deployment を harden | [Security](security.md) | Isolation、OAuth、workspace scope、audit logs |

## 主な tool family

| Family | 例 | 用途 |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Build、tests、scripts、long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection と precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Review 可能な source-control workflow |
| Sessions と Goal | `session_manage`, `plan_manage` | durable task handoff、progress report、optional Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction、UI check、screenshot、rendered docs、page text |
| File links | `link_create`, `link_revoke` | Chat から generated artifacts を download |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | NAT、firewall、cluster login flow の背後にある machine |

## 代表的な workflow

### Web ワークスペースでのコーディング

1. LSM コントローラーとオプションの [unified web workspace](getting-started/web-workspace.md) を開始します。
2. `/ui` を開き、LSM ID を使用してサインインします。
3. モデル エンドポイントを構成し、新しい会話を開きます。
4. モデルにリポジトリを検査し、最初に読み取り専用チェックを実行するように依頼します。
5. 承認されたら file patch、tests、diff review、commit、push を行わせます。
6. File link や remote system を扱う task では audit log を確認します。

### Remote HPC / accelerator host

1. 1 回限りの remote worker invite を作成します。
2. 生成された command を remote host に貼り付けます。
3. 通常の tools に `machine` を付け、Git は `run_shell`、path transfer は `remote_transfer` を使います。
4. Task 後に worker を revoke します。

### Artifact generation

1. AI に `/workspace` 下で file を生成させます。
2. TTL/download limit 付き tokenized file link を作ります。
3. Link を chat で共有します。
4. 完了したら revoke します。

## 言語

この site は native MkDocs i18n plugin で build されています。Header の language selector で English と translated pages を切り替えられます。翻訳版がないページは English に fallback します。
