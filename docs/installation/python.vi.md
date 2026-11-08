<!-- i18n-source-sha256: 1d80cfbe14747fb0691e91065f582d1e47eb36921d8b27da1648dcd26114a2e5 -->
# Runtime Python, pipx và source

Nên dùng [binary một tệp](binary.md) cho triển khai thường xuyên. Python và source dành cho phát triển và tùy biến.

Dùng trang này cho ba trường hợp liên quan:

- `pipx install local-shell-mcp`: cài executable cấp người dùng.
- `pip install local-shell-mcp`: cài vào virtual environment hiện có.
- Editable source checkout: phát triển hoặc gỡ lỗi chính project.

## Cài bằng pipx

`pipx` là cách cài dựa trên Python sạch nhất cho người dùng thông thường vì mỗi command có virtual environment riêng trong khi executable vẫn được đưa lên `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Khởi động server MCP HTTP cục bộ:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Kiểm tra sức khỏe:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Cài trong virtual environment

Dùng khi bạn đã tự quản lý các môi trường Python:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

Process dùng các tool đã cài trên host. Package Python không tự cài compiler, Git, browser system dependency hoặc project dependency cho bạn.

## Editable source checkout

Source thích hợp cho phát triển; triển khai thông thường nên dùng [binary](binary.md). OAuth/HTTPS: [bắt đầu nhanh](../getting-started/quickstart.md).

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

Chạy kiểm tra:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Thiết lập trình duyệt

Playwright là tùy chọn; chỉ cài thư viện và trình duyệt khi cần.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Cài trình duyệt là tùy chọn; image Docker cơ bản không có Playwright hoặc trình duyệt.

## Dùng HTTP MCP công khai

Với ChatGPT hoặc public HTTP MCP client khác, cấu hình cùng public-origin và OAuth như các runtime HTTP khác, sau đó expose local port qua reverse proxy hoặc tunnel.

Endpoint MCP công khai:

```text
https://your-public-host.example.com/mcp
```

## Chế độ phát triển

| Mode | Command | Sử dụng |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | MCP client đầy đủ qua HTTP, gồm ChatGPT sau HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Endpoint chẩn đoán hoặc tương thích, không phải đường chính của ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | MCP client cục bộ tự khởi chạy process |

`mode=both` được dành riêng và hiện không nên dùng như mode của một process đơn lẻ.

## An toàn host runtime

Cài đặt Python chạy với quyền host user trừ khi đặt trong VM/container. Giữ workspace hẹp, full-container mode tắt và không trỏ workspace tới home directory.

Dùng Docker Compose cho repository không tin cậy, task dùng nhiều package manager hoặc workflow mà resetability quan trọng hơn tích hợp host.
