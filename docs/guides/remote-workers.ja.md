<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# リモート workers

Remote worker を使うと、外向き HTTP(S) request は送信できるものの、受信 SSH 接続を受け付けられないマシンを `local-shell-mcp` から制御できます。

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## 基本ワークフロー

1. `remote_manage(action="invite", ...)` で招待を作成します。
2. 生成された command を remote machine で実行します。
3. `remote_manage(action="list")` で登録を確認します。
4. `machine="<worker-name>"` を付けて通常のツールを呼び出します。例：`environment_get`、`run_shell`、`file_read`、`browser_run_script`。
5. `remote_transfer` で controller-to-worker、worker-to-controller、worker-to-worker の追跡対象 file/directory transfer を開始します。その後 `job_list` または `job_tail` で確認し、`job_stop` または `job_retry` で停止・再試行します。
6. `remote_manage(action="rename", ...)` または `remote_manage(action="revoke", ...)` で worker を rename/revoke します。

招待コードは既定で 1 台の Worker の登録に使用できます（`max_uses=1`）。同じコードで複数台を登録するには `max_uses` を増やしてください。複数回使用する招待では `name` を空欄にします。省略可能な `ttl_s` の既定値は 2 時間（7200 秒）、上限は 7 日間（604800 秒）です。

`remote_*` 名を使うのは worker administration だけです。execution、shell、job、filesystem、patch、browser 操作は local/remote で同じ schema を共有します。machine を指定する場合は追加で `remote:use` OAuth scope が必要です。

## 永続 worker

招待結果にはプラットフォーム別 command が含まれます。

- `persistent_command` は Linux/macOS で user service をインストールして開始します。
- `powershell_persistent_command` は PowerShell から Windows user task をインストールして開始します。

Windows では `local-shell-mcp worker install-service` が現在のユーザー用に `local-shell-mcp-worker` task を登録します。task は直ちに開始し、再起動後はそのユーザーのログオン時に再開し、バッテリー動作を許可し、重複起動を無視し、失敗した実行を再試行します。管理者権限は不要で、ユーザーがサインインする前には実行されません。

すべての platform で同じ lifecycle command を使用します。

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

worker log は worker state directory の `worker.log` に保存されます。

## 能力

Worker は shell/persistent shell session、tracked job、filesystem operation、transfer internals、Python execution、patch、および依存関係が入っている場合の Playwright をサポートします。Git は `run_shell(machine=...)` から標準 command を使います。

## セキュリティと version

参加済み worker は、その設定された環境に対する制御権を MCP client に与えます。短い invite TTL、専用 work directory/user を使用し、audit log を確認し、タスク後は worker を revoke してください。生成される招待は control server と同じ version の worker code をインストールします。

## トラブルシューティング

worker が表示されない場合は、outbound HTTPS access、public base URL の到達性、invite expiry、system time、control-server log を確認してください。
