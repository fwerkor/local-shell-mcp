<!-- i18n-source-sha256: c8c0d8ebdbb123b9ac4af1fd288f30e8ca69037ca086486cb8027e2592f4b75a -->
# Python、pipx、source runtimes

**ソースチェックアウトからの直接インストールを推奨します。** Python 仮想環境と権限を制限したワークスペースを使用してください。Docker Compose も利用できます。

このページは次の 3 つの関連ケースを扱います。

- `pipx install local-shell-mcp`: user-level executable install。
- `pip install local-shell-mcp`: 既存 virtual environment への install。
- Editable source checkout: project 自体の開発やデバッグ。

## pipx install

通常のユーザーには `pipx` が最も扱いやすい Python-based install です。command 専用の virtual environment を作りつつ、executable を `PATH` に公開します。

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

ローカル HTTP MCP server を起動します。

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Health を確認します。

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Virtual environment install

Python environment を自分で管理している場合はこちらを使います。

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

process は host にインストールされた tool を使用します。Python package が compiler、Git、browser system dependency、project dependency を代わりにインストールすることはありません。

## Editable source checkout

通常のデプロイと開発に使用します。公開アクセスの設定は [quickstart](../getting-started/quickstart.md).

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

チェックを実行します。

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Browser setup

Playwright はオプションです。必要な場合のみライブラリーとブラウザーをインストールしてください。

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

ブラウザーのインストールは任意です。Docker の基本イメージに Playwright やブラウザーは含まれません。

## Public HTTP MCP use

ChatGPT または別の public HTTP MCP client で使う場合は、他の HTTP runtime と同じ public-origin/OAuth 設定を行い、local port を reverse proxy または tunnel 経由で公開します。

公開 MCP endpoint：

```text
https://your-public-host.example.com/mcp
```

## Development modes

| Mode | Command | 用途 |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | HTTPS 背後の ChatGPT を含む、HTTP 経由の完全な MCP client |
| REST-style HTTP | `local-shell-mcp --mode http` | 診断または互換 endpoint。ChatGPT の主経路ではありません |
| stdio | `local-shell-mcp --mode stdio` | process を起動するローカル MCP client |

`mode=both` は予約済みで、現在は単一 process mode として使用すべきではありません。

## Host-runtime safety

Python install は VM/container に入れない限り host user の権限で実行されます。workspace を狭くし、full-container mode は無効にしたまま、workspace を home directory に向けないでください。

信頼できない repository、package-manager を多用する task、または host integration より resetability が重要な workflow では Docker Compose を使用してください。
