<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# デスクトップ GUI 自動化

`local-shell-mcp` は Linux、Windows、macOS 上のネイティブデスクトップアプリケーションを観察・操作できます。公開インターフェースは意図的に小さく保たれています。

| ツール | 目的 |
|---|---|
| `gui_list` | 表示中のアプリケーションウィンドウを列挙し、有効なネイティブバックエンドと機能を返します。 |
| `gui_state` | 1 つのウィンドウを観察します。短時間有効な `state_id`、アクセシビリティ要素、ウィンドウ形状、必要に応じてネイティブ MCP スクリーンショットを返します。 |
| `gui_action` | その観察結果に対して、セマンティック操作または座標操作を実行します。 |

3 つのツールはいずれも任意の `machine` を受け取れるため、同じ手順で接続済みのデスクトップ worker を操作できます。

## 観察してから操作する

まず `gui_list` を呼び、`window_id` を選択してから `gui_state` を呼びます。対象コントロールに対応するアクセシビリティ `element_id` が返される場合は、それを優先してください。

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

ウィンドウ相対の `x`/`y` 座標は、canvas や独自描画コントロールなど、有用なアクセシビリティ要素がない場合だけ使用してください。要素の境界とスクリーンショットは、HiDPI/Retina 環境を含め、同じウィンドウ相対の論理ピクセル空間を使用します。選択したウィンドウ外の生座標は拒否されます。

`state_id` は 30 秒で期限切れになり、1 回だけ使用できます。座標操作では、観察後に対象ウィンドウが移動またはサイズ変更されていないことも確認されます。いずれかの確認に失敗した場合は、古い座標を再利用せず `gui_state` を再度呼んでください。

対応する操作は `click`、`double_click`、`right_click`、`move`、`scroll`、`drag`、`type`、`key`、`set_value`、`focus`、`wait` です。

## Native WebUI での人間による操作

Native WebUI には、同じネイティブ GUI バックエンドを人間が直接操作する **Desktop** ページがあります。マシンとウィンドウを選択し、表示画像上でクリック、ダブルクリック、右クリック、ドラッグ、ホイール、キーボードショートカット、または IME/CJK 入力用のテキスト欄を使用できます。

この経路はモデル用 `state_id` の意味論とは意図的に分離されています。表示フレームには観察時のウィンドウ形状が含まれ、人間の入力要求ごとに、入力注入前にその形状が完全に一致していることを検証します。ウィンドウが移動・リサイズ・消失している場合、操作は拒否され WebUI が観察を更新します。生座標は常に選択ウィンドウ内に制限されます。

キーボード操作とテキスト入力では、注入前に選択したネイティブウィンドウへ明示的にフォーカスします。WebUI は VNC/WebRTC の動画配信ではなく軽量なスクリーンショットポーリングを使用します。リモート専用 `gui_human_action` RPC は controller から worker への内部操作であり、モデルに公開される MCP ツールではありません。

## ネイティブバックエンド

| プラットフォーム | アクセシビリティ / セマンティック操作 | キャプチャと生入力 |
|---|---|---|
| Windows | Microsoft UI Automation | ウィンドウキャプチャと Windows ネイティブのマウス・キーボード入力 |
| macOS | Accessibility (`AXUIElement`) | 選択ウィンドウの `screencapture` と Quartz `CGEvent` 入力 |
| Linux | AT-SPI | X11 のネイティブ入力/キャプチャ。Wayland ではネイティブデスクトップキャプチャと XDG Desktop Portal RemoteDesktop/ScreenCast を使用 |

可能な場合はセマンティック操作を先に試します。そのため、ネイティブの invoke/press 操作を持つボタンはピクセル座標を推測せずに起動できます。アクセシビリティ非対応や独自描画コンテンツでは視覚座標がフォールバックになります。

## プラットフォーム設定

### Windows

LSM は操作対象アプリケーションと同じ対話型デスクトップセッションで実行してください。基本の `local-shell-mcp` は headless 環境でも安全で、Windows UI Automation adapter を必須としません。ローカル Windows GUI 操作が必要な場合だけ、任意の `local-shell-mcp[gui]` extra をインストールします。

### macOS

LSM のホストプロセスに次の権限を付与してください。

- セマンティック操作と入力のための **アクセシビリティ** 権限。
- スクリーンショットのための **画面収録** 権限。

基本パッケージは PyObjC を必須としません。ローカル macOS GUI 操作が必要な場合だけ `local-shell-mcp[gui]` extra をインストールしてください。GUI ツールを使わないマシンではこれらの framework は不要です。

### Linux

デスクトップセッションは AT-SPI を公開する必要があります。Debian/Ubuntu では通常、次のコマンドで必要なシステム binding を導入できます。

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

基本パッケージは Python の X11/D-Bus adapter を必須としません。任意の `local-shell-mcp[gui]` extra がローカル GUI 用にそれらを導入します。リモート worker は GUI 依存関係の bootstrap 前に有効な Linux セッションを検出し、X11 では X11 adapter、Wayland では D-Bus adapter のみを必要とし、headless worker はどちらもインストールしません。Wayland の生ポインター/キーボード fallback は XDG Desktop Portal RemoteDesktop API を使用するため、初回に権限/セッション選択画面が表示される場合があります。KDE と GNOME の portal 実装に対応しています。ウィンドウのスクリーンショットは利用可能なネイティブキャプチャを使用し、必要に応じて Screenshot portal にフォールバックします。

LSM worker はグラフィカルログイン環境外で起動されることがあります。Linux backend は、直接継承されていない場合、ユーザーの systemd 環境から `DISPLAY`、`WAYLAND_DISPLAY`、`XDG_SESSION_TYPE` などを復元します。

## リモートデスクトップ

GUI ツールは controller ではなく選択したマシン上で実行されます。リモート worker は対象デスクトップを所有するユーザー/セッションに属している必要があります。GUI adapter は lazy に読み込まれ、GUI 呼び出しに限定されます。通常の worker 起動や shell/files/browser の使用ではインストールも import も行いません。Linux の headless worker は GUI 用 pip bootstrap より前に GUI unavailable を返し、グラフィカル worker は有効な X11/Wayland セッションに必要な adapter だけを確認またはインストールします。

リモート `gui_state` が返すスクリーンショットは LSM のファイル転送経路で転送され、ネイティブ MCP 画像コンテンツとしてモデルに公開されます。worker の JSON 応答には埋め込まれません。
