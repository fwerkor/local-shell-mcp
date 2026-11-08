<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# 獨立二進制運行時

推薦從 GitHub Releases 下載 **Controller 單檔可執行程式**直接部署。Controller 不需預裝 Python、Docker 或複製原始碼。

這是運行時選擇。ChatGPT 訪問需要另外通過 HTTPS `/mcp` 端點配置。

## Release 產物

GitHub Releases 會爲常見平臺構建自包含可執行文件：

| 平臺產物 | 壓縮包 |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

每個壓縮包包含可執行文件、README、license 和簡短 quickstart 文件。

也可直接下載**單檔可執行程式**。該檔案只包含 Controller 和原生 WebUI；聊天、資料庫、Worker、宿主工具與瀏覽器執行環境需另行部署。

## 安裝

1. 從 [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) 下載平台對應的單檔程式或壓縮檔。
2. 若下載壓縮檔，先解壓。
3. 把可執行文件放到 `PATH` 中，或記錄其絕對路徑。
4. 運行 `local-shell-mcp --help`，確認二進制能啓動。

以下示範直接下載 Linux x86_64 單檔程式；其他平台請選對應產物：

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Windows 用戶應在 PowerShell 中運行 `local-shell-mcp.exe`，或把所在目錄加入 `PATH`。

## 最小本地運行

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

另開一個終端檢查：

```bash
curl -i http://127.0.0.1:8765/healthz
```

## 公開 HTTP MCP 運行

對於 ChatGPT 或公開 HTTP MCP 客戶端，需要配置這些類別：

| 設置 | 用途 |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | 工具控制的目錄 |
| `LOCAL_SHELL_MCP_HOST` 和 `LOCAL_SHELL_MCP_PORT` | 本地綁定地址和端口 |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | 公開 HTTPS origin，不含 `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | 公開部署使用 `oauth` |
| OAuth PIN 和 JWT secret 設置 | 公開 OAuth 授權所需 |

通過反向代理或隧道暴露本地 HTTP 端口。公開端點是：

```text
https://your-public-host.example.com/mcp
```

## YAML 配置

YAML 配置可以保存非敏感運行時默認值：

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

運行：

```bash
local-shell-mcp --config /path/to/config.yaml
```

帶有 `LOCAL_SHELL_MCP_` 前綴的環境變量會覆蓋 YAML 值。

## 宿主機工具鏈責任

二進制打包的是 Python 應用本身，不包含所有開發者工具。MCP 工具會調用宿主機上可用的程序。

按任務需要安裝工具：

| 能力 | 可考慮的宿主機包 |
|---|---|
| 搜索與 shell 易用性 | `ripgrep`、`tree`、`jq`、`curl`、`wget`；Linux 發行包已內置靜態 tmux helper |
| Git 工作流 | `git`、`gh`、OpenSSH client、credential helper |
| Python 項目 | Python、pip、venv、項目特定編譯器和頭文件 |
| Node 項目 | Node.js、npm、pnpm、yarn |
| Rust / Go / Java / C++ | Cargo / rustc、Go、JDK、Maven / Gradle、編譯器、CMake、Ninja |
| 瀏覽器自動化 | Playwright 瀏覽器二進制和系統依賴 |
| 文檔轉換 | LibreOffice、Pandoc、Poppler 工具 |

單檔程式包含 Controller，工作所需工具仍由主機提供；瀏覽器相依套件可按需安裝。整合聊天與歷史記錄需另外部署 [統一 Web 工作區](../getting-started/web-workspace.md) 及資料庫。

## 長時間服務

持久公開部署時，把二進制交給操作系統進程管理器運行。保持這些做法：

- 使用專用低權限 OS 賬號。
- 使用專用工作區目錄。
- 把敏感值保存在非公開可讀文件之外。
- 失敗後自動重啓。
- 每次重啓後檢查 `/healthz`。
- 保留日誌以便排查。

## 更新

1. 替換發布的可執行檔後重新啟動 Controller：
2. 如有需要，校驗 checksum。
3. 替換可執行文件。
4. 重啓進程管理器。
5. 檢查 `/healthz`。
6. 讓客戶端先運行 `environment_get`，再繼續工作。

## 安全說明

二進制會以其操作系統用戶的權限運行。公開部署時，儘量使用專用低權限用戶、專用工作區，以及 VM 或容器邊界。

不要讓直接運行在個人宿主機上的二進制設置 `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true`。該設置面向一次性容器或 VM。
