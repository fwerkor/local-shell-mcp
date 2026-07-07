# Python、pipx 與源碼運行時

Python 運行時適合開發、調試，以及 Python 包管理比 Docker 更容易維護的環境。它運行的服務與 Docker 和二進制運行時相同。

本頁覆蓋三個相關場景：

- `pipx install local-shell-mcp`：用戶級可執行文件安裝。
- `pip install local-shell-mcp`：安裝到已有虛擬環境。
- 可編輯源碼 checkout：開發或調試項目本身。

## pipx 安裝

對普通用戶而言，`pipx` 是最乾淨的 Python 安裝方式：它會爲命令創建獨立虛擬環境，同時把可執行文件暴露到 `PATH`。

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

啓動本地 HTTP MCP 服務：

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

檢查健康狀態：

```bash
curl -i http://127.0.0.1:8765/healthz
```

## 虛擬環境安裝

當你已經手動管理 Python 環境時，使用這種方式：

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

該進程使用宿主機上已安裝的工具。Python 包不會替你安裝編譯器、Git、瀏覽器系統依賴或項目依賴。

## 可編輯源碼 checkout

用於項目開發：

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e '.[dev,docs]'
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/tmp/local-shell-mcp-workspace local-shell-mcp --mode mcp
```

運行檢查：

```bash
ruff check .
pytest -q
mkdocs build --strict
```

## 瀏覽器設置

Python 包依賴 Playwright，但宿主機上可能仍需要安裝瀏覽器二進制：

```bash
python -m playwright install chromium
```

部分 Linux 宿主機還需要額外瀏覽器系統依賴。Docker 大多能避免這些問題，因爲鏡像基於 Playwright base image。

## 公開 HTTP MCP 使用

對於 ChatGPT 或其它公開 HTTP MCP 客戶端，配置與其它 HTTP 運行時相同的公開 origin 和 OAuth 設置，然後通過反向代理或隧道暴露本地端口。

公開 MCP 端點是：

```text
https://your-public-host.example.com/mcp
```

## 開發模式

| 模式 | 命令 | 用途 |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | 通過 HTTP 使用完整 MCP 客戶端，包括位於 HTTPS 之後的 ChatGPT |
| REST 風格 HTTP | `local-shell-mcp --mode http` | 診斷或兼容端點，不是 ChatGPT 主要路徑 |
| stdio | `local-shell-mcp --mode stdio` | 由本地 MCP 客戶端啓動進程 |

`mode=both` 是保留值，目前不應作爲單進程模式使用。

## 宿主機運行時安全

除非放在 VM 或容器中，Python 安裝會以你的宿主機用戶身份運行。保持工作區範圍較窄，關閉 full-container 模式，不要把工作區指向 home 目錄。

對於不可信倉庫、依賴包安裝較多的任務，或更重視可重置性的工作流，使用 Docker Compose。
