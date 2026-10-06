<!-- i18n-source-sha256: f471795a57e16e999999f856000b779183d5b6c642ffc8c852c77e7faf3bc0dd -->
# 利用パターンと prompt ガイド

`local-shell-mcp` は強力な tools を公開します。良い結果を得るには、まず inspect し、小さな step で操作し、verification を実行し、変更内容を報告するようモデルに指示します。

## 一般的な操作ループ

多くの coding task では次のループを使います：

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read`、および `git status` などを `run_shell` で実行します。
2. Plan: 関係する最小限の files と tests を特定させます。
3. Edit: unified `file_edit`, `file_patch` または shell commands を使います。
4. Verify: `run_shell` または persistent shells で targeted tests/builds を実行します。
5. Review: `run_shell` で `git diff` を実行し、必要なら `secret_scan` と `audit_tail` を使います。
6. Commit/export: `run_shell` で明示的な Git CLI commands、または `link_create` を使います。

## Tool の選び方

| Task | 推奨 | 避ける |
|---|---|---|
| 短い one-shot command | `run_shell` | command ごとに persistent shell を開始 |
| 長時間 dev server、REPL、watch task | `shell_start` + `shell_read` + `shell_send` | timeout まで `run_shell` を block |
| structured analysis / file generation | `run_python` | 複雑な JSON/text に壊れやすい shell pipeline |
| 小さな exact edit | `file_edit` | 不要な whole-file rewrite |
| 1 file 内の複数置換 | `file_edit` with an `edits` array | 再読せず stale edit を繰り返す |
| multi-file patch | `file_patch` | ad hoc shell edit |
| file 検索 | `file_tree`, `file_glob` | 大規模 repository の完全 recursive listing |
| code 検索 | `file_grep` | 多数の file を盲目的に読む |
| browser evidence | `browser_snapshot`, `browser_run_script` | page name/route から推測 |
| downloadable artifacts | `link_create` | 大きな binary content を chat に貼る |
| remote machine work | normal tools with `machine`, plus `remote_transfer` | outbound worker で足りるのに inbound SSH を開く |

## CLI からツールを呼び出す

シェルスクリプトや CI では、`lsm call <tool>` が実行中の loopback controller 経由で同じ登録済みツール群を呼び出すため、remote worker と controller の状態が維持されます。

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

`--session s_...` を使うと呼び出しを Logical Session に関連付けられます。Docker Compose では repository ルートから実行すれば既定の共有 token パスが自動検出されます。controller が別の runtime ファイルシステムを使う場合は `--token-file <path>` を指定できます。`--direct` は controller を経由せず、ローカル専用です。

## Prompt テンプレート

### Read-only repository orientation

```text
local-shell-mcp を使用してください。repository layout と git status を調べ、file は変更しないでください。変更前に主要 component、推測できる test command、明らかな risk を要約してください。
```

### Focused bug fix

```text
local-shell-mcp で bug を修正してください。まず最小限の relevant command で再現または場所を特定し、edit 前に files を読んでください。最小 patch を作成し、targeted verification を実行してから git diff と実行した tests を正確に示してください。承認するまで commit しないでください。
```

### Commit と push workflow

```text
local-shell-mcp を使用してください。git status と diff を確認し、関連 tests と secret_scan を実行し、簡潔な message の focused commit を 1 つ作成して current branch を push してください。cache、build artifact、無関係な formatting は含めないでください。
```

### 長時間 process

```text
dev server を persistent shell session で起動し、ready になるまで output を読み、その後 browser tools で page を確認してください。session id を保持し、確認後に kill してください。
```

### Remote worker task

```text
接続済み remote worker <machine> を使用してください。まず machine=<machine> で environment_get を呼び、同じ machine で file_list を実行してください。configured remote workdir 内だけで作業し、短い command は run_shell、長時間処理は shell_start または job_start を使ってください。
```

## Repository での作業

open-source change の推奨 sequence：

1. `run_shell` で `git status --short --branch` を実行します。
2. upstream state が重要なら明示的な Git CLI で fetch/branch inspect を行います。
3. edit 前に `file_grep` と `file_read` を使います。
4. 最小 patch を作ります。
5. まず targeted tests、可能なら broader tests を実行します。
6. commit/push 前に `secret_scan` を実行します。
7. 明示的に stage/commit し、簡潔な message を使います。

maintainer が review しやすいよう、logical change ごとに 1 commit を依頼してください。

## 生成 artifact の扱い

PDF、report、screenshot、archive、log の場合：

1. workspace 内に file を生成します。
2. file の存在と想定 size を確認します。
3. 短い TTL と optional `max_downloads` で `link_create` を使います。
4. 不要になった link を revoke します。

private key、credential directory、無関係な personal data への public link を作成しないでください。

## Remote machine での作業

Remote worker mode は outbound HTTPS は可能だが inbound SSH を受けられない machine に適しています。

推奨：

- `remote_manage(action="invite", ...)` または `remote_manage(action="rename", ...)` で machine を作成/rename します。
- 操作前に `environment_get(machine=...)` を呼びます。
- `remote_transfer` で controller/worker または worker/worker transfer job を開始し、通常の `job_*` tools で管理します。
- task 後は `remote_manage(action="revoke", ...)` で worker を revoke します。

## Anti-patterns

environment が disposable で結果を理解している場合を除き、次の指示を避けてください：

- host-launched server で「必要なものを global に何でも install」。
- 時間制限や verification criteria なしで「動くまで実行」。
- generated artifacts を含む repository で「すべて commit」。
- 便利だから「home directory 全体を expose」。
- 「workspace 全体の file link を作成」。
- `LOCAL_SHELL_MCP_AUTH_MODE=none` で public deployment を実行。
